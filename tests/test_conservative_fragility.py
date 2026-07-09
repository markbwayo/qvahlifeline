"""tests/test_conservative_fragility.py - merge gate for D-027.

The bug this locks out: an unclassified crossing (structure=None, e.g. every
synthesised crossing) was scored as an engineered "bridge" - the LEAST fragile
structure - so a flood left it passable, its road unsevered, and a village that
should read ISOLATED read fine. A false all-clear.

Rule under test: unknown structure => assume the MOST fragile structure (ford).
Never fail toward all-clear.
"""
import pytest

from app import db, links, ontology, propagate


# --- unit level: the fragility resolution itself -------------------------

def test_known_structures_pass_through():
    for s in ("bridge", "culvert", "ford", "causeway"):
        eff, assumed = ontology.resolve_structure(s)
        assert eff == s and assumed is False


def test_unknown_structure_assumes_most_fragile():
    for bad in (None, "", "   ", "unknown", "trestle", "footbridge"):
        eff, assumed = ontology.resolve_structure(bad)
        assert eff == ontology.UNKNOWN_STRUCTURE_ASSUMPTION
        assert assumed is True


def test_assumption_is_the_weakest_structure_in_the_table():
    """The assumed structure must be at least as fragile as every known one,
    at every severity - otherwise 'conservative' is a lie."""
    assumed = ontology.UNKNOWN_STRUCTURE_ASSUMPTION
    order = ontology.STATE_ORDER
    for sev in ontology.SEVERITIES:
        a_state = ontology.bridge_state(assumed, "riverine_flood", sev)
        for known in ontology.KNOWN_STRUCTURES:
            k_state = ontology.bridge_state(known, "riverine_flood", sev)
            assert order.index(a_state) >= order.index(k_state), (
                f"at {sev}: assumed {assumed}->{a_state} is less fragile "
                f"than {known}->{k_state}")


def test_unclassified_crossing_never_returns_OK_under_flood():
    for sev in ontology.SEVERITIES:
        assert ontology.bridge_state(None, "riverine_flood", sev) != "OK"


def test_unclassified_blocks_at_alert_and_emergency():
    """The states that actually sever a road."""
    for sev in ("alert", "emergency"):
        st = ontology.bridge_state(None, "riverine_flood", sev)
        assert st in ontology.BLOCKING_BRIDGE_STATES


def test_engineered_bridge_still_survives_a_watch():
    # the fix must not make everything fragile - a known bridge at watch is OK.
    assert ontology.bridge_state("bridge", "riverine_flood", "watch") == "OK"


def test_unmodelled_hazard_still_returns_OK():
    # a table miss on HAZARD KIND is legitimately OK (that hazard doesn't act here);
    # only a miss on STRUCTURE is the dangerous one.
    assert ontology.bridge_state("ford", "locust_swarm", "emergency") == "OK"


def test_explained_reports_assumption():
    st, eff, assumed = ontology.bridge_state_explained(None, "riverine_flood", "alert")
    assert assumed is True and eff == "ford" and st == "LIKELY_IMPASSABLE"
    st, eff, assumed = ontology.bridge_state_explained("bridge", "riverine_flood", "alert")
    assert assumed is False and eff == "bridge" and st == "AT_RISK"


# --- integration: through the real engine --------------------------------

@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    db.init()
    return tmp_path


def _corridor(c, structure):
    """South settlement -> road -> crossing -> road -> north clinic."""
    db.add_object(c, "R", "river_reach", "R", 0.0005, 34.0, {}, source="osm")
    db.add_object(c, "X", "bridge", "crossing X", 0.0005, 34.0,
                  {"structure": structure}, source="synth")
    for oid, g in (("rS", [[0.0, 34.0], [0.0004, 34.0]]),
                   ("rX", [[0.0004, 34.0], [0.0006, 34.0]]),
                   ("rN", [[0.0006, 34.0], [0.001, 34.0]])):
        db.add_object(c, oid, "road_segment", oid, g[0][0], g[0][1],
                      {"tags": {"highway": "tertiary"}, "geometry": g}, source="osm")
    db.add_object(c, "S1", "settlement", "S1", 0.0, 34.0, {}, source="osm")
    db.add_object(c, "H1", "clinic", "H1", 0.001, 34.0, {}, source="osm")


def _run_flood(sev="alert"):
    links.infer_crossing_links()
    links.infer_road_network()
    links.infer_access_and_serves()
    with db.conn() as c:
        c.execute("INSERT INTO hazards (kind, severity, target_id, source, "
                  "trigger_detail, created_utc, active) VALUES "
                  "('riverine_flood',?,'R','test','t',?,1)", (sev, db.now()))
        hid = c.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    propagate.run(hid)
    with db.conn() as c:
        rows = list(c.execute("SELECT * FROM impacts WHERE hazard_id=?", (hid,)))
    return {r["object_id"]: r["state"] for r in rows}, rows


def test_unclassified_crossing_isolates_village_at_alert(fresh_db):
    """THE regression: before D-027 this returned no impact at all."""
    with db.conn() as c:
        _corridor(c, structure=None)          # synth crossing, unclassified
    impacts, _ = _run_flood("alert")
    assert impacts.get("X") == "LIKELY_IMPASSABLE"
    assert impacts.get("rX") == "SEVERED"
    assert impacts.get("S1") == "ISOLATED"    # the village is warned


def test_engineered_bridge_does_not_isolate_at_alert(fresh_db):
    """Control: the fix is conservative, not indiscriminate. A known engineered
    bridge at alert is AT_RISK - not blocking - so nobody is isolated."""
    with db.conn() as c:
        _corridor(c, structure="bridge")
    impacts, _ = _run_flood("alert")
    assert impacts.get("X") == "AT_RISK"
    assert impacts.get("S1") != "ISOLATED"


def test_why_chain_declares_the_assumption(fresh_db):
    """Invariant 2: the impact must explain itself, including 'we assumed this'."""
    import json
    with db.conn() as c:
        _corridor(c, structure=None)
    _, rows = _run_flood("alert")
    chain = next(json.loads(r["why_chain_json"]) for r in rows if r["object_id"] == "X")
    assert any("assumed_structure" in str(step) for step in chain), chain


def test_known_structure_why_chain_has_no_assumption(fresh_db):
    import json
    with db.conn() as c:
        _corridor(c, structure="culvert")
    _, rows = _run_flood("alert")
    chain = next(json.loads(r["why_chain_json"]) for r in rows if r["object_id"] == "X")
    assert not any("assumed_structure" in str(step) for step in chain), chain
