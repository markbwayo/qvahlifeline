"""app/links.py - Step B: crossing reconciliation + link inference.

Sub-step 1 (this slice): inject operator-verified crossings from
`data/operator_crossings.csv` into the object graph, deduping against OSM
crossings within a distance threshold. On a spatial match the operator's
engineering classification wins (structure / crossing_class), but the OSM
object's id, name and coordinates are preserved so existing references and the
demo map stay stable. See 09 (v0.2) and D-013.

Deterministic and auditable end to end. No language model touches this.
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


def _apply_in_place(c, obj, new_props):
    """Overwrite an existing object with operator classification, preserving its
    id, name, coordinates and created_utc. Props merge; operator values win."""
    props = dict(obj["props"])
    props.update(new_props)
    props["operator_injected_utc"] = db.now()
    c.execute("UPDATE objects SET type='bridge', name=?, props_json=?, "
              "source='operator' WHERE id=?",
              (obj["name"], json.dumps(props), obj["id"]))


def inject_operator_crossings(csv_path=DEFAULT_CSV, threshold_m=MATCH_THRESHOLD_M):
    """Inject operator crossings. Idempotent and atomic.

    Returns a list of tuples: (op_id, resolution, object_id[, dist_m]) where
    resolution is one of 'reinjected' | 'deduped_onto_osm' | 'inserted_new'.
    A bad row raises ValueError and the whole injection rolls back (no partial writes).
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

                # (1) already injected on a prior run -> update in place (idempotent)
                prior = _find_by_operator_id(c, op_id)
                if prior is not None:
                    _apply_in_place(c, prior, op_props)
                    results.append((op_id, "reinjected", prior["id"]))
                    continue

                # (2) same physical structure as an OSM crossing within threshold?
                best, best_d = None, None
                for o in osm_crossings:
                    d = _haversine_m(lat, lon, o["lat"], o["lon"])
                    if best_d is None or d < best_d:
                        best, best_d = o, d
                if best is not None and best_d <= threshold_m:
                    merged = dict(op_props)
                    merged["osm_id"] = best["id"]
                    merged["osm_structure"] = best["props"].get("structure")
                    merged["dedup_dist_m"] = round(best_d, 1)
                    if "single_point_of_failure" in best["props"]:
                        merged["single_point_of_failure"] = \
                            best["props"]["single_point_of_failure"]
                    _apply_in_place(c, best, merged)
                    osm_crossings.remove(best)   # an OSM crossing can't be claimed twice
                    results.append((op_id, "deduped_onto_osm", best["id"],
                                    round(best_d, 1)))
                    continue

                # (3) genuinely new operator crossing
                new_id = f"op:{op_id}"
                props = dict(op_props)
                props["operator_injected_utc"] = db.now()
                db.add_object(c, new_id, "bridge", name, lat, lon, props,
                              source="operator")
                results.append((op_id, "inserted_new", new_id))
    return results


if __name__ == "__main__":
    db.init()
    for r in inject_operator_crossings():
        print(" ", r)
