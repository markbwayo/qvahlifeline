"""Invariant 4: no action without a matching impact; no impact state outside the
ontology. Plus the failure this layer can hide: an impact with no playbook row
fires nothing and, if unreported, looks exactly like an all-clear.

Self-contained: builds its own temp DB and its own hazard rows, so it does not
depend on conftest, hazards.py, or the real Manafwa graph.
"""
import csv
import os
import sqlite3

import pytest

from app import actions, db, propagate
from app.actions import ActionsError, PlaybookError
from app.ontology import (FRAGILITY, HAZARD_KINDS, OBJECT_TYPES, STATE_ORDER)

REAL_PLAYBOOK = os.path.join(os.path.dirname(__file__), "..", "data", "playbook.csv")


# --------------------------------------------------------------------------- fixtures

@pytest.fixture()
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db._schema_ready.clear()
    db.init()
    db.seed_demo_graph()
    yield
    db._schema_ready.clear()


def make_hazard(severity="emergency", kind="riverine_flood", target="R1", scope="reach"):
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO hazards (kind, severity, target_id, source, trigger_detail, "
            "created_utc, active, scope) VALUES (?,?,?,?,?,?,1,?)",
            (kind, severity, target, "test", "unit test", db.now(), scope))
        return cur.lastrowid


def write_playbook(tmp_path, rows, header=None):
    p = tmp_path / "pb.csv"
    with open(p, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header or actions.COLUMNS)
        w.writerows(rows)
    return str(p)


GOOD_ROW = ["settlement", "ISOLATED", "riverine_flood",
            "Alert the chief by radio.", "DDMC comms", "48"]


# --------------------------------------------------------------------------- the real playbook

def test_real_playbook_loads_and_is_deterministic():
    a = actions.load_playbook(REAL_PLAYBOOK)
    b = actions.load_playbook(REAL_PLAYBOOK)
    assert a and a == b
    for key, rows in a.items():
        assert rows == sorted(rows, key=lambda r: (r["lead_time_hrs"], r["owner_role"],
                                                   r["action_text"]))


def test_real_playbook_covers_every_state_the_engine_can_produce():
    """Every (object_type, state) the deterministic engine can emit for a
    riverine_flood must have at least one row. A missing row = a silent
    no-action next to a real impact."""
    required = set()
    # states the fragility table itself can assign
    for (otype, _struct, kind, _sev), state in FRAGILITY.items():
        if state != "OK":
            required.add((otype, state, kind))
    # states the propagation engine derives (09 propagation steps 3-4)
    k = "riverine_flood"
    required |= {("road_segment", "SEVERED", k),
                 ("settlement", "ISOLATED", k),
                 ("settlement", "REROUTED", k),
                 ("settlement", "FLOOD_EXPOSED", k),
                 ("clinic", "SERVICE_AT_RISK", k),
                 ("school", "SERVICE_AT_RISK", k),
                 ("water_point", "SERVICE_AT_RISK", k),
                 ("clinic", "FLOOD_EXPOSED", k),
                 ("school", "FLOOD_EXPOSED", k),
                 ("water_point", "FLOOD_EXPOSED", k)}
    missing = required - actions.covered_triples(actions.load_playbook(REAL_PLAYBOOK))
    assert not missing, f"playbook has no action for: {sorted(missing)}"


def test_isolated_actions_never_offer_a_road_alternate():
    """The 62 have no alternate; the second bridge fails under the same flood.
    An ISOLATED action that says 'detour' contradicts the engine."""
    book = actions.load_playbook(REAL_PLAYBOOK)
    for (_t, state, _k), rows in book.items():
        if state != "ISOLATED":
            continue
        for r in rows:
            low = r["action_text"].lower()
            for bad in actions.FORBIDDEN_IN_ISOLATED:
                assert bad not in low, f"{bad!r} in {r['action_text']!r}"


def test_every_real_row_is_owned_and_leads():
    for rows in actions.load_playbook(REAL_PLAYBOOK).values():
        for r in rows:
            assert r["owner_role"] and isinstance(r["lead_time_hrs"], int)
            assert r["lead_time_hrs"] >= 0


# --------------------------------------------------------------------------- loader guards

@pytest.mark.parametrize("row, needle", [
    (["footbridge", "ISOLATED", "riverine_flood", "x", "o", "1"], "object_type"),
    (["settlement", "MAROONED", "riverine_flood", "x", "o", "1"], "state"),
    (["settlement", "OK", "riverine_flood", "x", "o", "1"], "no action"),
    (["settlement", "ISOLATED", "river_flood", "x", "o", "1"], "hazard_kind"),
    (["settlement", "ISOLATED", "riverine_flood", "", "o", "1"], "action_text"),
    (["settlement", "ISOLATED", "riverine_flood", "x", "", "1"], "owner_role"),
    (["settlement", "ISOLATED", "riverine_flood", "x", "o", "soon"], "integer"),
    (["settlement", "ISOLATED", "riverine_flood", "x", "o", "-1"], "negative"),
    (["settlement", "ISOLATED", "riverine_flood", "Take the detour.", "o", "1"], "alternate"),
])
def test_loader_refuses_bad_rows(tmp_path, row, needle):
    with pytest.raises(PlaybookError) as e:
        actions.load_playbook(write_playbook(tmp_path, [row]))
    assert needle in str(e.value)


