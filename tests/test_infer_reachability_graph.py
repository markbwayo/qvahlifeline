"""tests/test_infer_reachability_graph.py - merge gate for the 3b link inference
(connects / access_via / serves), plus a mini end-to-end reachability run through
the real propagate engine.
"""
import pytest

from app import db, links


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    return tmp_path


def _road(c, oid, geometry, highway="tertiary"):
    db.add_object(c, oid, "road_segment", oid, geometry[0][0], geometry[0][1],
                  {"tags": {"highway": highway}, "geometry": geometry}, source="osm")


def _pt(c, oid, otype, lat, lon):
    db.add_object(c, oid, otype, oid, lat, lon, {}, source="osm")


def _links(ltype):
    with db.conn() as c:
        return [r for r in db.links(c) if r["type"] == ltype]


def _connects_pairs():
    return {frozenset((r["src"], r["dst"])) for r in _links("connects")}


def _access_of(oid):
    return {r["dst"] for r in _links("access_via") if r["src"] == oid}


def _serves_pairs():
    return {(r["src"], r["dst"]) for r in _links("serves")}


def test_round_pt():
    assert links._round_pt((0.9406239, 34.2802124)) == (0.94062, 34.28021)


def test_connects_shared_vertex(fresh_db):
    with db.conn() as c:
        _road(c, "rA", [(0.0, 34.0), (0.0, 34.01)])            # meets rB at (0,34.01)
        _road(c, "rB", [(0.0, 34.01), (0.0, 34.02)])
        _road(c, "rC", [(0.5, 34.0), (0.5, 34.01)])            # far away, no shared vertex
    links.infer_road_network()
    assert _connects_pairs() == {frozenset(("rA", "rB"))}


def test_connects_excludes_footpaths(fresh_db):
    with db.conn() as c:
        _road(c, "rA", [(0.0, 34.0), (0.0, 34.01)])
        _road(c, "fp", [(0.0, 34.01), (0.0, 34.02)], highway="path")  # footpath
    links.infer_road_network()
    assert _connects_pairs() == set()                          # footpath not in graph


def test_access_via_nearest_vehicle_road(fresh_db):
    with db.conn() as c:
        _road(c, "near", [(-0.001, 34.0), (0.001, 34.0)])      # ~0 m from settlement
        _road(c, "far", [(-0.001, 34.01), (0.001, 34.01)])     # ~1.1 km away
        _pt(c, "S1", "settlement", 0.0, 34.0)
        _pt(c, "H1", "clinic", 0.0, 34.00005)                  # facility attaches too
    links.infer_access_and_serves()
    assert _access_of("S1") == {"near"}
    assert _access_of("H1") == {"near"}


def test_serves_nearest_clinic_within_cap(fresh_db):
    with db.conn() as c:
        _road(c, "r", [(-0.01, 34.0), (0.01, 34.0)])
        _pt(c, "S1", "settlement", 0.0, 34.0)
        _pt(c, "Hnear", "clinic", 0.001, 34.0)                 # ~111 m
        _pt(c, "Hfar", "clinic", 0.05, 34.0)                   # ~5.5 km
    links.infer_access_and_serves()
    assert ("Hnear", "S1") in _serves_pairs()
    assert ("Hfar", "S1") not in _serves_pairs()               # nearest wins


def test_idempotent(fresh_db):
    with db.conn() as c:
        _road(c, "rA", [(0.0, 34.0), (0.0, 34.01)])
        _road(c, "rB", [(0.0, 34.01), (0.0, 34.02)])
        _pt(c, "S1", "settlement", 0.0, 34.0)
        _pt(c, "H1", "clinic", 0.0, 34.02)
    links.infer_road_network(); links.infer_access_and_serves()
    with db.conn() as c:
        n1 = len(db.links(c))
    links.infer_road_network(); links.infer_access_and_serves()
    with db.conn() as c:
        assert len(db.links(c)) == n1                          # no growth


def test_mini_reachability_isolates_when_bridge_blocks(fresh_db):
    """End-to-end through the real engine: a settlement whose only clinic route
    crosses one culvert goes ISOLATED when that culvert is IMPASSABLE."""
    from app import propagate
    with db.conn() as c:
        # river + a culvert crossing it (culvert -> IMPASSABLE at emergency)
        _pt(c, "R", "river_reach", 0.0005, 34.0)
        db.add_object(c, "X", "bridge", "culvert X", 0.0005, 34.0,
                      {"structure": "culvert"}, source="osm")
        # south settlement, north clinic; the only road path crosses X
        db.add_object(c, "rS", "road_segment", "south", 0.0, 34.0,
                      {"tags": {"highway": "tertiary"},
                       "geometry": [[0.0, 34.0], [0.0004, 34.0]]}, source="osm")
        db.add_object(c, "rX", "road_segment", "over-crossing", 0.0004, 34.0,
                      {"tags": {"highway": "tertiary"},
                       "geometry": [[0.0004, 34.0], [0.0006, 34.0]]}, source="osm")
        db.add_object(c, "rN", "road_segment", "north", 0.0006, 34.0,
                      {"tags": {"highway": "tertiary"},
                       "geometry": [[0.0006, 34.0], [0.001, 34.0]]}, source="osm")
        _pt(c, "S1", "settlement", 0.0, 34.0)
        _pt(c, "H1", "clinic", 0.001, 34.0)
    # infer all links: crossing links + reachability graph
    links.infer_crossing_links()
    links.infer_road_network()
    links.infer_access_and_serves()
    # rX carries X (the over-crossing road) - confirm before propagating
    carries = {(r["src"], r["dst"]) for r in _links("carries")}
    assert ("rX", "X") in carries
    # raise an emergency riverine flood on R, propagate
    with db.conn() as c:
        c.execute("INSERT INTO hazards (kind, severity, target_id, source, "
                  "trigger_detail, created_utc, active) VALUES "
                  "('riverine_flood','emergency','R','test','t',?,1)", (db.now(),))
        hid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    propagate.run(hid)
    with db.conn() as c:
        impacts = {r["object_id"]: r["state"]
                   for r in c.execute("SELECT * FROM impacts WHERE hazard_id=?", (hid,))}
    assert impacts.get("S1") == "ISOLATED"                     # the whole point
