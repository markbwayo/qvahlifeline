"""tests/test_infer_crossing_links.py - merge gate for links.infer_crossing_links.

Hermetic: fresh temp DB, hand-built geometry. Tests crosses (nearest reach),
carries (vehicle road within CARRIES_THRESHOLD_M; footpath gate; synth crossings;
clustered bridges must not cross-link), and the nearest-road fallback for
crossings that would otherwise get zero carriers.

test_regression_spine_bridge_gets_its_own_carrier reproduces the real bug found
on the live Manafwa graph: the demo-spine bridge w128611448's true nearest road
was 17.7 m away (just past the old 15 m threshold) while the OTHER town bridge's
road sat at 23.9 m - so the spine silently got zero carriers and could never
sever a route. See D-026.
"""
import pytest

from app import db, links


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    return tmp_path


def _river(c, oid, geometry):
    db.add_object(c, oid, "river_reach", oid, geometry[0][0], geometry[0][1],
                  {"geometry": geometry}, source="osm")


def _road(c, oid, geometry, highway="tertiary"):
    db.add_object(c, oid, "road_segment", oid, geometry[0][0], geometry[0][1],
                  {"tags": {"highway": highway}, "geometry": geometry}, source="osm")


def _bridge(c, oid, lat, lon, props=None, source="osm"):
    db.add_object(c, oid, "bridge", oid, lat, lon,
                  props or {"structure": "bridge"}, source=source)


def _links(ltype=None):
    with db.conn() as c:
        rows = db.links(c)
    return [r for r in rows if ltype is None or r["type"] == ltype]


def _crosses_of(bid):
    return {r["dst"] for r in _links("crosses") if r["src"] == bid}


def _carriers_of(bid):
    return {r["src"] for r in _links("carries") if r["dst"] == bid}


def _carrier_source(bid, rid):
    for r in _links("carries"):
        if r["src"] == rid and r["dst"] == bid:
            return r["inferred_by"]
    return None


def test_pt_poly_dist_math():
    # point (0,0) to an N-S line at lon 0.0005 -> ~55.7 m
    d = links._pt_poly_dist_m((0.0, 0.0), [(-0.001, 0.0005), (0.001, 0.0005)])
    assert abs(d - 55.66) < 1.0


def test_crosses_links_nearest_reach(fresh_db):
    with db.conn() as c:
        _river(c, "rvA", [(-0.01, 34.0), (0.01, 34.0)])         # ~5.6 m from bridge
        _river(c, "rvB", [(-0.01, 34.001), (0.01, 34.001)])     # ~106 m from bridge
        _bridge(c, "bX", 0.0, 34.00005)
    links.infer_crossing_links()
    assert _crosses_of("bX") == {"rvA"}                          # nearest only


def test_crosses_none_when_far(fresh_db):
    with db.conn() as c:
        _river(c, "rvA", [(-0.01, 34.0), (0.01, 34.0)])
        _bridge(c, "bFar", 0.0, 34.001)                          # ~111 m -> no crosses
    links.infer_crossing_links()
    assert _crosses_of("bFar") == set()


def test_carries_road_within_threshold(fresh_db):
    with db.conn() as c:
        _road(c, "rdOn", [(-0.001, 34.0), (0.001, 34.0)])        # through bX (0 m)
        _road(c, "rdOff", [(-0.001, 34.0004), (0.001, 34.0004)]) # ~44 m away
        _bridge(c, "bX", 0.0, 34.0)
    links.infer_crossing_links()
    assert _carriers_of("bX") == {"rdOn"}
    assert _carrier_source("bX", "rdOn") == "geom_carries"


def test_carries_both_segments_of_split_road(fresh_db):
    with db.conn() as c:
        _road(c, "rdW", [(0.0, 33.999), (0.0, 34.0)])            # ends at bX
        _road(c, "rdE", [(0.0, 34.0), (0.0, 34.001)])            # starts at bX
        _bridge(c, "bX", 0.0, 34.0)
    links.infer_crossing_links()
    assert _carriers_of("bX") == {"rdW", "rdE"}                  # both sides sever


def test_footpath_crossing_gets_crosses_not_carries(fresh_db):
    with db.conn() as c:
        _river(c, "rvA", [(-0.01, 34.0), (0.01, 34.0)])
        _road(c, "rdOn", [(-0.001, 34.0), (0.001, 34.0)])
        _bridge(c, "bFP", 0.0, 34.0,
                {"structure": "culvert", "crossing_class": "footpath"}, "operator")
    links.infer_crossing_links()
    assert _crosses_of("bFP") == {"rvA"}                         # still crosses the stream
    assert _carriers_of("bFP") == set()                          # but carries nothing


