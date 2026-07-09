r"""tests/test_spine_isolation.py - sub-step 5: prove the spine.

Topology (mirrors the real Manafwa town crossing):

    V1 --rS1--\                         V5 --\
    V2 --rS2---+--[rMain over Bmain]--+--rN--+-- H1 (clinic, north)
               \                      /           H2 sits ON rMain
                rAlt1--rAlt2---------/
                 (over Balt, reach R2 - NOT flooded)
    V3 --rS3-----[rOther over Bother]--+

Flood reach R at emergency:  Bmain and Bother block; Balt (on R2) does not.
Expected:
  V1 ISOLATED, why-chain names Bmain/rMain      (its own blocker)
  V3 ISOLATED, why-chain names Bother/rOther    (a DIFFERENT blocker)
  V2 REROUTED via the longer Balt route, alternate named
  V5 ISOLATED - its access road IS the severed road, and so is its clinic's
  H1/H2 SERVICE_AT_RISK

The V1-vs-V3 assertion is the regression: the old engine chose one arbitrary
severed road (`next(iter(severed))`) for EVERY settlement, so both chains named
the same bridge and one of them was a lie. The V5 case is the other old bug: a
severed road was still traversable as a zero-hop start==goal.
"""
import json

import pytest

from app import db, hazards, propagate


@pytest.fixture
def spine_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("DEMO_REACH_ID", raising=False)
    db.init()
    with db.conn() as c:
        A = lambda oid, t, props=None: db.add_object(
            c, oid, t, oid, 0.94, 34.28, props or {}, source="osm")
        L = lambda a, b, t: db.add_link(c, a, b, t, "test")

        A("R", "river_reach")                      # the flooded reach
        A("R2", "river_reach")                     # a different reach - stays dry
        for b in ("Bmain", "Bother", "Balt"):
            A(b, "bridge", {"structure": "bridge"})   # engineered: blocks at emergency
        for r in ("rS1", "rS2", "rS3", "rMain", "rOther", "rAlt1", "rAlt2", "rN"):
            A(r, "road_segment", {"all_weather": True})
        for v in ("V1", "V2", "V3", "V5"):
            A(v, "settlement")
        A("H1", "clinic")
        A("H2", "clinic")

        L("Bmain", "R", "crosses")
        L("Bother", "R", "crosses")
        L("Balt", "R2", "crosses")                 # not on the flooded reach
        L("rMain", "Bmain", "carries")
        L("rOther", "Bother", "carries")
        L("rAlt1", "Balt", "carries")

        for a, b in (("rS1", "rMain"), ("rS2", "rMain"), ("rMain", "rN"),
                     ("rS2", "rAlt1"), ("rAlt1", "rAlt2"), ("rAlt2", "rN"),
                     ("rS3", "rOther"), ("rOther", "rN")):
            L(a, b, "connects")

        L("V1", "rS1", "access_via"); L("V2", "rS2", "access_via")
        L("V3", "rS3", "access_via"); L("V5", "rMain", "access_via")
        L("H1", "rN", "access_via")
        L("H2", "rMain", "access_via")             # clinic ON the severed road
        for v in ("V1", "V2", "V3"):
            L("H1", v, "serves")
        L("H2", "V5", "serves")
    return tmp_path


def _propagate(sev="emergency"):
    hid = hazards.create_hazard("riverine_flood", sev, "R", "TEST", "spine test")
    propagate.run(hid)
    with db.conn() as c:
        rows = list(c.execute("SELECT * FROM impacts WHERE hazard_id=?", (hid,)))
    states = {r["object_id"]: r["state"] for r in rows}
    chains = {r["object_id"]: json.loads(r["why_chain_json"]) for r in rows}
    return states, chains


def test_bridges_block_and_roads_sever(spine_db):
    states, _ = _propagate()
    assert states["Bmain"] == "LIKELY_IMPASSABLE"
    assert states["Bother"] == "LIKELY_IMPASSABLE"
    assert "Balt" not in states                  # different reach: untouched
    assert states["rMain"] == "SEVERED"
    assert states["rOther"] == "SEVERED"
    assert "rAlt1" not in states


def test_only_crossing_isolates_village(spine_db):
    states, _ = _propagate()
    assert states["V1"] == "ISOLATED"


def test_village_with_alternate_is_rerouted_not_isolated(spine_db):
    """Invariant 3: an alternate path degrades to REROUTED, never ISOLATED."""
    states, chains = _propagate()
    assert states["V2"] == "REROUTED"
    alt = [s for s in chains["V2"] if str(s).startswith("alternate_via:")]
    assert alt, chains["V2"]
    assert "rAlt1" in alt[0] and "rAlt2" in alt[0]   # the alternate is named


def test_why_chain_names_each_settlements_own_blocker(spine_db):
    """THE regression. V1 and V3 are cut off by DIFFERENT bridges; each chain
    must name its own. The old engine named one arbitrary severed road for all."""
    states, chains = _propagate()
    assert states["V1"] == "ISOLATED" and states["V3"] == "ISOLATED"

    assert "Bmain" in chains["V1"] and "rMain" in chains["V1"]
    assert "Bother" not in chains["V1"] and "rOther" not in chains["V1"]

    assert "Bother" in chains["V3"] and "rOther" in chains["V3"]
    assert "Bmain" not in chains["V3"] and "rMain" not in chains["V3"]


def test_why_chain_is_complete_hazard_to_facility(spine_db):
    """Invariant 2: hazard -> reach -> bridge -> road -> settlement -> facility."""
    _, chains = _propagate()
    ch = chains["V1"]
    assert ch[0] == "hazard:riverine_flood/emergency"
    assert ch[1] == "R"
    assert ch.index("Bmain") < ch.index("rMain") < ch.index("V1")
    assert ch[-1] == "H1"


def test_severed_road_is_not_traversable_as_endpoint(spine_db):
    """V5's access road IS the severed road, and so is its clinic's. The old
    BFS returned start==goal in one hop and called V5 reachable."""
    states, chains = _propagate()
    assert states["V5"] == "ISOLATED"
    assert "Bmain" in chains["V5"] and "rMain" in chains["V5"]


def test_facilities_lose_service(spine_db):
    states, _ = _propagate()
    assert states["H1"] == "SERVICE_AT_RISK"
    assert states["H2"] == "SERVICE_AT_RISK"


def test_no_isolation_at_alert_for_engineered_bridges(spine_db):
    """D-029 in code: engineered bridges are AT_RISK (non-blocking) at alert."""
    states, _ = _propagate("alert")
    assert states["Bmain"] == "AT_RISK"
    assert "rMain" not in states                 # nothing severed
    for v in ("V1", "V2", "V3", "V5"):
        assert v not in states                   # nobody isolated


def test_deterministic_states_and_chains(spine_db):
    """Invariant 1: identical inputs -> identical impacts AND why-chains."""
    s1, c1 = _propagate()
    s2, c2 = _propagate()
    assert s1 == s2
    assert c1 == c2


def test_removing_hazard_clears_impacts(spine_db):
    """Invariant 5: idempotent re-scan / clean teardown."""
    _propagate()
    hazards.clear_hazards()
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM impacts").fetchone()["n"] == 0
        assert c.execute("SELECT COUNT(*) n FROM actions").fetchone()["n"] == 0
