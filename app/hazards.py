"""Hazard feeds - the second swappable edge. Phase 2 makes it live.

LIVE (USE_LIVE=1): daily scan of GloFAS river discharge via the Open-Meteo flood
API, free, no key, ~5 km grid. Deterministic thresholds only - no model, ever.

Target safety (D-028): a hazard whose target_id does not exist as an object
produces ZERO impacts - propagation simply matches nothing. That is a silent
false all-clear, the one failure mode this product exists to prevent. So
create_hazard REFUSES an unknown target, and refuses a target that is not a
river_reach for riverine_flood. Never fail toward all-clear.

Trigger doctrine (D-047), measured on the pilot graph, not assumed:

  * A reach's GloFAS point is OPERATOR-VERIFIED, never auto-snapped. The demo
    reach w188321163 is 4.3 km long and straddles THREE 0.05 deg cells whose mean
    discharge reads 67.7, 6.1 and 91.5 m3/s - a 23x spread, non-monotonic
    downstream. Water does not do that: two of those cells model a DIFFERENT
    river. A dead cell reads 0.0 and screams; a wrong cell reads 91.5 and looks
    like data. So geometry proposes (scripts/glofas_probe.py) and the engineer
    signs (data/reach_glofas.csv).

  * Thresholds are EMPIRICAL (Weibull plotting position T=(n+1)/m) over ANNUAL
    MAXIMA. No distribution is fitted. Beyond MAX_RETURN_PERIOD the code refuses
    to answer rather than extrapolate: with n=29 (the reanalysis starts 1997, not
    1984 - the API silently clips the requested window), Q10 rests on the third
    largest peak and Q20 interpolates between the top two. A Gumbel fit returns
    Q10=17.5 against the empirical 19.4 because it flattens the 1998 El Nino
    outlier; a fitted number past the record is an extrapolation wearing a
    decimal point.

  * severity -> return period is DATA (data/triggers.csv), committee-tunable,
    never buried in code (D-007). watch=Q2, alert=Q5, emergency=Q10.

  * A FETCH FAILURE IS NOT AN ALL-CLEAR. Every failure raises. "No hazard" and
    "the API was down" must never render identically on a map (invariant 6).
"""
import csv
import json
import math
import os
import time
import urllib.error
import urllib.request

from . import db

USE_LIVE = os.environ.get("USE_LIVE", "0") == "1"

SEVERITIES = ("watch", "alert", "emergency")
SCOPES = ("reach", "river")     # see 09 / D-036 and propagate.flooded_reaches
HAZARD_KINDS = ("riverine_flood", "extreme_rain")

# The demo spine's reach: the Manafwa channel crossed by BOTH town bridges -
# w128611448 (Manafwa Bridge, B112 tarmac) and w902422828 (Old Manafwa bridge,
# C870). A hazard here hits the crossing pair together, which is the real SPOF.
REAL_DEMO_REACH_ID = "w188321163"
# Phase 0 seed graph's river, kept so the seed demo and its tests still run.
SEED_DEMO_REACH_ID = "R1"

API = "https://flood-api.open-meteo.com/v1/flood"
REANALYSIS_START = "1984-01-01"          # the API serves from 1997; we verify
REANALYSIS_END = "2025-12-31"
FORECAST_DAYS = 7                        # anticipatory-action lead time
MIN_ANNUAL_MAXIMA = 20                   # fewer years than this: refuse to threshold
MAX_RETURN_PERIOD = 20                   # beyond this we do not extrapolate (D-047)
CELL_TOLERANCE_DEG = 0.03                # the served cell must be the verified cell

_HERE = os.path.dirname(__file__)
REACH_GLOFAS_PATH = os.path.join(_HERE, "..", "data", "reach_glofas.csv")
TRIGGERS_PATH = os.path.join(_HERE, "..", "data", "triggers.csv")


class HazardFeedError(Exception):
    """A feed failed. Raised, never swallowed: silence looks like a calm river."""


def _use_live():
    return os.environ.get("USE_LIVE", "0") == "1"


# --------------------------------------------------------------- graph guards (D-028)

def _objects_by_id(c=None):
    return {o["id"]: o for o in db.objects(c)}


def require_reach(reach_id, c=None):
    """Raise unless reach_id exists AND is a river_reach. Returns the object."""
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
    """Which reach the demo hazard points at. Explicit, never guessed."""
    env = os.environ.get("DEMO_REACH_ID")
    if env:
        require_reach(env, c)
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
    """Insert a hazard. Validates severity, scope and target before writing."""
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


