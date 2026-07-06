"""tests/test_inject_operator.py - merge gate for links.inject_operator_crossings.

Hermetic: each test runs against a fresh temp SQLite DB (db.DB_PATH monkeypatched)
seeded with a minimal OSM crossing fixture and a temp operator CSV. No network,
no dependence on the 362-object pilot load.
"""
import pytest

from app import db, links


# The two real bridges over the Manafwa at the town crossing, ~20 m apart.
MAIN_ID = "w128611448"   # Manafwa Bridge, B112 secondary (main tarmac) = demo spine
OLD_ID = "w902422828"    # Old Manafwa bridge, C870 tertiary (separate, older)
MAIN_LAT, MAIN_LON = 0.94063, 34.28022
OLD_LAT, OLD_LON = 0.94076, 34.28046

# operator_crossings.csv ground truth.
TC_LAT, TC_LON = 0.9406239, 34.2802124              # on the main bridge -> dedup
CULVERT_LAT, CULVERT_LON = 0.9564980, 34.2896510    # ~1.7 km away      -> new object

CSV_HEADER = "id,structure,name,lat,lon,road_class,source,note,match_hint\n"
CSV_ROWS = (
    f"op_manafwa_tc_bridge,bridge,Manafwa Bridge (B112),"
    f"{TC_LAT},{TC_LON},main_road,operator,tc,{MAIN_ID}\n"
    f"op_north_footpath_culvert,culvert,North footpath culvert,"
    f"{CULVERT_LAT},{CULVERT_LON},footpath,operator,north,\n"
)


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    with db.conn() as c:   # seed the main bridge + a far ford (no cluster)
        db.add_object(c, MAIN_ID, "bridge", "Manafwa Bridge",
                      MAIN_LAT, MAIN_LON, {"structure": "bridge"}, source="osm")
        db.add_object(c, "w_far_ford", "bridge", "Far ford",
                      0.9200, 34.2500, {"structure": "ford"}, source="osm")
    return tmp_path


def _seed_old_bridge():
    with db.conn() as c:   # add the second clustered bridge for ambiguity tests
        db.add_object(c, OLD_ID, "bridge", "Old Manafwa bridge",
                      OLD_LAT, OLD_LON, {"structure": "bridge"}, source="osm")


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
    before = _count()                       # main bridge + far ford
    results = links.inject_operator_crossings(csv_path)

    spine = _by_id(MAIN_ID)
    assert spine is not None
    assert spine["source"] == "operator"
    assert spine["props"]["structure"] == "bridge"
    assert spine["props"]["crossing_class"] == "main_road"
    assert spine["props"]["osm_id"] == MAIN_ID
    assert spine["props"]["dedup_dist_m"] <= links.MATCH_THRESHOLD_M
    assert spine["name"] == "Manafwa Bridge"                        # OSM name kept
    assert spine["lat"] == MAIN_LAT and spine["lon"] == MAIN_LON    # OSM coords kept

    culvert = _by_id("op:op_north_footpath_culvert")
    assert culvert is not None
    assert culvert["source"] == "operator"
    assert culvert["props"]["structure"] == "culvert"
    assert culvert["props"]["crossing_class"] == "footpath"

    assert _count() == before + 1           # spine reused, one new culvert
    assert {r[1] for r in results} == {"deduped_onto_osm", "inserted_new"}


def test_match_hint_resolves_when_clustered(fresh_db):
    # both real bridges are within 50 m of the TC point; hint picks the main one.
    _seed_old_bridge()
    csv_path = _write_csv(fresh_db, CSV_ROWS)
    results = links.inject_operator_crossings(csv_path)
    assert _by_id(MAIN_ID)["source"] == "operator"     # hinted bridge wins
    assert _by_id(OLD_ID)["source"] == "osm"           # other bridge untouched
    assert ("op_manafwa_tc_bridge", "deduped_onto_osm", MAIN_ID) == results[0][:3]


def test_ambiguous_cluster_without_hint_refuses(fresh_db):
    _seed_old_bridge()
    before = _count()
    # same TC row but with the match_hint blanked -> two candidates in 50 m.
    body = (f"op_manafwa_tc_bridge,bridge,TC,{TC_LAT},{TC_LON},main_road,operator,tc,\n")
    csv_path = _write_csv(fresh_db, body)
    with pytest.raises(ValueError, match="matches 2 OSM crossings"):
        links.inject_operator_crossings(csv_path)
    assert _count() == before                          # nothing written
    assert _by_id(MAIN_ID)["source"] == "osm"
    assert _by_id(OLD_ID)["source"] == "osm"


def test_bad_hint_refuses(fresh_db):
    before = _count()
    body = (f"op_x,bridge,X,{TC_LAT},{TC_LON},main_road,operator,x,w999999999\n")
    csv_path = _write_csv(fresh_db, body)
    with pytest.raises(ValueError, match="resolves to no OSM crossing"):
        links.inject_operator_crossings(csv_path)
    assert _count() == before


def test_idempotent(fresh_db):
    csv_path = _write_csv(fresh_db, CSV_ROWS)
    links.inject_operator_crossings(csv_path)
    after_first = _count()
    results = links.inject_operator_crossings(csv_path)   # run again
    assert _count() == after_first                        # no duplicates
    assert {r[1] for r in results} == {"reinjected"}
    assert _by_id(MAIN_ID)["source"] == "operator"


def test_within_threshold_dedups_single_candidate(fresh_db):
    # ~44.5 m east of the far ford, no other crossing near -> single-candidate dedup.
    csv_path = _write_csv(fresh_db,
                          "op_near,ford,Near,0.9200,34.2504,minor_road,operator,,\n")
    before = _count()
    res = links.inject_operator_crossings(csv_path)
    assert res[0][1] == "deduped_onto_osm" and res[0][2] == "w_far_ford"
    assert _count() == before
    assert _by_id("w_far_ford")["source"] == "operator"


def test_beyond_threshold_inserts(fresh_db):
    # ~66.8 m east of the far ford -> new object.
    csv_path = _write_csv(fresh_db,
                          "op_far,ford,Far new,0.9200,34.2506,minor_road,operator,,\n")
    before = _count()
    res = links.inject_operator_crossings(csv_path)
    assert res[0][1] == "inserted_new"
    assert _count() == before + 1


def test_haversine_known_value():
    d = links._haversine_m(0.0, 0.0, 0.0, 0.001)   # 0.001 deg lon at equator
    assert abs(d - 111.32) < 1.0


def test_bad_row_rolls_back_earlier_writes(fresh_db):
    # first row valid (hinted onto the spine), second row invalid -> whole aborts.
    body = (
        f"op_manafwa_tc_bridge,bridge,TC,{TC_LAT},{TC_LON},main_road,operator,tc,{MAIN_ID}\n"
        f"op_bad,culver,Typo,0.95,34.28,footpath,operator,bad,\n"     # 'culver' typo
    )
    csv_path = _write_csv(fresh_db, body)
    with pytest.raises(ValueError):
        links.inject_operator_crossings(csv_path)
    assert _by_id(MAIN_ID)["source"] == "osm"          # rolled back
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