def test_loader_refuses_duplicate_rows(tmp_path):
    with pytest.raises(PlaybookError, match="duplicate"):
        actions.load_playbook(write_playbook(tmp_path, [GOOD_ROW, list(GOOD_ROW)]))


def test_loader_refuses_missing_column(tmp_path):
    with pytest.raises(PlaybookError, match="missing columns"):
        actions.load_playbook(write_playbook(
            tmp_path, [GOOD_ROW[:-1]], header=actions.COLUMNS[:-1]))


def test_loader_refuses_empty_or_absent_playbook(tmp_path):
    with pytest.raises(PlaybookError, match="empty"):
        actions.load_playbook(write_playbook(tmp_path, []))
    with pytest.raises(PlaybookError, match="not found"):
        actions.load_playbook(str(tmp_path / "nope.csv"))


def test_two_rows_may_share_a_triple(tmp_path):
    second = ["settlement", "ISOLATED", "riverine_flood",
              "Pre-position food.", "DDMC relief", "72"]
    book = actions.load_playbook(write_playbook(tmp_path, [second, GOOD_ROW]))
    rows = book[("settlement", "ISOLATED", "riverine_flood")]
    assert [r["lead_time_hrs"] for r in rows] == [48, 72]   # sorted, not file order


# --------------------------------------------------------------------------- invariant 4

