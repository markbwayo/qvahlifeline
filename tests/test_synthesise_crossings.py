"""tests/test_synthesise_crossings.py - merge gate for links.synthesise_crossings.

Hermetic: fresh temp DB, hand-built road/river polylines. Tests the geometry and
the safety property (synth crossings carry no structure -> no fragility yet).
"""
import pytest

from app import db, links


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    return tmp_path


def _road(c, oid, highway, geometry):
    db.add_object(c, oid, "road_segment", oid, geometry[0][0], geometry[0][1],
                  {"tags": {"highway": highway}, "geometry": geometry}, source="osm")


def _river(c, oid, geometry):
    db.add_object(c, oid, "river_reach", oid, geometry[0][0], geometry[0][1],
                  {"geometry": geometry}, source="osm")


def _crossings():
    with db.conn() as c:
        return [o for o in db.objects(c) if o["type"] == "bridge"]


# An E-W vehicle road at lat 0.0 and an N-S river at lon 34.005 cross at (0.0, 34.005).
ROAD_EW = [(0.0, 34.000), (0.0, 34.010)]
RIVER_NS = [(-0.005, 34.005), (0.005, 34.005)]


def test_seg_intersect_math():
    pt = links._seg_intersect((0.0, 34.0), (0.0, 34.01),
                              (-0.005, 34.005), (0.005, 34.005))
    assert pt is not None
    assert abs(pt[0] - 0.0) < 1e-9 and abs(pt[1] - 34.005) < 1e-9
    # parallel / non-crossing -> None
    assert links._seg_intersect((0.0, 34.0), (0.0, 34.01),
                                (0.001, 34.0), (0.001, 34.01)) is None


def test_road_crosses_river_creates_synth(fresh_db):
    with db.conn() as c:
        _road(c, "rd1", "tertiary", ROAD_EW)
        _river(c, "rv1", RIVER_NS)
    created = links.synthesise_crossings()
    assert len(created) == 1
    xs = _crossings()
    assert len(xs) == 1
    x = xs[0]
    assert x["source"] == "synth"
    assert x["props"]["needs_review"] is True
    assert x["props"].get("structure") is None          # not guessed
    assert x["props"]["synth_road_id"] == "rd1"
    assert x["props"]["synth_reach_id"] == "rv1"
    assert abs(x["lat"] - 0.0) < 1e-6 and abs(x["lon"] - 34.005) < 1e-6


def test_existing_crossing_suppresses_synth(fresh_db):
    with db.conn() as c:
        _road(c, "rd1", "tertiary", ROAD_EW)
        _river(c, "rv1", RIVER_NS)
        # an existing bridge right at the intersection point
        db.add_object(c, "w_here", "bridge", "Existing", 0.0, 34.005,
                      {"structure": "bridge"}, source="osm")
    created = links.synthesise_crossings()
    assert created == []
    assert len(_crossings()) == 1                        # only the existing one


def test_footpath_ignored(fresh_db):
    with db.conn() as c:
        _road(c, "fp1", "path", ROAD_EW)                 # not a vehicle road
        _river(c, "rv1", RIVER_NS)
    created = links.synthesise_crossings()
    assert created == []
    assert len(_crossings()) == 0


def test_parallel_no_intersection(fresh_db):
    with db.conn() as c:
        # a road running N-S like the river but offset ~111 m east -> never crosses
        _road(c, "rd1", "secondary", [(-0.005, 34.006), (0.005, 34.006)])
        _river(c, "rv1", RIVER_NS)
    created = links.synthesise_crossings()
    assert created == []
    assert len(_crossings()) == 0


def test_two_crossings_far_apart(fresh_db):
    # a road that crosses the same river at two points ~1.1 km apart -> 2 crossings.
    river = [(-0.01, 34.005), (0.01, 34.005)]
    road = [(-0.005, 34.000), (-0.005, 34.010),
            (0.005, 34.010), (0.005, 34.000)]
    with db.conn() as c:
        _road(c, "rd1", "tertiary", road)
        _river(c, "rv1", river)
    created = links.synthesise_crossings()
    assert len(created) == 2
    assert len(_crossings()) == 2


def test_idempotent(fresh_db):
    with db.conn() as c:
        _road(c, "rd1", "tertiary", ROAD_EW)
        _river(c, "rv1", RIVER_NS)
    links.synthesise_crossings()
    n1 = len(_crossings())
    created2 = links.synthesise_crossings()             # run again
    assert created2 == []                                # nothing new
    assert len(_crossings()) == n1                       # no duplicates
