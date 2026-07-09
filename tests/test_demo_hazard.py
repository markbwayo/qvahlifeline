"""tests/test_demo_hazard.py - merge gate for D-028/D-029.

Two safety properties:
  1. A hazard on a nonexistent (or wrong-typed) target is REFUSED. Such a hazard
     propagates to nothing - a silent all-clear.
  2. The demo hazard resolves to the REAL Manafwa reach when the real graph is
     loaded, and falls back to the seed reach otherwise. Never guessed.

Plus a severity check that documents, in code, why the demo needs 'emergency':
engineered bridges are non-blocking at 'alert'.
"""
import os

import pytest

from app import db, hazards, ontology


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("DEMO_REACH_ID", raising=False)
    db.init()
    return tmp_path


def _reach(c, oid):
    db.add_object(c, oid, "river_reach", oid, 0.94, 34.28, {}, source="osm")


# --- target validation (D-028) -------------------------------------------

def test_refuses_nonexistent_target(fresh_db):
    with db.conn() as c:
        _reach(c, "w188321163")
    with pytest.raises(ValueError, match="not an object in the graph"):
        hazards.create_hazard("riverine_flood", "alert", "w_TYPO",
                              "DEMO", "detail")


def test_refuses_wrong_typed_target(fresh_db):
    with db.conn() as c:
        db.add_object(c, "b1", "bridge", "b1", 0.94, 34.28,
                      {"structure": "bridge"}, source="osm")
    with pytest.raises(ValueError, match="not a river_reach"):
        hazards.create_hazard("riverine_flood", "alert", "b1", "DEMO", "detail")


def test_refuses_bad_severity(fresh_db):
    with db.conn() as c:
        _reach(c, "w188321163")
    with pytest.raises(ValueError, match="severity"):
        hazards.create_hazard("riverine_flood", "catastrophic", "w188321163",
                              "DEMO", "detail")


def test_valid_target_is_accepted(fresh_db):
    with db.conn() as c:
        _reach(c, "w188321163")
    hid = hazards.create_hazard("riverine_flood", "emergency", "w188321163",
                                "DEMO", "detail")
    assert isinstance(hid, int) and hid > 0


# --- demo reach resolution (D-029) ---------------------------------------

def test_resolves_real_reach_when_real_graph_loaded(fresh_db):
    with db.conn() as c:
        _reach(c, "R1")                       # seed reach also present
        _reach(c, "w188321163")               # real reach wins
    assert hazards.resolve_demo_reach() == "w188321163"


def test_falls_back_to_seed_reach(fresh_db):
    with db.conn() as c:
        _reach(c, "R1")
    assert hazards.resolve_demo_reach() == "R1"


def test_raises_when_no_reach_at_all(fresh_db):
    with pytest.raises(ValueError, match="no demo river_reach"):
        hazards.resolve_demo_reach()


def test_env_override(fresh_db, monkeypatch):
    with db.conn() as c:
        _reach(c, "w188321163")
        _reach(c, "wOTHER")
    monkeypatch.setenv("DEMO_REACH_ID", "wOTHER")
    assert hazards.resolve_demo_reach() == "wOTHER"


def test_env_override_with_bad_id_raises(fresh_db, monkeypatch):
    with db.conn() as c:
        _reach(c, "w188321163")
    monkeypatch.setenv("DEMO_REACH_ID", "wNOPE")
    with pytest.raises(ValueError, match="not an object in the graph"):
        hazards.resolve_demo_reach()


def test_demo_flood_targets_the_real_reach(fresh_db):
    with db.conn() as c:
        _reach(c, "R1")
        _reach(c, "w188321163")
    hid = hazards.demo_flood("emergency")
    with db.conn() as c:
        row = c.execute("SELECT * FROM hazards WHERE id=?", (hid,)).fetchone()
    assert row["target_id"] == "w188321163"
    assert row["severity"] == "emergency"
    assert row["kind"] == "riverine_flood"


def test_demo_flood_explicit_reach_id_validated(fresh_db):
    with db.conn() as c:
        _reach(c, "w188321163")
    with pytest.raises(ValueError):
        hazards.demo_flood("alert", reach_id="w_NOT_HERE")


def test_clear_hazards_deactivates(fresh_db):
    with db.conn() as c:
        _reach(c, "w188321163")
    hazards.demo_flood("emergency")
    hazards.clear_hazards()
    with db.conn() as c:
        assert all(r["active"] == 0 for r in c.execute("SELECT * FROM hazards"))


# --- why the demo needs 'emergency' (documents D-029 in code) -------------

def test_engineered_bridge_is_nonblocking_at_alert():
    st = ontology.bridge_state("bridge", "riverine_flood", "alert")
    assert st not in ontology.BLOCKING_BRIDGE_STATES     # -> no isolation at alert


def test_engineered_bridge_blocks_at_emergency():
    st = ontology.bridge_state("bridge", "riverine_flood", "emergency")
    assert st in ontology.BLOCKING_BRIDGE_STATES         # -> the demo works here