# ------------------------------------------------------------------ the feed

def _get(url, tries=3):
    """One HTTP GET with backoff. Raises HazardFeedError - never returns None,
    never returns an empty series that a caller could read as 'no flood'."""
    last = None
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode())
        except Exception as e:                     # noqa: BLE001 - all are fatal here
            last = e
            if i < tries - 1:
                time.sleep(2 ** i * 3)
    raise HazardFeedError(
        f"GloFAS fetch failed after {tries} tries: {url} ({last!r}). "
        f"A dead feed is NOT an all-clear - refusing to report 'no hazard'.")


def _cached(key, url):
    with db.conn() as c:
        row = c.execute("SELECT value_json FROM geocache WHERE key=?", (key,)).fetchone()
        if row:
            return json.loads(row["value_json"])
    data = _get(url)
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?)",
                  (key, json.dumps(data), db.now()))
    return data


def _series(data):
    d = data.get("daily") or {}
    t, v = d.get("time") or [], d.get("river_discharge") or []
    pairs = [(a, b) for a, b in zip(t, v) if b is not None]
    return [a for a, _ in pairs], [b for _, b in pairs]


def _check_cell(data, lat, lon):
    """The API snaps a request onto a cell centre. The verified cell is the one
    the engineer signed off; if the service hands back a different one, the
    thresholds no longer describe the water we verified. Refuse."""
    got_lat, got_lon = data.get("latitude"), data.get("longitude")
    if got_lat is None or got_lon is None:
        raise HazardFeedError(f"response for {lat},{lon} carries no coordinates")
    if (abs(got_lat - lat) > CELL_TOLERANCE_DEG
            or abs(got_lon - lon) > CELL_TOLERANCE_DEG):
        raise HazardFeedError(
            f"GloFAS served cell {got_lat},{got_lon} for the verified point "
            f"{lat},{lon} (> {CELL_TOLERANCE_DEG} deg away). The operator "
            f"verified a specific cell; this is a different one. Re-verify.")
    return got_lat, got_lon


def reanalysis(lat, lon):
    """Daily discharge history for one verified cell. Returns (dates, values).

    Asserts the served window rather than trusting the requested one: we ask for
    1984 and the API quietly serves from 1997.
    """
    key = f"glofas:re:{lat:.4f},{lon:.4f}:{REANALYSIS_START}:{REANALYSIS_END}"
    url = (f"{API}?latitude={lat}&longitude={lon}&daily=river_discharge"
           f"&start_date={REANALYSIS_START}&end_date={REANALYSIS_END}")
    data = _cached(key, url)
    _check_cell(data, lat, lon)
    dates, vals = _series(data)
    if not vals:
        raise HazardFeedError(f"empty reanalysis for {lat},{lon} - cannot threshold")
    if max(vals) <= 0.0:
        raise HazardFeedError(
            f"cell {lat},{lon} reads 0.0 m3/s across its whole record: it is not "
            f"on the GloFAS modelled channel. A reach pinned here could never "
            f"trigger - a permanent silent all-clear. Re-verify the point.")
    return dates, vals


def forecast(lat, lon, days=FORECAST_DAYS):
    key = f"glofas:fc{days}:{lat:.4f},{lon:.4f}:{time.strftime('%Y-%m-%d')}"
    url = (f"{API}?latitude={lat}&longitude={lon}&daily=river_discharge"
           f"&forecast_days={days}")
    data = _cached(key, url)
    _check_cell(data, lat, lon)
    dates, vals = _series(data)
    if not vals:
        raise HazardFeedError(f"empty forecast for {lat},{lon}")
    peak = max(vals)
    return peak, dates[vals.index(peak)], dates


# ------------------------------------------------------- flood frequency (empirical)

def annual_maxima(dates, vals):
    """One peak per calendar year. Annual maximum series - the standard sample,
    one flood population. Seasonal maxima would double n but mix the lesser
    season's peaks into the sample (D-047)."""
    peaks = {}
    for d, v in zip(dates, vals):
        y = d[:4]
        peaks[y] = max(peaks.get(y, 0.0), v)
    return dict(sorted(peaks.items()))


