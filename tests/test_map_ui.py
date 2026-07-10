"""The read side, tested. Every bug this file guards against was a page that lied
by omission: a stale action, a green ISOLATED village, an empty action column, a
silent scan. The engine was right every time; the screen was not.

No HTTP client is used. `main.home()` is a plain function returning HTML, so the
page can be rendered and read in a test without pulling starlette's TestClient
(and httpx) onto the VPS.
"""
import inspect
import json

import pytest

from app import actions, db, hazards, main, propagate

PLAYBOOK = """object_type,state,hazard_kind,action_text,owner_role,lead_time_hrs
bridge,IMPASSABLE,riverine_flood,Close the crossing and stage barriers,district engineer,12
bridge,LIKELY_IMPASSABLE,riverine_flood,Deploy an inspection team,district engineer,24
road_segment,SEVERED,riverine_flood,Post a road-closed notice at the last junction,district engineer,12
settlement,ISOLATED,riverine_flood,Pre-position the community health kit village-side,DDMC health,36
settlement,ISOLATED,riverine_flood,Alert the chief by radio; no road alternate exists,DDMC comms,48
clinic,SERVICE_AT_RISK,riverine_flood,Pre-position the essential drug kit across the crossing,DHO,72
school,SERVICE_AT_RISK,riverine_flood,Confirm the shelter register and water store,DEO,48
"""
# NOTE: no `water_point SERVICE_AT_RISK` row. The seed graph produces that impact,
# so the fixture always carries one genuinely uncovered impact. Real data, not a mock.


@pytest.fixture()
def graph(tmp_path, monkeypatch):
    dbfile = str(tmp_path / "t.db")
    monkeypatch.setattr(db, "DB_PATH", dbfile)
    db._schema_ready.discard(dbfile)
    book = tmp_path / "playbook.csv"
    book.write_text(PLAYBOOK, encoding="utf-8")
    monkeypatch.setattr(actions, "PLAYBOOK_PATH", str(book))
    db.init()
    db.seed_demo_graph()
    yield dbfile
    db._schema_ready.discard(dbfile)


@pytest.fixture()
def fired(graph):
    hid = main.run_demo("emergency")
    return hid


# ------------------------------------------------------------------ the palette

def test_every_ontology_state_has_a_colour():
    from app.ontology import STATE_ORDER
    assert not [s for s in STATE_ORDER if s not in main.COLORS]


def test_no_impacted_state_wears_the_ok_colour():
    """`COLORS.get(state, OK_GREEN)` rendered an unknown state as a healthy asset.
    A missing colour must be impossible, not defaulted."""
    from app.ontology import STATE_ORDER
    green = main.COLORS["OK"]
    assert [s for s in STATE_ORDER if main.COLORS[s] == green] == ["OK"]


# -------------------------------------------------------------------- labelling

def test_nameless_crossing_is_labelled_by_object_id():
    assert main.label("w747829218", None) == "w747829218"
    assert main.label("w747829218", "  ") == "w747829218"
    assert "unnamed" not in main.label("w747829218", None)


def test_named_crossing_keeps_its_name():
    assert main.label("w128611448", "Manafwa Bridge (B112 town crossing)") \
        == "Manafwa Bridge (B112 town crossing)"


# ------------------------------------------------------- one hazard, never blended

def test_impact_map_is_scoped_to_one_hazard(fired):
    """852 action rows from five hazards rendered on one page. The join had no
    hazard filter at all."""
    with db.conn() as c:
        c.execute("INSERT INTO impacts (hazard_id, object_id, state, why_chain_json, "
                  "created_utc) VALUES (?,?,?,?,?)",
                  (999, "V1", "REROUTED", json.dumps(["stale"]), db.now()))
        mine = main.impact_map(c, fired)
        other = main.impact_map(c, 999)
    assert mine["V1"][0] == "ISOLATED"
    assert other["V1"][0] == "REROUTED"


