r"""tests/test_hazard_scope.py - merge gate for D-036 (hazard scope).

A GloFAS discharge spike raises the connected river channel, not one OSM way.
Flooding a single reach let settlements detour over crossings that would, in
reality, also be under water (measured on the real graph: scope=reach gave 0
ISOLATED / 43 REROUTED; scope=river gave 62 ISOLATED / 0 REROUTED).

scope='river' floods the trigger reach plus every reach of the SAME `waterway`
value vertex-connected to it. Streams are a different hazard (04.D) and are
excluded. A disconnected river is a different watercourse and is excluded.
"""
import pytest

from app import db, hazards, propagate


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.delenv("DEMO_REACH_ID", raising=False)
    db._schema_ready.discard(str(tmp_path / "test.db"))
    db.init()
    return tmp_path


def _reach(c, oid, geometry, waterway="river"):
    db.add_object(c, oid, "river_reach", oid, geometry[0][0], geometry[0][1],
                  {"tags": {"waterway": waterway}, "geometry": geometry}, source="osm")


def _objs():
    return {o["id"]: o for o in db.objects()}


# --- schema migration ------------------------------------------------------

def test_scope_column_exists_after_init(fresh_db):
    with db.conn() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(hazards)")}
    assert "scope" in cols


def test_conn_migrates_without_an_explicit_init_call(tmp_path, monkeypatch):
    """The live failure (D-037): the real DB predates the `scope` column, and an
    ad-hoc script that imports db and calls create_hazard() never runs init().
    conn() must bring the schema current by itself."""
    path = str(tmp_path / "legacy.db")
    monkeypatch.setattr(db, "DB_PATH", path)
    db._schema_ready.discard(path)
    import sqlite3
    raw = sqlite3.connect(path)               # an OLD database, no scope column
    raw.executescript(
        "CREATE TABLE objects (id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT,"
        " lat REAL, lon REAL, props_json TEXT DEFAULT '{}', source TEXT DEFAULT 'seed',"
        " created_utc TEXT);"
        "CREATE TABLE hazards (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT,"
        " severity TEXT, target_id TEXT, source TEXT, trigger_detail TEXT,"
        " created_utc TEXT, active INTEGER DEFAULT 1);")
    raw.commit(); raw.close()

    # NO db.init() here - exactly what the failing script did.
    with db.conn() as c:
        _reach(c, "B", [[0.0, 34.0], [0.01, 34.0]])
    hid = hazards.create_hazard("riverine_flood", "alert", "B", "T", "d",
                                scope="river")
    with db.conn() as c:
        assert c.execute("SELECT scope FROM hazards WHERE id=?",
                         (hid,)).fetchone()["scope"] == "river"


def test_migration_is_idempotent_on_a_legacy_table(tmp_path, monkeypatch):
    """A legacy hazards table (no `scope`) is migrated, and migrating twice is safe."""
    import sqlite3
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)               # plant the OLD schema directly
    raw.executescript(
        "CREATE TABLE hazards (id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT,"
        " severity TEXT, target_id TEXT, source TEXT, trigger_detail TEXT,"
        " created_utc TEXT, active INTEGER DEFAULT 1);")
    raw.commit(); raw.close()

    monkeypatch.setattr(db, "DB_PATH", path)
    db._schema_ready.discard(path)
    db.init()
    with db.conn() as c:
        cols = {r["name"] for r in c.execute("PRAGMA table_info(hazards)")}
    assert "scope" in cols

    db._schema_ready.discard(path)
    db.init()                                  # second run must not fail
    with db.conn() as c:
        assert "scope" in {r["name"] for r in c.execute("PRAGMA table_info(hazards)")}


# --- scope resolution ------------------------------------------------------

@pytest.fixture
def river_db(fresh_db):
    r"""Mainstem: A -- B -- C   (B joins A and C at shared vertices)
        Tributary stream S touches B mid-way.
        Separate river X, unconnected (a different watercourse)."""
    with db.conn() as c:
        _reach(c, "A", [[0.00, 34.00], [0.01, 34.00]])
        _reach(c, "B", [[0.01, 34.00], [0.02, 34.00]])
        _reach(c, "C", [[0.02, 34.00], [0.03, 34.00]])
        _reach(c, "S", [[0.015, 34.00], [0.015, 34.01]], waterway="stream")  # touches B
        _reach(c, "X", [[0.50, 34.50], [0.51, 34.50]])                       # far river
    return fresh_db


def test_scope_reach_floods_only_the_target(river_db):
    assert propagate.flooded_reaches(_objs(), "B", "reach") == {"B"}


def test_scope_river_floods_the_connected_channel(river_db):
    assert propagate.flooded_reaches(_objs(), "B", "river") == {"A", "B", "C"}


def test_scope_river_excludes_streams(river_db):
    """Streams touch the mainstem but GloFAS does not resolve them (04.D)."""
    assert "S" not in propagate.flooded_reaches(_objs(), "B", "river")


def test_scope_river_excludes_a_disconnected_watercourse(river_db):
    assert "X" not in propagate.flooded_reaches(_objs(), "B", "river")


def test_scope_river_from_a_stream_floods_streams_not_rivers(river_db):
    """Symmetry: the rule groups by the target's own waterway value."""
    assert propagate.flooded_reaches(_objs(), "S", "river") == {"S"}


