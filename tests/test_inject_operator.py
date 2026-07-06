"""tests/test_inject_operator.py - merge gate for links.inject_operator_crossings.

Hermetic: each test runs against a fresh temp SQLite DB (db.DB_PATH monkeypatched)
seeded with a minimal OSM crossing fixture and a temp operator CSV. No network,
no dependence on the 362-object pilot load.
"""
import pytest

from app import db, links


# Old Manafwa bridge - the demo spine (OSM w902422828).
SPINE_ID = "w902422828"
SPINE_LAT, SPINE_LON = 0.94065, 34.28044

# operator_crossings.csv ground truth (real coordinates).
TC_LAT, TC_LON = 0.9406239, 34.2802124              # ~25 m from spine -> dedup
CULVERT_LAT, CULVERT_LON = 0.9564980, 34.2896510    # ~1.7 km away  -> new object

CSV_HEADER = "id,structure,name,lat,lon,road_class,source,note\n"
CSV_ROWS = (
    f"op_manafwa_tc_bridge,bridge,Manafwa Town Council bridge,"
    f"{TC_LAT},{TC_LON},main_road,operator,tc\n"
    f"op_north_footpath_culvert,culvert,North footpath culvert,"
    f"{CULVERT_LAT},{CULVERT_LON},footpath,operator,north\n"
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    with db.conn() as c:   # seed two OSM crossings: the spine + a far ford
        db.add_object(c, SPINE_ID, "bridge", "Old Manafwa bridge",
                      SPINE_LAT, SPINE_LON, {"structure": "bridge"}, source="osm")
        db.add_object(c, "w_far_ford", "bridge", "Far ford",
                      0.9200, 34.2500, {"structure": "ford"}, source="osm")
    return tmp_path


def _write_csv(tmp_path, body):
    p = tmp_path / "operator_crossings.csv"
    p.write_text(CSV_HEADER + body, encoding="utf-8")
    return str(p)


def _all():
    with db.conn() as c:
        return db.objects(c)


def _by_id(oid):
    return next((o for o in _all() if o["id"] == oid), None)


def _count():
    return len(_all())


def test_dedup_onto_spine_and_insert_culvert(fresh_db):
    csv_path = _write_csv(fresh_db, CSV_ROWS)
    before = _count()                       # 2 OSM crossings
    results = links.inject_operator_crossings(csv_path)

    # spine updated in place: still exactly one object at that id, now operator.
    spine = _by_id(SPINE_ID)
    assert spine is not None
    assert spine["source"] == "operator"
    assert spine["props"]["structure"] == "bridge"
    assert spine["props"]["crossing_class"] == "main_road"
    assert spine["props"]["osm_id"] == SPINE_ID
    assert spine["props"]["dedup_dist_m"] <= links.MATCH_THRESHOLD_M
    assert spine["name"] == "Old Manafwa bridge"                    # OSM name kept
    assert spine["lat"] == SPINE_LAT and spine["lon"] == SPINE_LON  # OSM coords kept

    # exactly one object near the TC coordinates (no duplicate created).
    near = [o for o in _all()
            if links._haversine_m(TC_LAT, TC_LON, o["lat"], o["lon"]) <= 50]
    assert len(near) == 1 and near[0]["id"] == SPINE_ID

    # culvert inserted as a new operator object.
    culvert = _by_id("op:op_north_footpath_culvert")
    assert culvert is not None
    assert culvert["source"] == "operator"
    assert culvert["props"]["structure"] == "culvert"
    assert culvert["props"]["crossing_class"] == "footpath"

    # net object count: 2 OSM + 1 new culvert (spine reused, not duplicated).
    assert _count() == before + 1
    assert {r[1] for r in results} == {"deduped_onto_osm", "inserted_new"}


def test_idempotent(fresh_db):
    csv_path = _write_csv(fresh_db, CSV_ROWS)
    links.inject_operator_crossings(csv_path)
    after_first = _count()
    results = links.inject_operator_crossings(csv_path)   # run again
    assert _count() == after_first                        # no duplicates
    assert {r[1] for r in results} == {"reinjected"}
    assert _by_id(SPINE_ID)["source"] == "operator"


def test_within_threshold_dedups(fresh_db):
    # ~44.5 m east of the far ford -> dedup, no new object.
    csv_path = _write_csv(fresh_db,
                          "op_near,ford,Near,0.9200,34.2504,minor_road,operator,\n")
    before = _count()
    res = links.inject_operator_crossings(csv_path)
    assert res[0][1] == "deduped_onto_osm" and res[0][2] == "w_far_ford"
    assert _count() == before
    assert _by_id("w_far_ford")["source"] == "operator"
    assert _by_id("w_far_ford")["props"]["structure"] == "ford"


def test_beyond_threshold_inserts(fresh_db):
    # ~66.8 m east of the far ford -> new object.
    csv_path = _write_csv(fresh_db,
                          "op_far,ford,Far new,0.9200,34.2506,minor_road,operator,\n")
    before = _count()
    res = links.inject_operator_crossings(csv_path)
    assert res[0][1] == "inserted_new"
    assert _count() == before + 1


def test_haversine_known_value():
    d = links._haversine_m(0.0, 0.0, 0.0, 0.001)   # 0.001 deg lon at equator
    assert abs(d - 111.32) < 1.0


def test_bad_row_rolls_back_earlier_writes(fresh_db):
    # first row valid (would dedup onto spine), second row invalid -> whole aborts.
    body = (
        f"op_manafwa_tc_bridge,bridge,TC,{TC_LAT},{TC_LON},main_road,operator,\n"
        f"op_bad,culver,Typo,0.95,34.28,footpath,operator,\n"     # 'culver' typo
    )
    csv_path = _write_csv(fresh_db, body)
    with pytest.raises(ValueError):
        links.inject_operator_crossings(csv_path)
    # the valid row's in-place update to the spine must have been rolled back.
    assert _by_id(SPINE_ID)["source"] == "osm"
    assert _by_id("op:op_manafwa_tc_bridge") is None


def test_real_csv_schema_if_present():
    import os
    real = os.path.join(os.path.dirname(links.__file__), "..", "data",
                        "operator_crossings.csv")
    if not os.path.exists(real):
        pytest.skip("data/operator_crossings.csv not present in this checkout")
    import csv as _csv
    with open(real, newline="", encoding="utf-8-sig") as f:
        reader = _csv.DictReader(f)
        links._require_columns(reader.fieldnames, real)
        n = 0
        for row in reader:
            links._read_row(row, real)   # raises if any structure/class/coord is bad
            n += 1
        assert n >= 1
