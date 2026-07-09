r"""tests/test_crossing_connects.py - merge gate for D-031, D-032, D-033.

D-031: in OSM a bridge is its own way, so the roads either side of it share no
vertex. Vertex-based `connects` leaves the two banks as separate components and
NO vehicle route ever crosses the river. Roads carrying the same crossing must be
connected through it.

D-032: 09 step 4 is per-facility. Pooling facilities hides the loss of one - a
village that loses its clinic but keeps its local school must still be ISOLATED.

D-033: a facility is SERVICE_AT_RISK only for settlements that HAD baseline
access and lost it, never for ones that could never reach it.
"""
import json

import pytest

from app import db, hazards, links, propagate


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("DEMO_REACH_ID", raising=False)
    db.init()
    return tmp_path


def _connects():
    with db.conn() as c:
        return {(tuple(sorted((l["src"], l["dst"]))), l["inferred_by"])
                for l in db.links(c) if l["type"] == "connects"}


# --- D-031: roads join through the crossing -------------------------------

def test_roads_carrying_same_crossing_are_connected(fresh_db):
    with db.conn() as c:
        db.add_object(c, "X", "bridge", "X", 0.0, 34.0, {"structure": "bridge"}, "osm")
        for r in ("rSouth", "rNorth"):
            db.add_object(c, r, "road_segment", r, 0.0, 34.0, {}, "osm")
        db.add_link(c, "rSouth", "X", "carries", "t")
        db.add_link(c, "rNorth", "X", "carries", "t")
    rep = links.infer_crossing_connects()
    assert rep["via_crossing"] == 1 and rep["crossings_joined"] == 1
    assert (("rNorth", "rSouth"), "via_crossing") in _connects()


def test_roads_on_different_crossings_not_connected(fresh_db):
    with db.conn() as c:
        for x in ("X1", "X2"):
            db.add_object(c, x, "bridge", x, 0.0, 34.0, {"structure": "bridge"}, "osm")
        for r in ("rA", "rB"):
            db.add_object(c, r, "road_segment", r, 0.0, 34.0, {}, "osm")
        db.add_link(c, "rA", "X1", "carries", "t")
        db.add_link(c, "rB", "X2", "carries", "t")
    rep = links.infer_crossing_connects()
    assert rep["via_crossing"] == 0
    assert _connects() == set()


def test_does_not_clobber_an_existing_vertex_connect(fresh_db):
    with db.conn() as c:
        db.add_object(c, "X", "bridge", "X", 0.0, 34.0, {"structure": "bridge"}, "osm")
        for r in ("rA", "rB"):
            db.add_object(c, r, "road_segment", r, 0.0, 34.0, {}, "osm")
        db.add_link(c, "rA", "X", "carries", "t")
        db.add_link(c, "rB", "X", "carries", "t")
        db.add_link(c, "rA", "rB", "connects", "geom_connects")   # already share a vertex
    rep = links.infer_crossing_connects()
    assert rep["via_crossing"] == 0
    assert (("rA", "rB"), "geom_connects") in _connects()


def test_footpath_crossing_never_joins_the_vehicle_graph(fresh_db):
    with db.conn() as c:
        db.add_object(c, "FP", "bridge", "FP", 0.0, 34.0,
                      {"structure": "culvert", "crossing_class": "footpath"}, "operator")
        for r in ("rA", "rB"):
            db.add_object(c, r, "road_segment", r, 0.0, 34.0, {}, "osm")
        # footpath crossings get no `carries` links at all (09 gate)
    rep = links.infer_crossing_connects()
    assert rep["via_crossing"] == 0


def test_idempotent(fresh_db):
    with db.conn() as c:
        db.add_object(c, "X", "bridge", "X", 0.0, 34.0, {"structure": "bridge"}, "osm")
        for r in ("rA", "rB", "rC"):
            db.add_object(c, r, "road_segment", r, 0.0, 34.0, {}, "osm")
            db.add_link(c, r, "X", "carries", "t")
    links.infer_crossing_connects()
    with db.conn() as c:
        n1 = len(db.links(c))
    links.infer_crossing_connects()
    with db.conn() as c:
        assert len(db.links(c)) == n1


# --- D-032 / D-033: per-facility reachability ------------------------------