def test_reaches_joining_midway_are_connected(fresh_db):
    """Endpoint-only adjacency misses this; vertex adjacency catches it."""
    with db.conn() as c:
        _reach(c, "main", [[0.0, 34.0], [0.01, 34.0], [0.02, 34.0]])
        _reach(c, "join", [[0.01, 34.0], [0.01, 34.01]])   # meets main mid-way
    assert propagate.flooded_reaches(_objs(), "main", "river") == {"main", "join"}


def test_unknown_target_degrades_to_itself(fresh_db):
    assert propagate.flooded_reaches(_objs(), "nope", "river") == {"nope"}


# --- validation + end to end ----------------------------------------------

def test_create_hazard_rejects_bad_scope(river_db):
    with pytest.raises(ValueError, match="scope"):
        hazards.create_hazard("riverine_flood", "alert", "B", "T", "d", scope="planet")


def test_demo_flood_river_sets_scope(river_db):
    hid = hazards.demo_flood_river("emergency", reach_id="B")
    with db.conn() as c:
        row = c.execute("SELECT * FROM hazards WHERE id=?", (hid,)).fetchone()
    assert row["scope"] == "river" and row["severity"] == "emergency"


def test_default_demo_flood_stays_reach_scoped(river_db):
    hid = hazards.demo_flood("alert", reach_id="B")
    with db.conn() as c:
        assert c.execute("SELECT scope FROM hazards WHERE id=?",
                         (hid,)).fetchone()["scope"] == "reach"


@pytest.fixture
def two_crossing_db(fresh_db):
    r"""Village V on the south bank, clinic H north. Two crossings of the SAME
    river: the near bridge X1 (on reach A) and a detour bridge X2 (on reach C).
    Under scope=reach only X1 blocks -> V reroutes. Under scope=river both block
    -> V is ISOLATED. This is the real Manafwa result in miniature."""
    with db.conn() as c:
        _reach(c, "A", [[0.00, 34.00], [0.01, 34.00]])
        _reach(c, "C", [[0.01, 34.00], [0.02, 34.00]])       # same channel
        A = lambda oid, t, p=None: db.add_object(c, oid, t, oid, 0.0, 34.0,
                                                 p or {}, source="osm")
        L = lambda a, b, t: db.add_link(c, a, b, t, "test")
        A("X1", "bridge", {"structure": "ford"})             # blocks at emergency
        A("X2", "bridge", {"structure": "ford"})
        for r in ("rV", "rS", "rN", "rD1", "rD2"):
            A(r, "road_segment")
        A("V", "settlement"); A("H", "clinic")
        L("X1", "A", "crosses"); L("X2", "C", "crosses")
        L("rS", "X1", "carries")                             # sole carrier -> removed
        L("rD1", "X2", "carries")                            # sole carrier -> removed
        # V sits on its own spur, which reaches BOTH crossings
        L("rV", "rS", "connects")                            # short way  (3 hops)
        L("rS", "rN", "connects")
        L("rV", "rD1", "connects")                           # long detour (4 hops)
        L("rD1", "rD2", "connects"); L("rD2", "rN", "connects")
        L("V", "rV", "access_via"); L("H", "rN", "access_via")
        L("H", "V", "serves")
    return fresh_db


def _states(hid):
    propagate.run(hid)
    with db.conn() as c:
        return {r["object_id"]: r["state"]
                for r in c.execute("SELECT * FROM impacts WHERE hazard_id=?", (hid,))}


def test_reach_scope_leaves_the_detour_open(two_crossing_db):
    st = _states(hazards.create_hazard("riverine_flood", "emergency", "A",
                                       "T", "d", scope="reach"))
    assert st["X1"] == "IMPASSABLE"
    assert "X2" not in st                       # the detour crossing stays dry
    assert st["V"] == "REROUTED"                # ... so the village merely detours


def test_river_scope_blocks_the_detour_and_isolates(two_crossing_db):
    hid = hazards.create_hazard("riverine_flood", "emergency", "A",
                                "T", "d", scope="river")
    st = _states(hid)
    assert st["X1"] == "IMPASSABLE" and st["X2"] == "IMPASSABLE"
    assert st["V"] == "ISOLATED"                # no dry crossing left
    assert st["H"] == "SERVICE_AT_RISK"


def test_run_reports_scope_and_breakdown(two_crossing_db):
    hid = hazards.create_hazard("riverine_flood", "emergency", "A",
                                "T", "d", scope="river")
    rep = propagate.run(hid)
    assert rep["scope"] == "river"
    assert rep["flooded_reaches"] == 2
    assert rep["isolated_from"] == {"clinic": 1}      # the pitch number


def test_why_chain_names_the_reach_that_actually_blocked(two_crossing_db):
    r"""With several reaches flooded, each impact must name the water its own
    crossing spans - not the anchor reach by default."""
    import json
    hid = hazards.create_hazard("riverine_flood", "emergency", "A",
                                "T", "d", scope="river")
    propagate.run(hid)
    with db.conn() as c:
        chains = {r["object_id"]: json.loads(r["why_chain_json"])
                  for r in c.execute("SELECT * FROM impacts WHERE hazard_id=?", (hid,))}
    assert chains["X1"][1] == "A"
    assert chains["X2"][1] == "C"               # not "A"


def test_deterministic_under_river_scope(two_crossing_db):
    a = _states(hazards.create_hazard("riverine_flood", "emergency", "A",
                                      "T", "d", scope="river"))
    b = _states(hazards.create_hazard("riverine_flood", "emergency", "A",
                                      "T", "d", scope="river"))
    assert a == b