def test_page_never_shows_an_action_from_another_hazard(fired):
    with db.conn() as c:
        c.execute("INSERT INTO impacts (hazard_id, object_id, state, why_chain_json, "
                  "created_utc) VALUES (?,?,?,?,?)",
                  (999, "V1", "ISOLATED", json.dumps(["stale"]), db.now()))
        iid = c.execute("SELECT id FROM impacts WHERE hazard_id=999").fetchone()["id"]
        c.execute("INSERT INTO actions (impact_id, action_text, owner_role, "
                  "lead_time_hrs, status) VALUES (?,?,?,?,?)",
                  (iid, "STALE-ACTION-FROM-A-CLEARED-HAZARD", "nobody", 1, "PROPOSED"))
    assert "STALE-ACTION-FROM-A-CLEARED-HAZARD" not in main.home()


def test_two_active_hazards_are_declared_not_blended(graph):
    hazards.demo_flood_river("alert")
    hazards.demo_flood_river("emergency")
    html = main.home()
    assert "HAZARDS ARE ACTIVE" in html


# ------------------------------------------------------- consequence, not urgency

def test_actions_are_ordered_by_consequence(fired):
    """B1 is LIKELY_IMPASSABLE with lead 24 h and isolates nobody. The school
    (48 h) and clinic (72 h) each lost two villages. Sorted by lead time, B1
    prints above both. Sorted by consequence, it prints below them."""
    html = main.home()
    b1 = html.index("Nakoko concrete bridge")
    school = html.index("Nakoko Primary")
    clinic = html.index("St. Marks HC III")
    assert school < b1 and clinic < b1


def test_the_worst_consequence_prints_first(fired):
    rows = actions.actions_for(fired)
    assert rows[0]["consequence"] == max(r["consequence"] for r in rows)
    html = main.home()
    assert html.index("Nakoko culvert crossing") < html.index("Bumasata village")


def test_precautionary_is_explained_and_never_hidden(fired):
    html = main.home()
    assert "Nakoko concrete bridge" in html          # zero dependents, still fires
    assert "precautionary" in html


# ------------------------------------------------------------ coverage (D-044)

def test_uncovered_impact_is_named_on_the_page(fired):
    """The seed graph makes a water_point SERVICE_AT_RISK; the playbook has no
    row for it. A red asset with an empty action column must say why."""
    cov = main.coverage(fired)
    assert [u["object_id"] for u in cov["uncovered"]] == ["W1"]
    html = main.home()
    assert "UNCOVERED" in html
    assert "Trading-centre borehole" in html


def test_an_impact_whose_playbook_row_exists_but_fired_nothing_is_a_bug(fired):
    with db.conn() as c:
        c.execute("DELETE FROM actions WHERE impact_id IN "
                  "(SELECT id FROM impacts WHERE hazard_id=? AND object_id='C1')",
                  (fired,))
    cov = main.coverage(fired)
    assert [u["object_id"] for u in cov["unfired"]] == ["C1"]
    assert "BUG" in main.home()


def test_coverage_panel_renders_even_when_nothing_is_uncovered(fired):
    """Absence of an uncovered list must not be inferable from absence of a panel."""
    with db.conn() as c:
        c.execute("DELETE FROM impacts WHERE hazard_id=? AND object_id='W1'", (fired,))
    html = main.home()
    assert "impacts carry at least one" in html
    assert "Every impact of this hazard carries at least one action" in html


def test_a_broken_playbook_is_reported_not_assumed_clean(fired, monkeypatch):
    monkeypatch.setattr(actions, "PLAYBOOK_PATH", "/nonexistent/playbook.csv")
    cov = main.coverage(fired)
    assert cov["error"]
    assert "PLAYBOOK WILL NOT LOAD" in main.home()


# ---------------------------------------------------------- the scan banner (D-047)

def test_a_scan_that_never_ran_is_not_an_all_clear(graph):
    assert main.load_scan() is None
    html = main.scan_html(None)
    assert "has not been run" in html and "not an all-clear" in html


def test_a_disabled_scan_says_disabled(graph, monkeypatch):
    monkeypatch.delenv("USE_LIVE", raising=False)
    res = hazards.scan_live()
    main.save_scan(res)
    html = main.scan_html(main.load_scan())
    assert "LIVE SCAN DISABLED" in html
    assert "quiet" not in html.lower()


def test_a_dead_feed_renders_red_and_names_the_error(graph):
    main.save_scan({"status": "FEED FAILURE", "error": "HazardFeedError: GloFAS fetch failed"})
    html = main.scan_html(main.load_scan())
    assert "GLOFAS FEED FAILURE" in html
    assert "not an all-clear" in html
    assert "GloFAS fetch failed" in html


