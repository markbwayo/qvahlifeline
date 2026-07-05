#!/usr/bin/env python3
"""
Qvah LIFELINE — Day-1 pilot data check (D-004)

Decides the pilot area by EVIDENCE, not preference. For each candidate corridor it:
  1. Counts OSM assets (Overpass API) in the categories the ontology (09) needs:
     crossings (bridge/culvert/ford), vehicle roads, clinics/health, schools,
     water points, settlements.
  2. Probes the GloFAS river-discharge signal (Open-Meteo flood API) at a few
     representative river points, to confirm the flood trigger will have a real
     river reach to fire on.

It PRINTS a comparison and an advisory readout. It does NOT lock the pilot — you
read the numbers, decide (founder story is a legitimate tiebreak), and append the
result to 05_decisions_log.md. Nothing here writes to the database or the graph.

Stdlib only (urllib) so it runs before any pip install. Read-only against public
free APIs. Run it on the VPS where connectivity is stable:

    cd /opt/lifeline && python3 scripts/day1_datacheck.py
"""

import json
import math
import sys
import time
import urllib.error
import urllib.request

# --------------------------------------------------------------------------- #
# Candidate corridors (D-004). bbox = (south, west, north, east) in degrees.
# Boxes are kept to a similar, tight, district-sized footprint so the counts are
# comparable; area is printed so density can be judged honestly.
# --------------------------------------------------------------------------- #
CANDIDATES = {
    "B: Mt Elgon (Mbale-Manafwa-Bududa, UG)": {
        "bbox": (0.85, 34.12, 1.15, 34.42),
        "river_points": [
            ("Manafwa R. @ Bubulo",   0.92, 34.30),
            ("Manafwa R. downstream",  0.88, 34.33),
            ("Namatala R. @ Mbale",    1.06, 34.20),
            ("Sironko/Nabuyonga low",  1.10, 34.28),
        ],
    },
    "A: Isiolo / Ewaso Ng'iro (KE)": {
        "bbox": (0.20, 37.45, 0.70, 37.85),
        "river_points": [
            ("Ewaso Ng'iro @ Isiolo",  0.35, 37.60),
            ("Ewaso Ng'iro @ Archers", 0.63, 37.66),
            ("Seasonal lagga",         0.50, 37.75),
        ],
    },
}

# Overpass selectors per ontology category. {bbox} is replaced by (S,W,N,E).
OVERPASS_CATEGORIES = {
    "crossings (bridge/culvert/ford)": """
        way["bridge"]["bridge"!="no"]{bbox};
        way["tunnel"="culvert"]{bbox};
        nwr["ford"]["ford"!="no"]{bbox};
    """,
    "roads (vehicle)": """
        way["highway"~"^(trunk|primary|secondary|tertiary|unclassified|residential|track|trunk_link|primary_link|secondary_link)$"]{bbox};
    """,
    "clinics / health": """
        nwr["amenity"~"^(clinic|hospital|doctors)$"]{bbox};
        nwr["healthcare"~"^(clinic|hospital|centre|health_post|doctor)$"]{bbox};
    """,
    "schools": """
        nwr["amenity"="school"]{bbox};
    """,
    "water points": """
        nwr["man_made"~"^(water_well|water_tap|borehole)$"]{bbox};
        nwr["amenity"="drinking_water"]{bbox};
        nwr["natural"="spring"]{bbox};
    """,
    "settlements": """
        nwr["place"~"^(city|town|village|hamlet)$"]{bbox};
    """,
}

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
FLOOD_API = "https://flood-api.open-meteo.com/v1/flood"

# Advisory floors — what the ontology needs to make the demo land. Not hard gates.
FLOORS = {
    "crossings (bridge/culvert/ford)": 15,   # THE critical asset for isolation stories
    "clinics / health": 3,
    "schools": 5,
    "settlements": 20,
    "roads (vehicle)": 200,
}
DISCHARGE_FLOOR = 5.0  # m3/s — below this a grid cell isn't a useful river reach