@pytest.fixture
def banks_db(fresh_db):
    r"""South bank: village V + its local school S (same bank).
    North bank: clinic H. The ONLY link between banks is bridge X.

        V --rS--[X]--rN-- H
        S on rS (south bank, unaffected)
    """
    with db.conn() as c:
        A = lambda oid, t, p=None: db.add_object(c, oid, t, oid, 0.94, 34.28,
                                                 p or {}, source="osm")
        L = lambda a, b, t: db.add_link(c, a, b, t, "test")
        A("R", "river_reach")
        A("X", "bridge", {"structure": "bridge"})
        A("rS", "road_segment"); A("rN", "road_segment")
        A("V", "settlement"); A("S", "school"); A("H", "clinic")
        A("Hfar", "clinic")                      # unreachable clinic, own island
        A("rIsland", "road_segment")
        L("X", "R", "crosses")
        L("rS", "X", "carries"); L("rN", "X", "carries")   # joined via X only
        L("V", "rS", "access_via"); L("S", "rS", "access_via")
        L("H", "rN", "access_via"); L("Hfar", "rIsland", "access_via")
        L("S", "V", "serves"); L("H", "V", "serves"); L("Hfar", "V", "serves")
    links.infer_crossing_connects()
    return fresh_db


def _propagate(sev="emergency"):
    hid = hazards.create_hazard("riverine_flood", sev, "R", "TEST", "d")
    propagate.run(hid)
    with db.conn() as c:
        rows = list(c.execute("SELECT * FROM impacts WHERE hazard_id=?", (hid,)))
    return ({r["object_id"]: r["state"] for r in rows},
            {r["object_id"]: json.loads(r["why_chain_json"]) for r in rows})


def test_baseline_route_crosses_the_river(banks_db):
    """Without D-031 the banks are separate components and this is None."""
    objs, by_type = propagate._graph()
    adj = propagate._road_adj(by_type, set())
    hops, path = propagate._hops(adj, ["rS"], ["rN"])
    assert hops == 2 and path == ["rS", "rN"]


def test_village_isolated_from_clinic_though_school_survives(banks_db):
    """D-032: pooling facilities would report NO IMPACT here."""
    states, chains = _propagate()
    assert states["V"] == "ISOLATED"
    assert chains["V"][-1] == "H"              # names the facility it lost
    assert "X" in chains["V"]                  # and the crossing that did it


def test_unreachable_clinic_is_not_service_at_risk(banks_db):
    """D-033: Hfar was never reachable; the flood didn't take it away."""
    states, _ = _propagate()
    assert "Hfar" not in states


def test_reachable_clinic_is_service_at_risk_with_crossing_in_chain(banks_db):
    states, chains = _propagate()
    assert states["H"] == "SERVICE_AT_RISK"
    assert "X" in chains["H"]                  # why-chain names the crossing
    assert "V" in chains["H"] and chains["H"][-1] == "H"


def test_local_school_on_same_bank_is_unaffected(banks_db):
    states, _ = _propagate()
    assert "S" not in states                   # school never lost its village


# --- D-034: edge-cut vs road-removal --------------------------------------

def test_multi_carrier_crossing_cuts_the_edge_not_the_roads(fresh_db):
    r"""A bridge with a road either side: blocking it must remove the crossing
    edge, leaving both approach roads drivable on their own bank."""
    with db.conn() as c:
        A = lambda oid, t, p=None: db.add_object(c, oid, t, oid, 0.94, 34.28,
                                                 p or {}, source="osm")
        L = lambda a, b, t: db.add_link(c, a, b, t, "test")
        A("R", "river_reach"); A("X", "bridge", {"structure": "bridge"})
        A("rS", "road_segment"); A("rN", "road_segment")
        A("rSpur", "road_segment")            # south-bank spur off rS
        A("V", "settlement"); A("S", "school"); A("H", "clinic")
        L("X", "R", "crosses")
        L("rS", "X", "carries"); L("rN", "X", "carries")
        L("rS", "rSpur", "connects")          # shared vertex, same bank
        L("V", "rSpur", "access_via"); L("S", "rS", "access_via")
        L("H", "rN", "access_via")
        L("S", "V", "serves"); L("H", "V", "serves")
    links.infer_crossing_connects()
    states, chains = _propagate()
    # D-035: the bridge deck is the impassable object; the approach roads either
    # side stay drivable and take NO state. Marking them SEVERED while still
    # routing traffic over them would tell an officer "this road is cut, drive it".
    assert states["X"] == "LIKELY_IMPASSABLE"
    assert "rS" not in states and "rN" not in states
    assert states["V"] == "ISOLATED"           # from the clinic across the river
    assert "S" not in states                   # school on own bank still reachable
    assert "X" in chains["V"]                  # the why-chain names the crossing
    assert "rS" not in chains["V"]             # and no phantom severed road


