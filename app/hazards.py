"""Hazard feeds - the second swappable edge (Phase 2 makes it live).

Phase 0: demo hazard created manually via the UI button.
Phase 2 (LIVE, USE_LIVE=1): daily scan of
  - GloFAS river discharge via Open-Meteo flood API
    GET https://flood-api.open-meteo.com/v1/flood?latitude=..&longitude=..
        &daily=river_discharge,river_discharge_max&forecast_days=7
    Trigger: forecast discharge vs return-period context -> watch/alert/emergency
    on the river_reach whose props carry that glofas point. ~5 km grid: treat as
    screening levels and say so (see 04.D).
  - CHIRPS accumulation triggers for extreme_rain (via ClimateSERV or direct tiles).
Cache every response in db.geocache. Deterministic thresholds only - no model.

Target safety (D-028): a hazard whose target_id does not exist as an object
produces ZERO impacts - propagation simply matches nothing. That is a silent
false all-clear, the one failure mode this product exists to prevent. So
create_hazard REFUSES an unknown target, and refuses a target that is not a
river_reach for riverine_flood. Never fail toward all-clear.
"""
import os

from . import db

USE_LIVE = os.environ.get("USE_LIVE", "0") == "1"

SEVERITIES = ("watch", "alert", "emergency")
SCOPES = ("reach", "river")     # see 09 / D-036 and propagate.flooded_reaches

# The demo spine's reach: the Manafwa channel crossed by BOTH town bridges -
# w128611448 (Manafwa Bridge, B112 tarmac) and w902422828 (Old Manafwa bridge,
# C870). A hazard here hits the crossing pair together, which is the real SPOF.
REAL_DEMO_REACH_ID = "w188321163"
# Phase 0 seed graph's river, kept so the seed demo and its tests still run.
SEED_DEMO_REACH_ID = "R1"


def _objects_by_id(c=None):
    return {o["id"]: o for o in db.objects(c)}


def require_reach(reach_id, c=None):
    """Raise unless reach_id exists AND is a river_reach. Returns the object.

    Called before any riverine_flood hazard is created. A missing or mistyped
    target would otherwise yield a hazard that propagates to nothing.
    """
    objs = _objects_by_id(c)
    o = objs.get(reach_id)
    if o is None:
        reaches = sorted(k for k, v in objs.items() if v["type"] == "river_reach")
        raise ValueError(
            f"hazard target {reach_id!r} is not an object in the graph - a hazard "
            f"on a nonexistent target propagates to nothing (a silent all-clear). "
            f"Known river_reach ids: {reaches[:10]}"
            f"{' ...' if len(reaches) > 10 else ''}")
    if o["type"] != "river_reach":
        raise ValueError(
            f"hazard target {reach_id!r} is a {o['type']!r}, not a river_reach; "
            f"a riverine_flood must target a river reach.")
    return o


def resolve_demo_reach(c=None):
    """Which reach the demo hazard points at. Explicit, never guessed.

    Order: DEMO_REACH_ID env override -> the real Manafwa reach (if the real
    graph is loaded) -> the seed graph's R1 -> raise.
    """
    env = os.environ.get("DEMO_REACH_ID")
    if env:
        require_reach(env, c)          # raises with a helpful list if wrong
        return env
    objs = _objects_by_id(c)
    for cand in (REAL_DEMO_REACH_ID, SEED_DEMO_REACH_ID):
        o = objs.get(cand)
        if o is not None and o["type"] == "river_reach":
            return cand
    raise ValueError(
        "no demo river_reach found: expected the real Manafwa reach "
        f"{REAL_DEMO_REACH_ID!r} or the seed reach {SEED_DEMO_REACH_ID!r}. "
        "Load the graph (ingest_osm) or seed it before raising a demo hazard.")


def create_hazard(kind: str, severity: str, target_id: str,
                  source: str, trigger_detail: str, scope: str = "reach") -> int:
    """Insert a hazard. Validates severity, scope and target before writing.

    `scope` (D-036): 'reach' floods only target_id; 'river' floods the whole
    vertex-connected channel of the same `waterway` value. A GloFAS discharge
    spike raises the connected mainstem, not one OSM way - so a demo that floods
    a single reach lets settlements detour over crossings that would, in reality,
    also be under water.
    """
    if severity not in SEVERITIES:
        raise ValueError(f"severity {severity!r} not in {list(SEVERITIES)}")
    if scope not in SCOPES:
        raise ValueError(f"scope {scope!r} not in {list(SCOPES)}")
    if kind == "riverine_flood":
        require_reach(target_id)
    else:
        if target_id not in _objects_by_id():
            raise ValueError(
                f"hazard target {target_id!r} is not an object in the graph - "
                f"it would propagate to nothing.")
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO hazards (kind, severity, target_id, source, "
            "trigger_detail, created_utc, active, scope) VALUES (?,?,?,?,?,?,1,?)",
            (kind, severity, target_id, source, trigger_detail, db.now(), scope))
        return cur.lastrowid


def clear_hazards():
    """Deactivate all hazards and drop derived rows (invariant 5)."""
    with db.conn() as c:
        c.execute("UPDATE hazards SET active=0")
        db.clear_derived(c)


def demo_flood(severity: str = "alert", reach_id: str = None,
               scope: str = "reach") -> int:
    """Raise the demo riverine flood on the pilot reach.

    NOTE on severity: engineered bridges (structure='bridge') are AT_RISK - not
    blocking - at 'alert'. The Manafwa town crossing pair are both engineered
    bridges, so only 'emergency' blocks them (see 09, D-029).
    """
    rid = reach_id or resolve_demo_reach()
    reach = require_reach(rid)
    name = reach.get("name") or rid
    where = "the connected river channel" if scope == "river" else name
    return create_hazard(
        "riverine_flood", severity, rid, "DEMO",
        f"Demo trigger: GloFAS-style forecast exceeds the return-period "
        f"threshold for {severity} on {where} within 3 days "
        f"(screening-grade, ~5 km grid)", scope=scope)


def demo_flood_river(severity: str = "emergency", reach_id: str = None) -> int:
    """The demo hazard as it physically behaves: the whole connected river
    channel in flood, not one OSM way. See D-036."""
    return demo_flood(severity, reach_id, scope="river")


def scan_live():
    if not USE_LIVE:
        return {"status": "live scan disabled (USE_LIVE=0)"}
    raise NotImplementedError(
        "Phase 2: pull Open-Meteo flood API for each river_reach glofas point, "
        "apply thresholds, create hazards, run propagation + actions. "
        "Must call require_reach() on every target before create_hazard (D-028).")
