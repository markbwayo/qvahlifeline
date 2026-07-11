"""The message panel (Phase 2 item 4c) and the approvals store.

The load-bearing properties, each a test:

  * `home()` makes ZERO provider calls. A live translation is 4-6 s of generation
    (D-060); 62 villages in a page render is five minutes of blocking. The panel
    reads `ai_edge.cached_draft` (read-only, no network) and never `ai_edge()`.
  * The Lumasaba gap and the bare-id `needs_name` gap are SHOWN, by name, never
    swallowed (invariant 6). Silence and safety must not render alike.
  * `edge unusable` is REJECTED, never DRAFT (D-056): a page that prints a failed
    draft as a proposal has laundered a failure into an approval candidate.
  * An approval is bound to the exact Swahili BYTES (D-060 wall between what a model
    proposed and what a human signed). A re-translation under a changed prompt is
    not silently still-approved.
"""
import json
import os

import pytest

from app import ai_edge, approvals, db, main, messages


@pytest.fixture()
def graph(tmp_path, monkeypatch):
    dbfile = str(tmp_path / "t.db")
    monkeypatch.setattr(db, "DB_PATH", dbfile)
    db._schema_ready.discard(dbfile)
    approvals._ensured.discard(dbfile)
    db.init()

    csv = tmp_path / "messages.csv"
    csv.write_text(
        "object_type,state,hazard_kind,lang,template\n"
        "settlement,ISOLATED,riverine_flood,en,{settlement} is cut off from "
        "{facility} by {hazard}. The road crosses {crossing}. It is the only road.\n"
        "bridge,IMPASSABLE,riverine_flood,en,{crossing} is impassable in this "
        "{hazard}. Do not try to cross.\n", encoding="utf-8")
    monkeypatch.setattr(messages, "MESSAGES_PATH", str(csv))

    with db.conn() as c:
        objs = [
            ("R1", "river_reach", "Manafwa reach", 0.94, 34.28, {}),
            ("w128611448", "bridge", "Manafwa Bridge (B112 town crossing)",
             0.94, 34.28, {"structure": "bridge"}),
            ("w747829218", "bridge", "", 0.95, 34.29, {"structure": "bridge"}),
            ("Vill_A", "settlement", "Bumayeku B", 0.93, 34.27, {}),
            ("Vill_B", "settlement", "Nasitsapi", 0.96, 34.30, {}),
            ("Clin", "clinic", "Namuembi Medical Centre", 0.95, 34.28, {}),
        ]
        for oid, t, n, la, lo, p in objs:
            c.execute(
                "INSERT INTO objects (id, type, name, lat, lon, props_json, "
                "source, created_utc) VALUES (?,?,?,?,?,?,?,?)",
                (oid, t, n, la, lo, json.dumps(p), "osm", db.now()))
        c.execute("INSERT INTO hazards(kind,severity,scope,target_id,source,"
                  "trigger_detail,active) VALUES(?,?,?,?,?,?,1)",
                  ("riverine_flood", "emergency", "river", "R1", "GloFAS", "Q10"))
        hid = c.execute("SELECT id FROM hazards").fetchone()["id"]
        rows = [
            ("w128611448", "IMPASSABLE",
             ["hazard:riverine_flood/emergency", "R1", "w128611448"]),
            ("w747829218", "IMPASSABLE",
             ["hazard:riverine_flood/emergency", "R1", "w747829218"]),
            ("Vill_A", "ISOLATED",
             ["hazard:riverine_flood/emergency", "R1", "w128611448", "Vill_A", "Clin"]),
            ("Vill_B", "ISOLATED",
             ["hazard:riverine_flood/emergency", "R1", "w747829218", "Vill_B", "Clin"]),
        ]
        for oid, st, ch in rows:
            c.execute("INSERT INTO impacts(hazard_id,object_id,state,why_chain_json) "
                      "VALUES(?,?,?,?)", (hid, oid, st, json.dumps(ch)))
        for oid in ("Vill_A", "Vill_B", "w128611448", "w747829218"):
            iid = c.execute("SELECT id FROM impacts WHERE object_id=? AND hazard_id=?",
                            (oid, hid)).fetchone()["id"]
            c.execute("INSERT INTO actions(impact_id,action_text,owner_role,"
                      "lead_time_hrs) VALUES(?,?,?,?)",
                      (iid, "Alert the chief by radio.", "DDMC comms", 48))

    monkeypatch.setenv("AI_EDGE_LIVE", "1")
    monkeypatch.setenv("GEMINI_API_KEY", "AQ.test")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-test")
    monkeypatch.setattr(ai_edge, "_pause", lambda: None)
    yield {"hid": hid, "monkeypatch": monkeypatch}
    db._schema_ready.discard(dbfile)
    approvals._ensured.discard(dbfile)