def test_single_carrier_crossing_removes_the_road(fresh_db):
    r"""A crossing mid-way through ONE road (e.g. a synthesised road x river
    intersection): the break cannot be localised, so the road is dropped whole.
    Conservative - over-states the break rather than missing it."""
    with db.conn() as c:
        A = lambda oid, t, p=None: db.add_object(c, oid, t, oid, 0.94, 34.28,
                                                 p or {}, source="osm")
        L = lambda a, b, t: db.add_link(c, a, b, t, "test")
        A("R", "river_reach")
        A("X", "bridge", {"structure": None, "needs_review": True})   # synth
        A("rMid", "road_segment"); A("rS", "road_segment"); A("rN", "road_segment")
        A("V", "settlement"); A("H", "clinic")
        L("X", "R", "crosses")
        L("rMid", "X", "carries")             # sole carrier
        L("rS", "rMid", "connects"); L("rMid", "rN", "connects")
        L("V", "rS", "access_via"); L("H", "rN", "access_via")
        L("H", "V", "serves")
    states, chains = _propagate()
    assert states["rMid"] == "SEVERED"
    assert states["V"] == "ISOLATED"
    assert "X" in chains["V"] and "rMid" in chains["V"]
    # the unclassified crossing was assumed most fragile (D-027) and blocked
    assert states["X"] == "IMPASSABLE"


def test_settlement_on_a_cut_but_surviving_road_keeps_local_access(fresh_db):
    r"""The village sits ON the carrier road. It loses the far bank, but must
    still reach a facility on its own side of the crossing."""
    with db.conn() as c:
        A = lambda oid, t, p=None: db.add_object(c, oid, t, oid, 0.94, 34.28,
                                                 p or {}, source="osm")
        L = lambda a, b, t: db.add_link(c, a, b, t, "test")
        A("R", "river_reach"); A("X", "bridge", {"structure": "bridge"})
        A("rS", "road_segment"); A("rN", "road_segment")
        A("V", "settlement"); A("W", "water_point"); A("H", "clinic")
        L("X", "R", "crosses")
        L("rS", "X", "carries"); L("rN", "X", "carries")
        L("V", "rS", "access_via"); L("W", "rS", "access_via")
        L("H", "rN", "access_via")
        L("W", "V", "serves"); L("H", "V", "serves")
    links.infer_crossing_connects()
    states, _ = _propagate()
    assert states["V"] == "ISOLATED"           # lost the clinic
    assert "W" not in states                   # kept the borehole on its own bank


def test_alternate_route_never_traverses_a_severed_road(fresh_db):
    r"""D-035 guard. A SEVERED road is dropped from the network, so it can never
    appear in the alternate route we hand an officer. (The live demo printed
    `alternate_via: ...>w169219432>...` where w169219432 was itself SEVERED.)

        V --rS--+--[Xmid on rMid]--+--rN-- H        (rMid: sole carrier -> SEVERED)
                \--rDetour---------/                 (longer, stays open)
    """
    with db.conn() as c:
        A = lambda oid, t, p=None: db.add_object(c, oid, t, oid, 0.94, 34.28,
                                                 p or {}, source="osm")
        L = lambda a, b, t: db.add_link(c, a, b, t, "test")
        A("R", "river_reach"); A("R2", "river_reach")
        A("Xmid", "bridge", {"structure": "ford"})      # blocks at emergency
        A("rS", "road_segment"); A("rMid", "road_segment"); A("rN", "road_segment")
        A("rD1", "road_segment"); A("rD2", "road_segment")
        A("V", "settlement"); A("H", "clinic")
        L("Xmid", "R", "crosses")
        L("rMid", "Xmid", "carries")                    # SOLE carrier -> road dropped
        L("rS", "rMid", "connects"); L("rMid", "rN", "connects")
        L("rS", "rD1", "connects"); L("rD1", "rD2", "connects"); L("rD2", "rN", "connects")
        L("V", "rS", "access_via"); L("H", "rN", "access_via")
        L("H", "V", "serves")
    states, chains = _propagate()

    assert states["rMid"] == "SEVERED"
    assert states["V"] == "REROUTED"                     # detour exists
    alt = [s for s in chains["V"] if str(s).startswith("alternate_via:")][0]
    assert "rMid" not in alt                             # never route over a severed road
    assert "rD1" in alt and "rD2" in alt                 # the real detour is named
    # and the why-chain names what blocked the baseline route
    assert "Xmid" in chains["V"] and "rMid" in chains["V"]
