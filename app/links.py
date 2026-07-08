"""app/links.py - Step B: crossing reconciliation + link inference.

Sub-step 1 (this slice): inject operator-verified crossings from
`data/operator_crossings.csv` into the object graph, reconciling them against
OSM crossings. On a match the operator's engineering classification wins
(structure / crossing_class), but the OSM object's id, name and coordinates are
preserved so existing references and the demo map stay stable. See 09 (v0.3) and
D-013 / D-022.

Reconciliation order per row (all deterministic; no language model touches this):
  1. Already injected on a prior run (matched by operator_id)  -> update in place.
  2. Explicit `match_hint` (an OSM id, or a unique name substring) -> that object.
  3. No hint: OSM crossings within the distance threshold ->
        exactly one  -> dedup onto it,
        more than one -> REFUSE and print the cluster (identity must not be guessed),
        none          -> insert a new operator object.

Later sub-steps (geometric crossing synthesis, link inference, propagation
repoint) will be appended to this module behind their own tests.
"""
import csv
import json
import math
import os

try:                       # `uvicorn app.main:app` / `python -m pytest` (package)
    from app import db
except ImportError:        # `python app/links.py` run from inside app/
    import db


DEFAULT_CSV = os.path.join(os.path.dirname(__file__), "..", "data",
                           "operator_crossings.csv")
MATCH_THRESHOLD_M = 50.0

# Fragility rules (09) key on these exactly; an unrecognised value would yield a
# silent no-impact, so injection hard-fails instead of guessing.
VALID_STRUCTURES = {"bridge", "culvert", "ford", "causeway"}
VALID_CROSSING_CLASSES = {"main_road", "minor_road", "footpath"}
REQUIRED_COLS = {"id", "structure", "name", "lat", "lon", "road_class"}
# match_hint is optional (blank allowed); not in REQUIRED_COLS.