def _impact(oid):
    with db.conn() as c:
        return c.execute("SELECT id FROM impacts WHERE object_id=?", (oid,)).fetchone()["id"]


def _no_provider(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("the page render reached the provider")
    monkeypatch.setattr(ai_edge, "_call", boom)


# ------------------------------------------- the page makes no provider call

def test_home_renders_broadcasts_without_touching_the_provider(graph):
    _no_provider(graph["monkeypatch"])
    html = main.home()
    assert "Broadcast messages" in html
    assert "Bumayeku B is cut off from Namuembi Medical Centre" in html


def test_broadcast_panel_makes_no_provider_call(graph):
    _no_provider(graph["monkeypatch"])
    bp = main.broadcast_panel(graph["hid"])
    assert bp["en_count"] == 4          # 2 villages + 2 crossings
    assert len(bp["villages"]) == 2 and len(bp["crossings"]) == 2


# --------------------------------------------------- gaps are shown, by name

def test_the_lumasaba_gap_is_shown_by_village_name(graph):
    _no_provider(graph["monkeypatch"])
    html = main.home()
    assert "Lumasaba not yet written" in html
    assert "Bumayeku B" in html and "Nasitsapi" in html


def test_a_bare_id_crossing_is_flagged_as_an_operator_task(graph):
    _no_provider(graph["monkeypatch"])
    bp = main.broadcast_panel(graph["hid"])
    assert any(n["crossing_id"] == "w747829218" for n in bp["needs_name"])
    html = main.home()
    assert "an operator task, not a code fix" in html
    assert "w747829218" in html


def test_a_named_crossing_is_not_flagged(graph):
    _no_provider(graph["monkeypatch"])
    bp = main.broadcast_panel(graph["hid"])
    assert all(n["crossing_id"] != "w128611448" for n in bp["needs_name"])


def test_impacts_correctly_not_broadcast_are_counted(graph):
    _no_provider(graph["monkeypatch"])
    bp = main.broadcast_panel(graph["hid"])
    assert bp["not_broadcast"] == 0     # this fixture has no SEVERED / SERVICE_AT_RISK


# ------------------------------------------------------ the draft route

def test_the_draft_route_calls_the_provider_exactly_once_then_caches(graph):
    calls = []
    graph["monkeypatch"].setattr(
        ai_edge, "_call", lambda *a: calls.append(1) or 'Bumayeku B imekatwa kutoka Namuembi Medical Centre kwa mafuriko. Barabara inavuka Manafwa Bridge. Ndiyo barabara pekee.')
    iid = _impact("Vill_A")
    main.draft(iid)
    main.draft(iid)                     # second click: cache, no new call
    assert len(calls) == 1


def test_a_drafted_message_shows_a_draft_badge_and_an_approve_button(graph):
    graph["monkeypatch"].setattr(ai_edge, "_call", lambda *a: 'Bumayeku B imekatwa kutoka Namuembi Medical Centre kwa mafuriko. Barabara inavuka Manafwa Bridge. Ndiyo barabara pekee.')
    iid = _impact("Vill_A")
    main.draft(iid)
    _no_provider(graph["monkeypatch"])
    html = main.home()
    assert "DRAFT — not approved" in html
    assert f"/approve/{iid}" in html


def test_a_village_with_no_swahili_shows_a_draft_button_not_a_badge(graph):
    _no_provider(graph["monkeypatch"])
    html = main.home()
    assert "Draft Swahili" in html
    assert "APPROVED" not in html


def test_an_edge_failure_in_the_draft_route_never_raises(graph):
    import urllib.error
    graph["monkeypatch"].setattr(
        ai_edge, "_call",
        lambda *a: (_ for _ in ()).throw(urllib.error.URLError("dead")))
    iid = _impact("Vill_A")
    main.draft(iid)                     # must not raise
    _no_provider(graph["monkeypatch"])
    html = main.home()
    assert "no Swahili draft yet" in html   # the failure cached nothing


def test_a_rejected_draft_is_never_shown_as_a_draft(graph):
    """D-056. `edge unusable` returns the rejected text; the panel must render it
    as absent, never as a DRAFT a human could approve."""
    graph["monkeypatch"].setattr(ai_edge, "_call", lambda *a: "")   # empty -> unusable
    iid = _impact("Vill_A")
    main.draft(iid)
    _no_provider(graph["monkeypatch"])
    bp = main.broadcast_panel(graph["hid"])
    row = next(r for r in bp["villages"] if r["impact_id"] == iid)
    assert row["sw"] is None            # not the empty string, not shown as DRAFT


# ------------------------------------------------- approval is over the bytes

def test_approve_records_a_signature_over_the_current_draft(graph):
    graph["monkeypatch"].setattr(ai_edge, "_call", lambda *a: 'Bumayeku B imekatwa kutoka Namuembi Medical Centre kwa mafuriko. Barabara inavuka Manafwa Bridge. Ndiyo barabara pekee.')
    iid = _impact("Vill_A")
    main.draft(iid)
    main.approve(iid)
    assert approvals.is_approved(iid, "sw", 'Bumayeku B imekatwa kutoka Namuembi Medical Centre kwa mafuriko. Barabara inavuka Manafwa Bridge. Ndiyo barabara pekee.')


def test_an_approved_message_shows_approved_not_the_button(graph):
    graph["monkeypatch"].setattr(ai_edge, "_call", lambda *a: 'Bumayeku B imekatwa kutoka Namuembi Medical Centre kwa mafuriko. Barabara inavuka Manafwa Bridge. Ndiyo barabara pekee.')
    iid = _impact("Vill_A")
    main.draft(iid)
    main.approve(iid)
    _no_provider(graph["monkeypatch"])
    html = main.home()
    assert "APPROVED</span>" in html


def test_an_approval_does_not_carry_to_a_retranslation(graph):
    """The wall between proposed and signed (D-060). A draft re-made under a changed
    system prompt has different bytes and a different hash; the old signature does
    not bless it."""
    graph["monkeypatch"].setattr(ai_edge, "_call", lambda *a: 'Bumayeku B imekatwa kutoka Namuembi Medical Centre kwa mafuriko. Barabara inavuka Manafwa Bridge. Ndiyo barabara pekee.')
    iid = _impact("Vill_A")
    main.draft(iid)
    main.approve(iid)
    assert approvals.is_approved(iid, "sw", 'Bumayeku B imekatwa kutoka Namuembi Medical Centre kwa mafuriko. Barabara inavuka Manafwa Bridge. Ndiyo barabara pekee.')
    assert not approvals.is_approved(iid, "sw", "A different translation.")


def test_approving_with_no_cached_draft_signs_nothing(graph):
    _no_provider(graph["monkeypatch"])   # no draft was ever made
    iid = _impact("Vill_A")
    main.approve(iid)                    # must not raise, must not sign
    assert approvals.approved_for(graph["hid"], "sw") == {}


def test_approval_is_idempotent(graph):
    graph["monkeypatch"].setattr(ai_edge, "_call", lambda *a: 'Bumayeku B imekatwa kutoka Namuembi Medical Centre kwa mafuriko. Barabara inavuka Manafwa Bridge. Ndiyo barabara pekee.')
    iid = _impact("Vill_A")
    main.draft(iid)
    main.approve(iid)
    main.approve(iid)
    with db.conn() as c:
        n = c.execute("SELECT COUNT(*) FROM approvals WHERE impact_id=?", (iid,)).fetchone()[0]
    assert n == 1


# ------------------------------------------------------- the panel never decides

def test_the_approvals_table_holds_no_english_and_no_impact_state(graph):
    """Approval records a human's signature on Swahili bytes. It is not a place a
    state or an English string could leak into and become authority."""
    import inspect
    src = inspect.getsource(approvals)
    assert "impacts" in src              # it JOINs impacts to scope by hazard, read-only
    # but it never writes a state or an object's English name
    assert "state" not in src.lower().split("def approved_for")[0].replace(
        "text_hash", "")


def test_broadcast_panel_returns_none_with_no_hazard(graph):
    with db.conn() as c:
        c.execute("UPDATE hazards SET active=0")
    assert main.broadcast_panel(None) is None


# ---- controls that must be able to fail (found green in Session 24 review)

def test_home_provider_trap_is_not_swallowed_by_the_error_guard(graph):
    """NC-P1 stayed green because home()'s try/except around the panel caught the
    trap's AssertionError. Probe broadcast_panel directly, where nothing catches it,
    so 'home calls the provider' actually reddens."""
    calls = []
    graph["monkeypatch"].setattr(ai_edge, "_call", lambda *a: calls.append(1) or "x")
    # a warm-cache render must still make no call; prove it on the uncaught path
    main.broadcast_panel(graph["hid"])
    assert calls == []


def test_a_cached_unusable_row_is_never_shown_as_the_swahili(graph):
    """NC-P2. Put a non-DRAFT row in the cache under the real key and prove the
    panel treats it as absent, not as a translation a human could approve."""
    m = messages.render(_impact("Vill_A"), "en")
    ck = ai_edge._cache_key(m["text"], "sw", "gemini-test")
    ai_edge._cache_put(ck, {"status": "edge unusable", "draft": "garbage out",
                            "approved": False})
    _no_provider(graph["monkeypatch"])
    bp = main.broadcast_panel(graph["hid"])
    row = next(r for r in bp["villages"] if r["object_id"] == "Vill_A")
    assert row["sw"] is None
