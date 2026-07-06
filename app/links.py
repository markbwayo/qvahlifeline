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


if __name__ == "__main__":
    db.init()
    for r in inject_operator_crossings():
        print(" ", r)