def test_footpath_excluded_even_from_fallback(fresh_db):
    with db.conn() as c:
        # nearest road is 60 m away - within fallback range, but footpath must
        # still get NOTHING (gate applies before the fallback pass runs).
        _road(c, "rdFar", [(-0.001, 34.00054), (0.001, 34.00054)])   # ~60 m
        _bridge(c, "bFP", 0.0, 34.0,
                {"structure": "culvert", "crossing_class": "footpath"}, "operator")
    links.infer_crossing_links()
    assert _carriers_of("bFP") == set()


def test_synth_crossing_gets_both_links_though_unclassified(fresh_db):
    with db.conn() as c:
        _river(c, "rvA", [(-0.01, 34.0), (0.01, 34.0)])
        _road(c, "rdS", [(-0.001, 34.0), (0.001, 34.0)])
        _bridge(c, "synth:x", 0.0, 34.0,
                {"structure": None, "needs_review": True, "synth": True,
                 "synth_road_id": "rdS", "synth_reach_id": "rvA"}, "synth")
    links.infer_crossing_links()
    assert _crosses_of("synth:x") == {"rvA"}
    assert _carriers_of("synth:x") == {"rdS"}                    # can sever, though unclassified


def test_clustered_bridges_do_not_crosslink(fresh_db):
    # two bridges ~27.8 m apart (comfortably above CARRIES_THRESHOLD_M=20),
    # each with its own road at 0 m.
    with db.conn() as c:
        _road(c, "rdA", [(-0.001, 34.00000), (0.001, 34.00000)])
        _road(c, "rdB", [(-0.001, 34.00025), (0.001, 34.00025)])
        _bridge(c, "bA", 0.0, 34.00000)
        _bridge(c, "bB", 0.0, 34.00025)
    links.infer_crossing_links()
    assert _carriers_of("bA") == {"rdA"}
    assert _carriers_of("bB") == {"rdB"}


def test_regression_spine_bridge_gets_its_own_carrier(fresh_db):
    """Locks in the D-026 fix: a bridge whose own road is ~18 m away (inside the
    new 20 m threshold, outside the old 15 m one) must carry it; a nearby OTHER
    bridge's road at ~24 m must not cross-link. Mirrors the real w128611448
    (17.7 m own / 23.9 m other) measurement from the live graph."""
    with db.conn() as c:
        db.add_object(c, "rvManafwa", "river_reach", "reach", 0.0, 34.0,
                      {"geometry": [(-0.001, 34.0), (0.001, 34.0)]}, source="osm")
        own_road = [(-0.0001617, 33.999), (-0.0001617, 34.001)]   # ~18.0 m south
        other_road = [(0.0002157, 33.999), (0.0002157, 34.001)]   # ~24.0 m north
        _road(c, "ownRoad", own_road, highway="secondary")
        _road(c, "otherRoad", other_road, highway="tertiary")
        _bridge(c, "spine", 0.0, 34.0, {"structure": "bridge"}, "operator")
    rep = links.infer_crossing_links()
    assert _carriers_of("spine") == {"ownRoad"}                  # captured, not missed
    assert "otherRoad" not in _carriers_of("spine")               # no cross-link
    assert "spine" not in [x for x, _, _ in rep["fallback_used"]] # primary match, not fallback


def test_fallback_when_nothing_within_primary_threshold(fresh_db):
    with db.conn() as c:
        # nearest road ~60 m away: outside the 20 m primary, inside the 100 m
        # fallback cap -> must still get a carrier, flagged as fallback.
        _road(c, "rdFar", [(-0.001, 34.00054), (0.001, 34.00054)])
        _bridge(c, "bLonely", 0.0, 34.0)
    rep = links.infer_crossing_links()
    assert _carriers_of("bLonely") == {"rdFar"}
    assert _carrier_source("bLonely", "rdFar") == "geom_carries_fallback"
    assert rep["fallback_used"] and rep["fallback_used"][0][0] == "bLonely"
    assert rep["no_carrier"] == []


def test_fallback_capped_beyond_100m(fresh_db):
    with db.conn() as c:
        # nearest road ~167 m away: beyond even the fallback cap -> no carrier.
        _road(c, "rdWay", [(-0.0015, 34.0015), (0.0015, 34.0015)])
        _bridge(c, "bStranded", 0.0, 34.0)
    rep = links.infer_crossing_links()
    assert _carriers_of("bStranded") == set()
    assert "bStranded" in rep["no_carrier"]
    assert rep["fallback_used"] == []


def test_idempotent(fresh_db):
    with db.conn() as c:
        _river(c, "rvA", [(-0.01, 34.0), (0.01, 34.0)])
        _road(c, "rdOn", [(-0.001, 34.0), (0.001, 34.0)])
        _bridge(c, "bX", 0.0, 34.0)
    links.infer_crossing_links()
    n1 = len(_links())
    links.infer_crossing_links()                                 # re-run
    assert len(_links()) == n1                                   # no duplicates / growth