def _haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lon2 - lon1)
    a = (math.sin(dphi / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def _require_columns(fieldnames, csv_path):
    have = {(f or "").strip() for f in (fieldnames or [])}
    missing = REQUIRED_COLS - have
    if missing:
        raise ValueError(f"{csv_path}: missing column(s) {sorted(missing)}; "
                         f"found {sorted(have)}")


def _read_row(row, csv_path):
    """Validate one CSV row; return (op_id, name, lat, lon, op_props)."""
    op_id = (row.get("id") or "").strip()
    if not op_id:
        raise ValueError(f"{csv_path}: a row is missing 'id'")
    structure = (row.get("structure") or "").strip().lower()
    crossing_class = (row.get("road_class") or "").strip().lower()
    if structure not in VALID_STRUCTURES:
        raise ValueError(
            f"{csv_path} id={op_id!r}: structure {structure!r} not in "
            f"{sorted(VALID_STRUCTURES)} - fragility rules key on these exactly; "
            f"fix the CSV before injecting.")
    if crossing_class not in VALID_CROSSING_CLASSES:
        raise ValueError(
            f"{csv_path} id={op_id!r}: road_class {crossing_class!r} not in "
            f"{sorted(VALID_CROSSING_CLASSES)}.")
    try:
        lat, lon = float(row["lat"]), float(row["lon"])
    except (KeyError, TypeError, ValueError):
        raise ValueError(f"{csv_path} id={op_id!r}: lat/lon not parseable.")
    name = (row.get("name") or op_id).strip()
    op_props = {
        "structure": structure,
        "crossing_class": crossing_class,     # <- mapped from CSV column road_class
        "operator_id": op_id,
        "operator_verified": True,
        "operator_name": name,
        "operator_latlon": [lat, lon],
        "operator_note": (row.get("note") or "").strip(),
    }
    return op_id, name, lat, lon, op_props


def _find_by_operator_id(c, op_id):
    for o in db.objects(c):
        if o["props"].get("operator_id") == op_id:
            return o
    return None


def _resolve_hint(hint, osm_crossings):
    """Resolve a match_hint to exactly one OSM crossing, or raise if ambiguous.
    Returns the object, or None if the hint matches nothing."""
    hint = hint.strip()
    for o in osm_crossings:                      # exact id match first
        if o["id"] == hint or str(o["props"].get("osm_id")) == hint:
            return o
    by_name = [o for o in osm_crossings
               if hint.lower() in (o.get("name") or "").lower()]
    if len(by_name) == 1:
        return by_name[0]
    if len(by_name) > 1:
        raise ValueError(f"match_hint {hint!r} matches {len(by_name)} OSM "
                         f"crossings by name; use an exact OSM id.")
    return None


def _apply_in_place(c, obj, new_props):
    """Overwrite an existing object with operator classification, preserving its
    id, name, coordinates and created_utc. Props merge; operator values win."""
    props = dict(obj["props"])
    props.update(new_props)
    props["operator_injected_utc"] = db.now()
    c.execute("UPDATE objects SET type='bridge', name=?, props_json=?, "
              "source='operator' WHERE id=?",
              (obj["name"], json.dumps(props), obj["id"]))


def _dedup_onto(c, target, op_props, op_lat, op_lon):
    """Fold operator props onto an existing OSM crossing (operator wins)."""
    d = _haversine_m(op_lat, op_lon, target["lat"], target["lon"])
    merged = dict(op_props)
    merged["osm_id"] = target["id"]
    merged["osm_structure"] = target["props"].get("structure")
    merged["dedup_dist_m"] = round(d, 1)
    if "single_point_of_failure" in target["props"]:
        merged["single_point_of_failure"] = target["props"]["single_point_of_failure"]
    _apply_in_place(c, target, merged)
    return round(d, 1)


def inject_operator_crossings(csv_path=DEFAULT_CSV, threshold_m=MATCH_THRESHOLD_M):
    """Inject operator crossings. Idempotent and atomic.

    Returns a list of tuples: (op_id, resolution, object_id[, dist_m]) where
    resolution is 'reinjected' | 'deduped_onto_osm' | 'inserted_new'.
    Raises ValueError (rolling the whole injection back) on a bad row, an
    unresolvable hint, or an ambiguous cluster with no hint.
    """
    results = []
    with db.conn() as c:
        osm_crossings = [o for o in db.objects(c)
                         if o["type"] == "bridge" and o["source"] == "osm"]
        with open(csv_path, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            _require_columns(reader.fieldnames, csv_path)
            for row in reader:
                op_id, name, lat, lon, op_props = _read_row(row, csv_path)
                hint = (row.get("match_hint") or "").strip()

                # (1) already injected on a prior run -> update in place (idempotent)
                prior = _find_by_operator_id(c, op_id)
                if prior is not None:
                    _apply_in_place(c, prior, op_props)
                    results.append((op_id, "reinjected", prior["id"]))
                    continue

                # (2) explicit hint -> that exact OSM crossing
                if hint:
                    target = _resolve_hint(hint, osm_crossings)
                    if target is None:
                        raise ValueError(
                            f"operator crossing {op_id!r}: match_hint {hint!r} "
                            f"resolves to no OSM crossing in the graph.")
                    d = _dedup_onto(c, target, op_props, lat, lon)
                    osm_crossings.remove(target)
                    results.append((op_id, "deduped_onto_osm", target["id"], d))
                    continue

                # (3) no hint: OSM crossings within the threshold
                within = [(_haversine_m(lat, lon, o["lat"], o["lon"]), o)
                          for o in osm_crossings]
                within = [(d, o) for d, o in within if d <= threshold_m]
                within.sort(key=lambda t: t[0])          # sort on distance only
                if len(within) > 1:
                    lines = "\n".join(
                        f"    {d:6.1f} m  {o['id']:<14} {o.get('name') or '(unnamed)'}"
                        for d, o in within)
                    raise ValueError(
                        f"operator crossing {op_id!r} at ({lat},{lon}) matches "
                        f"{len(within)} OSM crossings within {threshold_m:.0f} m:\n"
                        f"{lines}\n  Add a match_hint (OSM id) to "
                        f"data/operator_crossings.csv to say which one it is.")
                if len(within) == 1:
                    d, target = within[0]
                    _dedup_onto(c, target, op_props, lat, lon)
                    osm_crossings.remove(target)
                    results.append((op_id, "deduped_onto_osm", target["id"], d))
                    continue

                # (4) genuinely new operator crossing
                new_id = f"op:{op_id}"
                props = dict(op_props)
                props["operator_injected_utc"] = db.now()
                db.add_object(c, new_id, "bridge", name, lat, lon, props,
                              source="operator")
                results.append((op_id, "inserted_new", new_id))
    return results


# ---------------------------------------------------------------------------
# Sub-step 2: synthesise crossings from road x river geometry.
#
# Where a VEHICLE road_segment polyline crosses a river_reach polyline and no
# crossing object already exists within ~50 m, create a review candidate.
# We do NOT guess structure (structure drives fragility, and a wrong guess is a
# wrong impact). A synthesised crossing carries source='synth', needs_review=True,
# and NO structure, so it produces no fragility state and cannot yield an impact
# until a human classifies it. See 09 (v0.4) and D-023.
# ---------------------------------------------------------------------------

SYNTH_SOURCE = "synth"
SYNTH_CLUSTER_M = 50.0            # merge synth points within this; also dedup vs existing

# Vehicle highway classes only. Footway/path/pedestrian/steps/cycleway/bridleway
# are NOT vehicle roads and are excluded (a footbridge is not a clinic lifeline).
# Adjust this set to your district (e.g. drop 'track') and re-run.
VEHICLE_HIGHWAYS = {
    "motorway", "trunk", "primary", "secondary", "tertiary",
    "unclassified", "residential", "living_street", "service", "track", "road",
    "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link",
}


def _road_highway(o):
    p = o["props"]
    return (p.get("class") or (p.get("tags") or {}).get("highway") or "").strip().lower()


def _is_vehicle_road(o):
    return _road_highway(o) in VEHICLE_HIGHWAYS


def _geom(o):
    g = o["props"].get("geometry")
    if g:
        return [(pt[0], pt[1]) for pt in g]
    return [(o["lat"], o["lon"])]


def _bbox(poly):
    lats = [p[0] for p in poly]
    lons = [p[1] for p in poly]
    return (min(lats), min(lons), max(lats), max(lons))


def _bbox_overlap(b1, b2):
    return not (b1[2] < b2[0] or b2[2] < b1[0] or b1[3] < b2[1] or b2[3] < b1[1])


def _seg_intersect(p1, p2, p3, p4):
    """Intersection point (lat,lon) of segments p1p2 and p3p4, or None.
    Planar in lat/lon (fine at district scale). Uses lon as x, lat as y."""
    x1, y1 = p1[1], p1[0]
    x2, y2 = p2[1], p2[0]
    x3, y3 = p3[1], p3[0]
    x4, y4 = p4[1], p4[0]
    d = (x2 - x1) * (y4 - y3) - (y2 - y1) * (x4 - x3)
    if d == 0:
        return None                       # parallel/collinear -> ignore
    t = ((x3 - x1) * (y4 - y3) - (y3 - y1) * (x4 - x3)) / d
    u = ((x3 - x1) * (y2 - y1) - (y3 - y1) * (x2 - x1)) / d
    if 0.0 <= t <= 1.0 and 0.0 <= u <= 1.0:
        return (y1 + t * (y2 - y1), x1 + t * (x2 - x1))   # (lat, lon)
    return None


def synthesise_crossings(threshold_m=SYNTH_CLUSTER_M):
    """Create review-candidate crossings at vehicle-road x river intersections
    that aren't already represented. Idempotent. Returns list of
    (road_obj, reach_obj, (lat, lon)) for the crossings created this run."""
    created = []
    with db.conn() as c:
        objs = db.objects(c)
        roads = [o for o in objs if o["type"] == "road_segment" and _is_vehicle_road(o)]
        reaches = [o for o in objs if o["type"] == "river_reach"]
        existing_pts = [(o["lat"], o["lon"]) for o in objs if o["type"] == "bridge"]
        new_pts = []                       # crossings synthesised this run

        for road in roads:
            rg = _geom(road)
            if len(rg) < 2:
                continue
            rb = _bbox(rg)
            for reach in reaches:
                vg = _geom(reach)
                if len(vg) < 2:
                    continue
                if not _bbox_overlap(rb, _bbox(vg)):
                    continue
                for i in range(len(rg) - 1):
                    for j in range(len(vg) - 1):
                        pt = _seg_intersect(rg[i], rg[i + 1], vg[j], vg[j + 1])
                        if pt is None:
                            continue
                        if any(_haversine_m(pt[0], pt[1], a, b) <= threshold_m
                               for a, b in existing_pts):
                            continue       # already a crossing here
                        if any(_haversine_m(pt[0], pt[1], a, b) <= threshold_m
                               for a, b in new_pts):
                            continue       # already synthesised this run
                        new_pts.append(pt)
                        created.append((road, reach, pt))

        for road, reach, pt in created:
            oid = f"synth:{pt[0]:.5f}_{pt[1]:.5f}"     # coordinate-stable, idempotent
            props = {
                "needs_review": True,
                "synth": True,
                "structure": None,                     # NOT guessed - no fragility yet
                "synth_road_id": road["id"],
                "synth_reach_id": reach["id"],
                "synth_road_class": _road_highway(road),
                "inferred_by": "road_x_river",
                "synth_created_utc": db.now(),
            }
            db.add_object(c, oid, "bridge", None, pt[0], pt[1], props,
                          source=SYNTH_SOURCE)
    return created


# ---------------------------------------------------------------------------
# Sub-step 3a: infer crossing-anchored links from geometry.
#
#   crosses  (bridge -> river_reach): the crossing links to the NEAREST reach
#            within ~50 m - the channel it physically spans.
#   carries  (road_segment -> bridge): every VEHICLE road whose line passes
#            within ~15 m of the crossing carries it. 15 m is tuned so the two
#            town bridges (19.8 m apart) don't cross-link to each other's road,
#            while both segments of a road that splits at a bridge (~0 m) are kept.
#
# Footpath crossings get crosses but NOT carries (09 crossing_class gate).
# Synth crossings get both, unclassified - so an unclassified crossing can sever
# a route (the conservative rule wired later decides whether it does).
# Deterministic; idempotent (rebuilds only its own geom_* links). See 09 / D-024.
# ---------------------------------------------------------------------------

CROSSES_THRESHOLD_M = 50.0
CARRIES_THRESHOLD_M = 15.0        # < 19.8 m town-bridge separation, on purpose


def _pt_seg_dist_m(p, a, b):
    """Distance in metres from point p to segment a-b (local planar around p)."""
    k = math.cos(math.radians(p[0])) * 111320.0        # metres per deg lon at p
    ax, ay = (a[1] - p[1]) * k, (a[0] - p[0]) * 111320.0
    bx, by = (b[1] - p[1]) * k, (b[0] - p[0]) * 111320.0
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(ax, ay)
    t = -(ax * dx + ay * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    return math.hypot(ax + t * dx, ay + t * dy)


def _pt_poly_dist_m(pt, poly):
    if len(poly) == 1:
        return _haversine_m(pt[0], pt[1], poly[0][0], poly[0][1])
    return min(_pt_seg_dist_m(pt, poly[i], poly[i + 1])
               for i in range(len(poly) - 1))


def infer_crossing_links(crosses_threshold_m=CROSSES_THRESHOLD_M,
                         carries_threshold_m=CARRIES_THRESHOLD_M):
    """Infer crosses + carries. Idempotent. Returns a report dict."""
    report = {"crosses": 0, "carries": 0, "footpath_skipped": 0, "no_carrier": []}
    with db.conn() as c:
        objs = db.objects(c)
        byid = {o["id"]: o for o in objs}
        crossings = [o for o in objs if o["type"] == "bridge"]
        reaches = [o for o in objs if o["type"] == "river_reach"]
        roads = [o for o in objs if o["type"] == "road_segment"]

        # rebuild only our own inferred links (preserve manual/other overrides)
        c.execute("DELETE FROM links WHERE type='crosses' AND inferred_by='geom_crosses'")
        c.execute("DELETE FROM links WHERE type='carries' AND inferred_by='geom_carries'")

        for x in crossings:
            xpt = (x["lat"], x["lon"])

            # crosses: nearest reach within threshold
            best_r, best_d = None, None
            for r in reaches:
                d = _pt_poly_dist_m(xpt, _geom(r))
                if best_d is None or d < best_d:
                    best_r, best_d = r, d
            if best_r is not None and best_d <= crosses_threshold_m:
                db.add_link(c, x["id"], best_r["id"], "crosses", "geom_crosses")
                report["crosses"] += 1

            # carries: footpath crossings never carry a vehicle road (09 gate)
            if x["props"].get("crossing_class") == "footpath":
                report["footpath_skipped"] += 1
                continue

            carriers = set()
            srid = x["props"].get("synth_road_id")       # synth: its own road
            if srid and srid in byid:
                carriers.add(srid)
            for rd in roads:
                if not _is_vehicle_road(rd):
                    continue
                if _pt_poly_dist_m(xpt, _geom(rd)) <= carries_threshold_m:
                    carriers.add(rd["id"])
            for rid in carriers:
                db.add_link(c, rid, x["id"], "carries", "geom_carries")
                report["carries"] += 1
            if not carriers:
                report["no_carrier"].append(x["id"])
    return report


if __name__ == "__main__":
    import sys
    db.init()
    mode = sys.argv[1] if len(sys.argv) > 1 else "inject"
    if mode in ("inject", "all"):
        print("== inject operator crossings ==")
        for r in inject_operator_crossings():
            print(" ", r)
    if mode in ("synth", "all"):
        print("== synthesise road x river crossings ==")
        created = synthesise_crossings()
        for road, reach, pt in created:
            print(f"  synth @ ({pt[0]:.5f},{pt[1]:.5f})  road={road['id']} "
                  f"({_road_highway(road)})  reach={reach['id']}")
        print(f"  {len(created)} synthesised crossing(s) created (needs_review).")
    if mode in ("links", "all"):
        print("== infer crossing links (crosses / carries) ==")
        rep = infer_crossing_links()
        print(f"  crosses links: {rep['crosses']}")
        print(f"  carries links: {rep['carries']}")
        print(f"  footpath crossings skipped for carries: {rep['footpath_skipped']}")
        if rep["no_carrier"]:
            print(f"  crossings with NO carrier road ({len(rep['no_carrier'])}): "
                  f"{rep['no_carrier']}")
