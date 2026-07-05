"""Phase 1, Step A: ingest real OSM assets for the locked pilot bbox -> objects.

Doctrine (see 07, 09 and hard rule 1):
  * This step writes OBJECTS ONLY. It creates NO links. Link inference
    (crosses / carries / connects / access_via / serves / on_floodplain) feeds the
    deterministic engine, so per the project rule it is built separately WITH TEST
    CASES (Step B, an Opus session). Because Step A makes no links, it cannot produce
    a wrong impact.
  * Crossings are NOT a separate object type. Every bridge / culvert / ford is stored
    as type "bridge" with props["structure"] in {bridge, culvert, ford, causeway} so
    ontology.FRAGILITY keys correctly. Mis-mapping a culvert would make the engine
    return OK for a washed-out crossing -- forbidden.
  * Full way geometry is stored in props_json so Step B can do spatial inference
    without hitting Overpass again (and so the demo runs with USE_LIVE=0).
  * Idempotent: a re-run wipes the graph and reloads it identically.

This is the ONLY place Overpass is called by the app. Polite rate-limit + cache.

Usage (from /opt/lifeline):
    .venv/bin/python -m app.ingest_osm --dry-run     # inspect counts, tune the bbox
    .venv/bin/python -m app.ingest_osm               # load the locked pilot box
    .venv/bin/python -m app.ingest_osm --bbox 0.884,34.264,0.929,34.309
    .venv/bin/python -m app.ingest_osm --refresh     # bypass the Overpass cache

Attribution: (c) OpenStreetMap contributors, ODbL (shown in the UI footer).
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

from . import db

# Locked pilot corridor: Manafwa River @ Bubulo (D-014). (south, west, north, east)
PILOT_BBOX = (0.905, 34.260, 0.962, 34.305)

LEGIBLE_MIN, LEGIBLE_MAX = 150, 400  # D-013 one-legible-district target

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Buckets in PRIORITY order. If one OSM element matches two buckets (e.g. a track
# tagged bridge=yes is both a crossing and a road), the earlier bucket wins and the
# element is not added twice. Each value is the Overpass statement body; {bbox} ->
# (S,W,N,E). We request 'out geom;' so ways carry their polyline + bounds.
BUCKETS = [
    # A CROSSING is a bridge/culvert/ford that CARRIES A VEHICLE ROAD (same highway
    # classes as road_segment below -- they MUST stay in sync). This deliberately
    # excludes footbridges (highway=path) and stream/ditch/drain culverts, of which
    # rural OSM maps hundreds; they are not vehicle lifelines. Genuinely untagged
    # road-over-river crossings are recovered geometrically in Step B. Fords are nodes
    # and can't be highway-filtered, so all fords are kept and flagged for Step B.
    ("crossing", """
        way["bridge"]["bridge"!="no"]["highway"~"^(trunk|primary|secondary|tertiary|unclassified|residential|track|trunk_link|primary_link|secondary_link)$"]{bbox};
        way["tunnel"="culvert"]["highway"~"^(trunk|primary|secondary|tertiary|unclassified|residential|track|trunk_link|primary_link|secondary_link)$"]{bbox};
        way["ford"]["ford"!="no"]{bbox};
        node["ford"]["ford"!="no"]{bbox};
    """),
    ("river_reach", """
        way["waterway"~"^(river|stream)$"]{bbox};
    """),
    # Vehicle road classes -- MUST match the crossing highway filter above.
    ("road_segment", """
        way["highway"~"^(trunk|primary|secondary|tertiary|unclassified|residential|track|trunk_link|primary_link|secondary_link)$"]{bbox};
    """),
    ("settlement", """
        node["place"~"^(city|town|village|hamlet)$"]{bbox};
        way["place"~"^(city|town|village|hamlet)$"]{bbox};
    """),
    ("clinic", """
        nwr["amenity"~"^(clinic|hospital|doctors)$"]{bbox};
        nwr["healthcare"~"^(clinic|hospital|centre|health_post|doctor)$"]{bbox};
    """),
    ("school", """
        nwr["amenity"="school"]{bbox};
    """),
    ("water_point", """
        nwr["man_made"~"^(water_well|water_tap|borehole)$"]{bbox};
        nwr["amenity"="drinking_water"]{bbox};
        node["natural"="spring"]{bbox};
    """),
]


# --------------------------------------------------------------------------- #
# Overpass fetch (with cache + endpoint fallback)
# --------------------------------------------------------------------------- #
def _bbox_str(bbox):
    s, w, n, e = bbox
    return f"({s},{w},{n},{e})"


def _cache_get(key):
    with db.conn() as c:
        r = c.execute("SELECT value_json FROM geocache WHERE key=?", (key,)).fetchone()
        return r["value_json"] if r else None


def _cache_put(key, value):
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?)", (key, value, db.now()))


def _post(url, body, timeout=180):
    req = urllib.request.Request(
        url, data=body.encode("utf-8"),
        headers={"User-Agent": "qvah-lifeline-ingest/1.0",
                 "Content-Type": "text/plain; charset=utf-8"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def fetch_bucket(bucket, bbox, refresh=False):
    """Return the parsed Overpass 'elements' list for one bucket, cached raw."""
    body = ("[out:json][timeout:180];(" +
            "".join(BUCKETS_BY_NAME[bucket].format(bbox=_bbox_str(bbox)).split()) +
            ");out geom;")
    key = f"overpass:{bucket}:{_bbox_str(bbox)}"
    if not refresh:
        cached = _cache_get(key)
        if cached is not None:
            return json.loads(cached).get("elements", [])
    last_err = None
    for ep in OVERPASS_ENDPOINTS:
        for _ in range(2):
            try:
                raw = _post(ep, body)
                json.loads(raw)  # validate (rate-limit pages are HTML -> raises)
                _cache_put(key, raw)
                return json.loads(raw).get("elements", [])
            except (urllib.error.URLError, urllib.error.HTTPError,
                    json.JSONDecodeError, ValueError, TimeoutError) as err:
                last_err = err
                time.sleep(4)
    raise RuntimeError(f"Overpass failed for bucket '{bucket}': {last_err}")


BUCKETS_BY_NAME = {name: body for name, body in BUCKETS}


# --------------------------------------------------------------------------- #
# Element -> object mapping
# --------------------------------------------------------------------------- #
def _osm_id(el):
    return f"{el['type'][0]}{el['id']}"  # n123 / w123 / r123


def _centroid(el):
    """(lat, lon, geometry_or_None). Node: its point. Way/relation: bounds midpoint;
    ways also return their polyline geometry."""
    if el["type"] == "node":
        return el.get("lat"), el.get("lon"), None
    geom = el.get("geometry")  # ways with out geom;
    coords = [[g["lat"], g["lon"]] for g in geom] if geom else None
    b = el.get("bounds")
    if b:
        return (b["minlat"] + b["maxlat"]) / 2.0, (b["minlon"] + b["maxlon"]) / 2.0, coords
    if coords:
        lat = sum(p[0] for p in coords) / len(coords)
        lon = sum(p[1] for p in coords) / len(coords)
        return lat, lon, coords
    c = el.get("center")
    if c:
        return c["lat"], c["lon"], None
    return None, None, None


def _structure(tags):
    """OSM crossing tags -> the four structures ontology.FRAGILITY understands."""
    if tags.get("tunnel") == "culvert":
        return "culvert"
    if tags.get("ford", "no") not in ("no", "",):
        return "ford"
    if tags.get("bridge") == "causeway" or tags.get("embankment") == "yes":
        return "causeway"
    return "bridge"  # anything else that reached the crossing bucket


def _population(tags):
    raw = tags.get("population")
    if raw and raw.replace(",", "").isdigit():
        return int(raw.replace(",", ""))
    return None


def build_objects(bbox, refresh=False):
    """Fetch every bucket and return (objects, report). No DB writes here."""
    objects = []          # list of dicts ready for db.add_object
    seen = set()          # osm keys already claimed by a higher-priority bucket
    report = {name: {"added": 0, "unnamed": 0} for name, _ in BUCKETS}
    report["_skipped_no_coords"] = 0
    crossings = []

    for bucket, _ in BUCKETS:
        els = fetch_bucket(bucket, bbox, refresh=refresh)
        for el in els:
            key = _osm_id(el)
            if key in seen:
                continue
            lat, lon, geom = _centroid(el)
            if lat is None or lon is None:
                report["_skipped_no_coords"] += 1
                continue
            seen.add(key)
            tags = el.get("tags", {}) or {}
            name = tags.get("name")
            props = {"osm_type": el["type"], "osm_id": el["id"], "tags": tags}
            if geom:
                props["geometry"] = geom

            otype = "bridge" if bucket == "crossing" else bucket
            if bucket == "crossing":
                props["structure"] = _structure(tags)
                crossings.append({
                    "id": key, "structure": props["structure"],
                    "name": name, "lat": round(lat, 5), "lon": round(lon, 5),
                    "on": tags.get("highway") or tags.get("waterway") or "?"})
            if bucket == "settlement":
                pop = _population(tags)
                if pop is not None:
                    props["population"] = pop

            objects.append({"id": key, "type": otype, "name": name,
                            "lat": lat, "lon": lon, "props": props})
            report[bucket]["added"] += 1
            if not name:
                report[bucket]["unnamed"] += 1
        time.sleep(2)  # polite between buckets

    return objects, report, crossings


# --------------------------------------------------------------------------- #
# Write + report
# --------------------------------------------------------------------------- #
def write_objects(objects):
    """Idempotent full reload of the pilot graph (mirrors seed wipe; keeps geocache)."""
    with db.conn() as c:
        c.executescript("DELETE FROM objects; DELETE FROM links; DELETE FROM hazards;"
                        "DELETE FROM impacts; DELETE FROM actions;")
        for o in objects:
            db.add_object(c, o["id"], o["type"], o["name"], o["lat"], o["lon"],
                          o["props"], source="osm")


def print_report(bbox, objects, report, crossings, wrote):
    total = len(objects)
    print("\n" + "=" * 64)
    print(f"LIFELINE ingest — Manafwa @ Bubulo   bbox {_bbox_str(bbox)}")
    print("=" * 64)
    print(f"{'category':<16}{'added':>7}{'unnamed':>9}")
    print("-" * 32)
    for name, _ in BUCKETS:
        r = report[name]
        print(f"{name:<16}{r['added']:>7}{r['unnamed']:>9}")
    print("-" * 32)
    print(f"{'TOTAL objects':<16}{total:>7}")
    if report["_skipped_no_coords"]:
        print(f"(skipped {report['_skipped_no_coords']} features with no usable coords)")

    if total < LEGIBLE_MIN:
        print(f"\n[!] {total} objects < {LEGIBLE_MIN}: bbox may be too tight or OSM thin. "
              "Consider widening slightly.")
    elif total > LEGIBLE_MAX:
        print(f"\n[!] {total} objects > {LEGIBLE_MAX}: box too big for one legible "
              "district (D-013). Shrink the bbox toward the river and re-run --dry-run.")
    else:
        print(f"\n[ok] {total} objects — within the {LEGIBLE_MIN}-{LEGIBLE_MAX} "
              "legibility window.")

    print("\nCROSSINGS — pick the single point of failure from this list:")
    if not crossings:
        print("  (none found — widen the box toward the river, or the reach is unmapped)")
    else:
        order = {"culvert": 0, "ford": 1, "causeway": 2, "bridge": 3}
        for i, x in enumerate(sorted(crossings, key=lambda z: order.get(z["structure"], 9)), 1):
            nm = x["name"] or f"(unnamed {x['structure']})"
            print(f"  {i:>2}. {x['id']:<9} {x['structure']:<9} {nm:<34} "
                  f"@ {x['lat']},{x['lon']}  on={x['on']}")

    if wrote:
        print("\nWROTE to data/lifeline.db (source='osm'). NO links yet — this is Step A.")
        print("The app will show every asset OK until Step B infers links. The demo")
        print("hazard button targets seed id 'R1', which no longer exists; wiring the")
        print("real reach + links is Step B (Opus, with test cases).")
    else:
        print("\nDRY RUN — nothing written. Re-run without --dry-run to load the graph.")
    print()


def parse_bbox(s):
    parts = [float(x) for x in s.split(",")]
    if len(parts) != 4:
        raise ValueError
    return tuple(parts)


def main(argv=None):
    ap = argparse.ArgumentParser(description="LIFELINE Phase 1 Step A — OSM ingest")
    ap.add_argument("--bbox", type=parse_bbox, default=PILOT_BBOX,
                    help="S,W,N,E (default: locked Manafwa @ Bubulo box)")
    ap.add_argument("--dry-run", action="store_true",
                    help="fetch + report only; write nothing")
    ap.add_argument("--refresh", action="store_true",
                    help="bypass the Overpass cache and refetch")
    args = ap.parse_args(argv)

    db.init()
    objects, report, crossings = build_objects(args.bbox, refresh=args.refresh)
    if not args.dry_run:
        write_objects(objects)
    print_report(args.bbox, objects, report, crossings, wrote=not args.dry_run)


if __name__ == "__main__":
    main()