def test_a_quiet_river_reports_its_numbers(graph):
    main.save_scan({"status": "ok", "checked": 1, "triggered": [], "unverified": 32,
                    "quiet": [{"reach_id": "w188321163", "peak": 6.19,
                               "peak_date": "2026-07-10", "watch_threshold": 12.37}]})
    html = main.scan_html(main.load_scan())
    assert "river quiet" in html and "6.19" in html and "12.37" in html


def test_scan_survives_a_raising_feed(graph, monkeypatch):
    """scan_live() must raise. The page must not 500 - it must show the raise."""
    def boom(*a, **k):
        raise hazards.HazardFeedError("the API was down")
    monkeypatch.setattr(hazards, "scan_live", boom)
    main.scan()
    assert main.load_scan()["status"] == "FEED FAILURE"
    assert "the API was down" in main.home()


# --------------------------------------------------------------- the why-chain

def test_assumed_structure_is_rendered_never_hidden():
    """D-027: the engine says out loud that it guessed a structure. So must the UI."""
    html = main.chain_html(
        ["hazard:riverine_flood/emergency", "w188321163", "synth:0.95_34.27",
         "assumed_structure:ford(unclassified)"],
        {"w188321163": "Manafwa"})
    assert "assumed_structure:ford(unclassified)" in html
    assert "ch-a" in html


def test_alternate_route_names_its_roads():
    html = main.chain_html(["alternate_via:RD4A>RD4B"],
                           {"RD4A": "Bridge road A", "RD4B": "Bridge road B"})
    assert "Bridge road A" in html and "Bridge road B" in html


def test_why_chain_labels_a_nameless_crossing_by_id():
    html = main.chain_html(["w747829218"], {})
    assert "w747829218" in html and "unnamed" not in html


# -------------------------------------------------------- the demo runs at river scope

def test_demo_endpoints_use_river_scope(graph):
    """D-036. At reach scope the pilot graph reports 0 ISOLATED / 43 REROUTED:
    villages detouring over crossings the same flood closes."""
    hid = main.run_demo("emergency")
    with db.conn() as c:
        row = c.execute("SELECT scope, severity FROM hazards WHERE id=?", (hid,)).fetchone()
    assert row["scope"] == "river"
    assert row["severity"] == "emergency"


def test_alert_endpoint_also_runs_at_river_scope(graph):
    hid = main.run_demo("alert")
    with db.conn() as c:
        row = c.execute("SELECT scope, severity FROM hazards WHERE id=?", (hid,)).fetchone()
    assert row["scope"] == "river" and row["severity"] == "alert"


def test_run_demo_clears_the_previous_hazard(graph):
    first = main.run_demo("alert")
    second = main.run_demo("emergency")
    with db.conn() as c:
        actives = [h["id"] for h in main.active_hazards(c)]
    assert actives == [second] and first not in actives


# ------------------------------------------------------------------- the page itself

def test_page_shows_both_versions_and_the_required_attribution(fired):
    html = main.home()
    assert "ontology v0.3" in html
    assert actions.PLAYBOOK_VERSION.split(" (")[0] in html
    assert "OpenStreetMap contributors (ODbL)" in html
    assert "GloFAS via the" in html


def test_page_does_not_attribute_data_it_never_ingested(fired):
    """WorldPop is not ingested (D-040); SRTM feeds no link. Attributing unused
    data is the same species of dishonesty as failing to attribute used data."""
    html = main.home()
    assert "WorldPop" not in html and "SRTM" not in html


def test_importing_main_does_not_touch_the_database():
    """`db.init()` and `seed_demo_graph()` used to run at import. A test could not
    then point db at a temp file, and neither could a script or a migration."""
    src = inspect.getsource(main)
    top_level = [ln for ln in src.splitlines()
                 if ln and not ln[0].isspace()
                 and ("db.init()" in ln or "seed_demo_graph" in ln)]
    assert top_level == [], f"module-level database call: {top_level}"
    assert "db.init()" in inspect.getsource(main._lifespan)


def test_flooded_reaches_come_from_the_engine(fired):
    objs = {o["id"]: o for o in db.objects()}
    with db.conn() as c:
        hz = main.active_hazards(c)[0]
    assert main.flooded_set(objs, hz) == propagate.flooded_reaches(
        objs, hz["target_id"], hz["scope"])