def http_get(url, timeout=90):
    req = urllib.request.Request(url, headers={"User-Agent": "qvah-lifeline-datacheck/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def http_post(url, body, timeout=180):
    req = urllib.request.Request(
        url,
        data=body.encode("utf-8"),
        headers={"User-Agent": "qvah-lifeline-datacheck/1.0",
                 "Content-Type": "text/plain; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8")


def bbox_str(bbox):
    s, w, n, e = bbox
    return f"({s},{w},{n},{e})"


def area_km2(bbox):
    s, w, n, e = bbox
    mid = math.radians((s + n) / 2.0)
    dlat_km = (n - s) * 110.574
    dlon_km = (e - w) * 111.320 * math.cos(mid)
    return abs(dlat_km * dlon_km)


def overpass_count(bbox, category_body):
    body = "[out:json][timeout:120];(" + category_body.format(bbox=bbox_str(bbox)) + ");out count;"
    last_err = None
    for ep in OVERPASS_ENDPOINTS:
        for attempt in range(2):
            try:
                raw = http_post(ep, body)
                data = json.loads(raw)  # HTML/rate-limit pages fail here -> retry
                els = data.get("elements", [])
                if els and "tags" in els[0] and "total" in els[0]["tags"]:
                    return int(els[0]["tags"]["total"])
                return 0
            except (urllib.error.URLError, urllib.error.HTTPError,
                    json.JSONDecodeError, ValueError, TimeoutError) as err:
                last_err = err
                time.sleep(4)
    print(f"      ! overpass failed for this category ({last_err})", file=sys.stderr)
    return None


def glofas_probe(lat, lon):
    url = (f"{FLOOD_API}?latitude={lat}&longitude={lon}"
           f"&daily=river_discharge&forecast_days=7&past_days=7")
    try:
        data = json.loads(http_get(url, timeout=60))
    except (urllib.error.URLError, urllib.error.HTTPError,
            json.JSONDecodeError, ValueError, TimeoutError) as err:
        return {"ok": False, "err": str(err)}
    series = (data.get("daily") or {}).get("river_discharge") or []
    vals = [v for v in series if isinstance(v, (int, float))]
    if not vals:
        return {"ok": True, "n": 0, "min": None, "mean": None, "max": None}
    return {"ok": True, "n": len(vals),
            "min": min(vals), "mean": sum(vals) / len(vals), "max": max(vals)}


def run_candidate(name, cfg):
    print(f"\n=== {name} ===")
    print(f"    bbox {bbox_str(cfg['bbox'])}  ~{area_km2(cfg['bbox']):.0f} km2")

    counts = {}
    print("    OSM assets (Overpass):")
    for cat, body in OVERPASS_CATEGORIES.items():
        n = overpass_count(cfg["bbox"], body)
        counts[cat] = n
        floor = FLOORS.get(cat)
        flag = ""
        if n is None:
            flag = "  [query failed]"
        elif floor is not None:
            flag = "  OK" if n >= floor else f"  THIN (want >= {floor})"
        shown = "ERR" if n is None else f"{n:>5}"
        print(f"      {cat:<34} {shown}{flag}")
        time.sleep(2)  # be polite to Overpass

    area = area_km2(cfg["bbox"])
    total = sum(v for v in counts.values() if isinstance(v, int))
    print(f"      {'TOTAL assets':<34} {total:>5}   ({total / area * 100:.1f} per 100 km2)")

    print("    GloFAS river signal (Open-Meteo flood API):")
    best_max = 0.0
    signal_points = 0
    for label, lat, lon in cfg["river_points"]:
        p = glofas_probe(lat, lon)
        if not p["ok"]:
            print(f"      {label:<26} ERR  ({p['err']})")
        elif p["n"] == 0 or p["max"] is None:
            print(f"      {label:<26} no discharge series")
        else:
            best_max = max(best_max, p["max"])
            if p["max"] >= DISCHARGE_FLOOR:
                signal_points += 1
            print(f"      {label:<26} mean {p['mean']:8.1f}  max {p['max']:8.1f} m3/s")
        time.sleep(1)

    print("    READOUT:")
    crossings = counts.get("crossings (bridge/culvert/ford)")
    if isinstance(crossings, int):
        verdict = "OK" if crossings >= FLOORS['crossings (bridge/culvert/ford)'] else "THIN"
        print(f"      crossings for isolation stories : {crossings}  [{verdict}]")
    print(f"      river points with usable signal : {signal_points} "
          f"(peak {best_max:.0f} m3/s)  [{'OK' if signal_points else 'WEAK'}]")

    return {"counts": counts, "total": total, "area": area,
            "signal_points": signal_points, "best_max": best_max}


def main():
    print("Qvah LIFELINE — Day-1 pilot data check (D-004)")
    print("Advisory only. You lock the pilot and log it in 05.")
    results = {name: run_candidate(name, cfg) for name, cfg in CANDIDATES.items()}

    print("\n\n=== SUMMARY (higher assets + at least one usable river = better demo) ===")
    header = f"{'candidate':<40}{'assets':>8}{'/100km2':>10}{'crossings':>11}{'river pts':>11}"
    print(header)
    print("-" * len(header))
    for name, r in results.items():
        cx = r["counts"].get("crossings (bridge/culvert/ford)")
        cx_s = "ERR" if cx is None else str(cx)
        dens = r["total"] / r["area"] * 100
        print(f"{name:<40}{r['total']:>8}{dens:>10.1f}{cx_s:>11}{r['signal_points']:>11}")

    print("\nNext: pick the corridor that scores well AND demos better, append the")
    print("result + reasoning to 05_decisions_log.md (extend D-004), then ingest.")


if __name__ == "__main__":
    main()