def weibull_q(peaks, T):
    """Empirical quantile at return period T via the Weibull plotting position
    T = (n+1)/m. No distribution is fitted.

    Returns None when T lies beyond the record (m < 1) - the caller must treat
    that as "unanswerable", never as "not exceeded". Refusing to extrapolate is
    the whole point: a fitted Q50 from 29 years is a guess with a decimal point.
    """
    if T > MAX_RETURN_PERIOD:
        raise ValueError(
            f"return period {T} exceeds MAX_RETURN_PERIOD={MAX_RETURN_PERIOD}; "
            f"this code does not extrapolate beyond the record (D-047)")
    x = sorted(peaks, reverse=True)
    n = len(x)
    if n < 2:
        return None
    m = (n + 1) / T
    if m < 1:
        return None                       # T beyond the record
    if m >= n:
        return x[-1]
    lo = int(math.floor(m))
    return x[lo - 1] + (x[lo] - x[lo - 1]) * (m - lo)


# ------------------------------------------------------------------ the data files

def load_triggers(path=None):
    """severity -> return_period_years, for one hazard kind. Data, not code."""
    path = path or TRIGGERS_PATH
    if not os.path.exists(path):
        raise HazardFeedError(f"triggers file not found: {path}")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=2):
            kind = (row.get("hazard_kind") or "").strip()
            sev = (row.get("severity") or "").strip()
            if not kind and not sev:
                continue
            if kind not in HAZARD_KINDS:
                raise HazardFeedError(f"triggers line {n}: unknown hazard_kind {kind!r}")
            if sev not in SEVERITIES:
                raise HazardFeedError(f"triggers line {n}: unknown severity {sev!r}")
            try:
                T = float(row["return_period_years"])
            except (KeyError, TypeError, ValueError):
                raise HazardFeedError(f"triggers line {n}: return_period_years is not a number")
            if T <= 1:
                raise HazardFeedError(f"triggers line {n}: return period {T} must exceed 1 year")
            if T > MAX_RETURN_PERIOD:
                raise HazardFeedError(
                    f"triggers line {n}: return period {T} exceeds "
                    f"MAX_RETURN_PERIOD={MAX_RETURN_PERIOD}. The record cannot "
                    f"support it; raise the record, not the number.")
            if (kind, sev) in out:
                raise HazardFeedError(f"triggers line {n}: duplicate {kind}/{sev}")
            out[(kind, sev)] = T

    missing = [s for s in SEVERITIES if ("riverine_flood", s) not in out]
    if missing:
        raise HazardFeedError(f"triggers missing riverine_flood severities: {missing}")
    ts = [out[("riverine_flood", s)] for s in SEVERITIES]
    if ts != sorted(ts) or len(set(ts)) != len(ts):
        raise HazardFeedError(
            f"riverine_flood return periods must strictly increase with severity, got "
            f"{dict(zip(SEVERITIES, ts))}. A watch rarer than an emergency is nonsense.")
    return out


def load_reach_points(path=None, validate=True):
    """reach_id -> (lat, lon, note). Operator-verified GloFAS cells (D-047)."""
    path = path or REACH_GLOFAS_PATH
    if not os.path.exists(path):
        raise HazardFeedError(f"reach GloFAS points file not found: {path}")
    out = {}
    with open(path, newline="", encoding="utf-8") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=2):
            rid = (row.get("reach_id") or "").strip()
            if not rid:
                continue
            if rid in out:
                raise HazardFeedError(f"reach_glofas line {n}: duplicate reach {rid!r}")
            try:
                lat, lon = float(row["glofas_lat"]), float(row["glofas_lon"])
            except (KeyError, TypeError, ValueError):
                raise HazardFeedError(f"reach_glofas line {n}: bad lat/lon for {rid!r}")
            if not (row.get("verified_by") or "").strip():
                raise HazardFeedError(
                    f"reach_glofas line {n}: {rid!r} has no verified_by. An "
                    f"unsigned GloFAS point is an auto-snap, which D-047 forbids.")
            if validate:
                require_reach(rid)            # D-028, before it can ever be a target
            out[rid] = (lat, lon, (row.get("note") or "").strip())
    if not out:
        raise HazardFeedError(f"no verified GloFAS points in {path}")
    return out