def test_no_action_without_a_matching_impact(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    res = actions.fire_actions(hz, REAL_PLAYBOOK)
    assert res["actions"] > 0

    with db.conn() as c:
        impact_ids = {r["id"] for r in c.execute(
            "SELECT id FROM impacts WHERE hazard_id=?", (hz,))}
        orphans = [dict(r) for r in c.execute(
            "SELECT * FROM actions WHERE impact_id NOT IN "
            "(SELECT id FROM impacts)")]
    assert not orphans
    for a in actions.actions_for(hz):
        assert a["impact_id"] in impact_ids


def test_no_impact_state_outside_the_ontology(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    with db.conn() as c:
        states = {r["state"] for r in c.execute(
            "SELECT state FROM impacts WHERE hazard_id=?", (hz,))}
    assert states and states <= set(STATE_ORDER) - {"OK"}


def test_every_action_text_is_verbatim_from_the_playbook(fresh_db):
    """No invented text, no interpolation. Hard rule 1 in the action layer."""
    hz = make_hazard("emergency")
    propagate.run(hz)
    actions.fire_actions(hz, REAL_PLAYBOOK)

    book = actions.load_playbook(REAL_PLAYBOOK)
    types = {o["id"]: o["type"] for o in db.objects()}
    for a in actions.actions_for(hz):
        key = (types[a["object_id"]], a["state"], "riverine_flood")
        assert any(r["action_text"] == a["action_text"]
                   and r["owner_role"] == a["owner_role"]
                   and r["lead_time_hrs"] == a["lead_time_hrs"]
                   for r in book[key]), a


def test_action_count_equals_sum_of_matching_rows(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    res = actions.fire_actions(hz, REAL_PLAYBOOK)

    book = actions.load_playbook(REAL_PLAYBOOK)
    types = {o["id"]: o["type"] for o in db.objects()}
    with db.conn() as c:
        imps = [dict(r) for r in c.execute(
            "SELECT object_id, state FROM impacts WHERE hazard_id=?", (hz,))]
    expected = sum(len(book.get((types[i["object_id"]], i["state"], "riverine_flood"), []))
                   for i in imps)
    assert res["actions"] == expected == len(actions.actions_for(hz))


def test_no_impacts_means_no_actions(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    with db.conn() as c:
        c.execute("DELETE FROM actions")
        c.execute("DELETE FROM impacts WHERE hazard_id=?", (hz,))
    res = actions.fire_actions(hz, REAL_PLAYBOOK)
    assert res["impacts"] == 0 and res["actions"] == 0
    assert actions.actions_for(hz) == []


def test_fire_refuses_an_unknown_hazard(fresh_db):
    with pytest.raises(ActionsError, match="does not exist"):
        actions.fire_actions(999, REAL_PLAYBOOK)


def test_fire_refuses_an_impact_on_a_nonexistent_object(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    with db.conn() as c:
        c.execute("INSERT INTO impacts (hazard_id, object_id, state, why_chain_json, "
                  "created_utc) VALUES (?,?,?,?,?)", (hz, "GHOST", "ISOLATED", "[]", db.now()))
    with pytest.raises(ActionsError, match="unknown object"):
        actions.fire_actions(hz, REAL_PLAYBOOK)


def test_fire_refuses_a_state_outside_the_ontology(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    with db.conn() as c:
        c.execute("UPDATE impacts SET state='MAROONED' WHERE object_id='V1' "
                  "AND hazard_id=?", (hz,))
    with pytest.raises(ActionsError, match="invariant 4"):
        actions.fire_actions(hz, REAL_PLAYBOOK)


# ----------------------------------------------------- the silent no-action (the real risk)

def test_an_uncovered_impact_is_reported_never_dropped(fresh_db, tmp_path):
    """A playbook with no settlement/ISOLATED row must NOT quietly return
    'success, 0 actions for that village'. It must name the village."""
    thin = write_playbook(tmp_path, [
        ["bridge", "IMPASSABLE", "riverine_flood", "Close it.", "district engineer", "12"],
    ])
    hz = make_hazard("emergency")
    propagate.run(hz)
    res = actions.fire_actions(hz, thin)

    isolated = [u for u in res["uncovered"] if u["state"] == "ISOLATED"]
    assert {u["object_id"] for u in isolated} == {"V1", "V2"}
    assert res["actions"] == 1                       # only C1 IMPASSABLE matched
    assert all(a["object_id"] == "C1" for a in actions.actions_for(hz))


def test_full_playbook_leaves_nothing_uncovered_on_the_seed_graph(fresh_db):
    for sev in ("alert", "emergency"):
        hz = make_hazard(sev)
        propagate.run(hz)
        res = actions.fire_actions(hz, REAL_PLAYBOOK)
        assert res["uncovered"] == [], (sev, res["uncovered"])
        assert res["actions"] > 0


# --------------------------------------------------------------------------- invariants 1 & 5

def test_firing_twice_is_idempotent_and_identical(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    first = actions.fire_actions(hz, REAL_PLAYBOOK)
    snap1 = [(a["impact_id"], a["action_text"], a["owner_role"], a["lead_time_hrs"])
             for a in actions.actions_for(hz)]
    second = actions.fire_actions(hz, REAL_PLAYBOOK)
    snap2 = [(a["impact_id"], a["action_text"], a["owner_role"], a["lead_time_hrs"])
             for a in actions.actions_for(hz)]
    assert first["actions"] == second["actions"] == len(snap1) == len(snap2)
    assert snap1 == snap2


def test_clearing_the_hazard_clears_its_actions(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    assert actions.fire_actions(hz, REAL_PLAYBOOK)["actions"] > 0
    with db.conn() as c:
        db.clear_derived(c, hz)
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM actions").fetchone()["n"] == 0
        assert c.execute("SELECT COUNT(*) n FROM impacts WHERE hazard_id=?",
                         (hz,)).fetchone()["n"] == 0


def test_rerunning_propagation_then_actions_stays_consistent(fresh_db):
    """propagate.run() clears derived rows, so a stale action can never outlive
    the impact that justified it (invariant 5)."""
    hz = make_hazard("emergency")
    propagate.run(hz)
    actions.fire_actions(hz, REAL_PLAYBOOK)
    propagate.run(hz)                       # rebuilds impacts -> old action ids gone
    with db.conn() as c:
        assert c.execute("SELECT COUNT(*) n FROM actions").fetchone()["n"] == 0
    res = actions.fire_actions(hz, REAL_PLAYBOOK)
    assert res["actions"] > 0 and res["uncovered"] == []


# --------------------------------------------------------------------------- spine semantics

def test_isolated_village_gets_an_owned_action_with_a_lead_time(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    actions.fire_actions(hz, REAL_PLAYBOOK)
    v1 = [a for a in actions.actions_for(hz) if a["object_id"] == "V1"]
    assert v1 and all(a["state"] == "ISOLATED" for a in v1)
    assert all(a["owner_role"] and a["lead_time_hrs"] > 0 for a in v1)
    assert all(a["status"] == "PROPOSED" for a in v1)
    assert all(a["why_chain_json"] and a["why_chain_json"] != "[]" for a in v1)


def test_clinic_service_at_risk_fires_the_prepositioning_action(fresh_db):
    hz = make_hazard("emergency")
    propagate.run(hz)
    actions.fire_actions(hz, REAL_PLAYBOOK)
    h1 = [a for a in actions.actions_for(hz) if a["object_id"] == "H1"]
    assert h1 and all(a["state"] == "SERVICE_AT_RISK" for a in h1)
    assert any("Pre-position" in a["action_text"] for a in h1)
    assert all(a["owner_role"] == "DHO" for a in h1)


def test_generate_alias_still_serves_main_py(fresh_db):
    """app/main.py calls actions.generate(hid) at two endpoints. Removing the name
    would break the app on import, not on a test."""
    assert actions.generate is not actions.fire_actions      # a real wrapper
    hz = make_hazard("emergency")
    propagate.run(hz)
    res = actions.generate(hz)
    assert res["actions"] > 0 and res["uncovered"] == []
    assert len(actions.actions_for(hz)) == res["actions"]


def test_hazard_kinds_registry_is_the_only_source_of_truth():
    assert "riverine_flood" in HAZARD_KINDS
    for rows in actions.load_playbook(REAL_PLAYBOOK).values():
        for r in rows:
            assert r["hazard_kind"] in HAZARD_KINDS
            assert r["object_type"] in OBJECT_TYPES
