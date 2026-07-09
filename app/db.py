"""SQLite state: the object graph, hazards, impacts, actions. All truth lives here."""
import json
import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "lifeline.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS objects (
    id TEXT PRIMARY KEY, type TEXT NOT NULL, name TEXT,
    lat REAL, lon REAL, props_json TEXT DEFAULT '{}',
    source TEXT DEFAULT 'seed', created_utc TEXT
);
CREATE TABLE IF NOT EXISTS links (
    src TEXT NOT NULL, dst TEXT NOT NULL, type TEXT NOT NULL,
    inferred_by TEXT DEFAULT 'seed',
    PRIMARY KEY (src, dst, type)
);
CREATE TABLE IF NOT EXISTS hazards (
    id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT, severity TEXT,
    target_id TEXT, source TEXT, trigger_detail TEXT,
    created_utc TEXT, active INTEGER DEFAULT 1,
    scope TEXT DEFAULT 'reach'
);
CREATE TABLE IF NOT EXISTS impacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT, hazard_id INTEGER, object_id TEXT,
    state TEXT, why_chain_json TEXT, created_utc TEXT
);
CREATE TABLE IF NOT EXISTS actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, impact_id INTEGER, action_text TEXT,
    owner_role TEXT, lead_time_hrs INTEGER, status TEXT DEFAULT 'PROPOSED'
);
CREATE TABLE IF NOT EXISTS geocache (
    key TEXT PRIMARY KEY, value_json TEXT, fetched_utc TEXT
);
"""


# Additive, idempotent column migrations. CREATE TABLE IF NOT EXISTS never alters
# an existing table, so a new column must be added explicitly or an already-loaded
# graph would silently keep the old schema.
MIGRATIONS = [
    ("hazards", "scope", "ALTER TABLE hazards ADD COLUMN scope TEXT DEFAULT 'reach'"),
]


def _migrate(c):
    for table, column, ddl in MIGRATIONS:
        cols = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
        if column not in cols:
            c.execute(ddl)


# Paths whose schema has been ensured in THIS process. Schema must never lag the
# code: a migration that only runs when someone remembers to call init() will be
# missed by scripts, cron jobs and the scheduler (D-037).
_schema_ready = set()


def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    if DB_PATH not in _schema_ready:
        c.executescript(SCHEMA)      # CREATE TABLE IF NOT EXISTS - cheap, idempotent
        _migrate(c)                  # additive column migrations
        c.commit()
        _schema_ready.add(DB_PATH)
    return c


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def init():
    """Explicit schema setup. conn() now does this lazily too, so init() is a
    no-op on an already-current database - kept for clarity at startup."""
    with conn() as c:
        c.executescript(SCHEMA)
        _migrate(c)


def add_object(c, oid, otype, name, lat, lon, props=None, source="seed"):
    c.execute("INSERT OR REPLACE INTO objects VALUES (?,?,?,?,?,?,?,?)",
              (oid, otype, name, lat, lon, json.dumps(props or {}), source, now()))


def add_link(c, src, dst, ltype, inferred_by="seed"):
    c.execute("INSERT OR REPLACE INTO links VALUES (?,?,?,?)", (src, dst, ltype, inferred_by))


def objects(c=None):
    close = c is None
    c = c or conn()
    rows = [dict(r) | {"props": json.loads(r["props_json"])}
            for r in c.execute("SELECT * FROM objects")]
    if close:
        c.close()
    return rows


def links(c=None):
    close = c is None
    c = c or conn()
    rows = [dict(r) for r in c.execute("SELECT * FROM links")]
    if close:
        c.close()
    return rows


def clear_derived(c, hazard_id=None):
    """Invariant 5: re-scans are idempotent - derived impacts/actions are rebuilt."""
    if hazard_id:
        c.execute("DELETE FROM actions WHERE impact_id IN "
                  "(SELECT id FROM impacts WHERE hazard_id=?)", (hazard_id,))
        c.execute("DELETE FROM impacts WHERE hazard_id=?", (hazard_id,))
    else:
        c.execute("DELETE FROM actions")
        c.execute("DELETE FROM impacts")


def seed_demo_graph():
    """Fictional but structurally realistic river-crossing corridor.
    Layout: River R1 crossed by one culvert (C1, carries road RD2) and one bridge
    (B1, carries road RD4, longer way round). Village V1's only access is via RD1-RD2
    (through the culvert) to the junction road RD3 where the clinic, school and
    borehole sit. Village V2 has BOTH routes (RD2 via culvert and RD4 via bridge).
    So: culvert fails alone -> V1 ISOLATED, V2 REROUTED. Both fail -> V2 ISOLATED too.
    """
    with conn() as c:
        c.executescript("DELETE FROM objects; DELETE FROM links; DELETE FROM hazards;"
                        "DELETE FROM impacts; DELETE FROM actions;")
        A = lambda *a, **k: add_object(c, *a, **k)
        L = lambda *a: add_link(c, *a)
        A("R1", "river_reach", "River Nakoko (demo)", 1.0210, 34.2010,
          {"glofas_lat": 1.02, "glofas_lon": 34.20})
        A("C1", "bridge", "Nakoko culvert crossing", 1.0212, 34.2015,
          {"structure": "culvert", "single_point_of_failure": True})
        A("B1", "bridge", "Nakoko concrete bridge", 1.0295, 34.2100,
          {"structure": "bridge"})
        A("RD1", "road_segment", "Village spur (V1)", 1.0150, 34.1950, {"all_weather": False})
        A("RD2", "road_segment", "Culvert road (short way)", 1.0212, 34.2018, {"all_weather": False})
        A("RD3", "road_segment", "Trading-centre road", 1.0250, 34.2060, {"all_weather": True})
        A("RD4A", "road_segment", "Bridge road A (long way)", 1.0280, 34.2085, {"all_weather": True})
        A("RD4B", "road_segment", "Bridge road B (long way)", 1.0290, 34.2115, {"all_weather": True})
        A("RD5", "road_segment", "V2 spur", 1.0190, 34.2130, {"all_weather": False})
        A("V1", "settlement", "Bumasata village (demo)", 1.0140, 34.1940, {"population": 3200})
        A("V2", "settlement", "Bunamubi village (demo)", 1.0185, 34.2140, {"population": 7800})
        A("H1", "clinic", "St. Marks HC III (demo)", 1.0255, 34.2065)
        A("S1", "school", "Nakoko Primary (demo)", 1.0252, 34.2058)
        A("W1", "water_point", "Trading-centre borehole", 1.0248, 34.2062, {"kind": "borehole"})
        # crossings
        L("C1", "R1", "crosses"); L("B1", "R1", "crosses")
        L("RD2", "C1", "carries"); L("RD4A", "B1", "carries")
        # road network: V1 -RD1-RD2-RD3(facilities); V2 -RD5-RD2 (3 hops, short)
        # or RD5-RD4B-RD4A-RD3 (4 hops, long, over the bridge)
        L("RD1", "RD2", "connects"); L("RD2", "RD3", "connects")
        L("RD3", "RD4A", "connects"); L("RD4A", "RD4B", "connects")
        L("RD4B", "RD5", "connects"); L("RD5", "RD2", "connects")
        # settlement access
        L("V1", "RD1", "access_via"); L("V2", "RD5", "access_via")
        # services (facilities sit on RD3)
        for f in ("H1", "S1", "W1"):
            L(f, "V1", "serves"); L(f, "V2", "serves")
            L(f, "RD3", "access_via")
        # floodplain exposure: V2 sits low near the river (demo)
        L("V2", "R1", "on_floodplain")