def thresholds(lat, lon, triggers=None, kind="riverine_flood"):
    """severity -> discharge threshold, from this cell's own annual maxima."""
    triggers = triggers or load_triggers()
    dates, vals = reanalysis(lat, lon)
    am = annual_maxima(dates, vals)
    peaks = list(am.values())
    if len(peaks) < MIN_ANNUAL_MAXIMA:
        raise HazardFeedError(
            f"cell {lat},{lon}: only {len(peaks)} annual maxima "
            f"({min(am)}-{max(am)}); need >= {MIN_ANNUAL_MAXIMA} to set a "
            f"return-period threshold. Refusing to guess.")
    out = {}
    for sev in SEVERITIES:
        T = triggers[(kind, sev)]
        q = weibull_q(peaks, T)
        if q is None:
            raise HazardFeedError(
                f"cell {lat},{lon}: Q{T:g} lies beyond a {len(peaks)}-year record")
        out[sev] = q
    return {"thresholds": out, "n": len(peaks),
            "record": f"{min(am)}-{max(am)}", "method": "Weibull empirical, annual maxima"}


# ------------------------------------------------------------------ the daily scan

def _already_raised(c, kind, target_id, severity):
    """One hazard per reach per severity per UTC day. A cron that runs hourly
    must not stack twelve identical emergencies."""
    today = db.now()[:10]
    row = c.execute(
        "SELECT id FROM hazards WHERE kind=? AND target_id=? AND severity=? "
        "AND active=1 AND substr(created_utc,1,10)=?",
        (kind, target_id, severity, today)).fetchone()
    return row["id"] if row else None


def scan_live(days=FORECAST_DAYS, scope="river", triggers_path=None,
              points_path=None):
    """The daily GloFAS scan. Deterministic. No model.

    For each operator-verified reach point: pull the forecast, compare its peak
    against that cell's own empirical return-period thresholds, and raise a
    hazard at the HIGHEST severity actually exceeded. Nothing exceeded -> no
    hazard, and the numbers are reported so "quiet river" is visibly different
    from "we did not look".

    Any fetch or threshold failure RAISES. It never returns a clean empty result.
    """
    if not _use_live():
        return {"status": "live scan disabled (USE_LIVE=0)",
                "triggered": [], "checked": 0, "unverified": None}

    triggers = load_triggers(triggers_path)
    points = load_reach_points(points_path)

    # waterway=stream is a pluvial/extreme_rain hazard, not a riverine one, and
    # GloFAS does not resolve it (D-036). Counting streams as "unverified river
    # points" would make an honest number look like a coverage failure.
    rivers = [o["id"] for o in db.objects()
              if o["type"] == "river_reach"
              and (o["props"].get("tags") or {}).get("waterway") == "river"]
    unverified = sorted(set(rivers) - set(points))

    triggered, quiet = [], []
    for rid in sorted(points):
        lat, lon, note = points[rid]
        require_reach(rid)                                # D-028, again, at use
        th = thresholds(lat, lon, triggers)
        peak, peak_date, _ = forecast(lat, lon, days)

        hit = None
        for sev in SEVERITIES:                            # watch < alert < emergency
            if peak >= th["thresholds"][sev]:
                hit = sev
        if hit is None:
            quiet.append({"reach_id": rid, "peak": peak, "peak_date": peak_date,
                          "watch_threshold": th["thresholds"]["watch"]})
            continue

        T = triggers[("riverine_flood", hit)]
        detail = (
            f"GloFAS forecast peak {peak:.2f} m3/s on {peak_date} (next {days} d) "
            f"reaches the Q{T:g} level {th['thresholds'][hit]:.2f} m3/s for "
            f"'{hit}'. Empirical annual-maxima threshold from the "
            f"{th['record']} reanalysis (n={th['n']}), cell {lat},{lon}. "
            f"GloFAS is ~5 km grid: screening-grade at village scale.")

        with db.conn() as c:
            existing = _already_raised(c, "riverine_flood", rid, hit)
        if existing:
            triggered.append({"reach_id": rid, "severity": hit, "hazard_id": existing,
                              "peak": peak, "threshold": th["thresholds"][hit],
                              "created": False})
            continue

        hid = create_hazard("riverine_flood", hit, rid, "GloFAS/Open-Meteo",
                            detail, scope=scope)
        triggered.append({"reach_id": rid, "severity": hit, "hazard_id": hid,
                          "peak": peak, "threshold": th["thresholds"][hit],
                          "created": True})

    return {"status": "ok", "checked": len(points), "triggered": triggered,
            "quiet": quiet, "unverified": len(unverified),
            "unverified_reaches": unverified,
            "note": ("reaches without a verified GloFAS point cannot raise a hazard; "
                     "under scope=river a trigger on one verified reach floods the "
                     "whole connected channel (D-036)")}
