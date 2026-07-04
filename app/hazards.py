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
"""
import os

from . import db

USE_LIVE = os.environ.get("USE_LIVE", "0") == "1"


def create_hazard(kind: str, severity: str, target_id: str,
                  source: str, trigger_detail: str) -> int:
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO hazards (kind, severity, target_id, source, "
            "trigger_detail, created_utc, active) VALUES (?,?,?,?,?,?,1)",
            (kind, severity, target_id, source, trigger_detail, db.now()))
        return cur.lastrowid


def clear_hazards():
    """Deactivate all hazards and drop derived rows (invariant 5)."""
    with db.conn() as c:
        c.execute("UPDATE hazards SET active=0")
        db.clear_derived(c)


def demo_flood(severity: str = "alert") -> int:
    return create_hazard(
        "riverine_flood", severity, "R1", "DEMO",
        f"Demo trigger: GloFAS-style forecast exceeds return-period threshold "
        f"({severity}) on River Nakoko within 3 days")


def scan_live():
    if not USE_LIVE:
        return {"status": "live scan disabled (USE_LIVE=0)"}
    raise NotImplementedError(
        "Phase 2: pull Open-Meteo flood API for each river_reach glofas point, "
        "apply thresholds, create hazards, run propagation + actions.")
