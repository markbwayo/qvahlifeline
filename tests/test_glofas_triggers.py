"""GloFAS trigger tests (D-047). No network: `hazards._get` is replaced by a
synthetic Open-Meteo whose annual maxima are exactly 1..29, so every empirical
quantile is checkable by hand:

    n=29, Weibull T=(n+1)/m  ->  m = 30/T
    Q2  : m=15   -> 15th largest = 15.0
    Q5  : m=6    ->  6th largest = 24.0
    Q10 : m=3    ->  3rd largest = 27.0
    Q20 : m=1.5  -> between the top two = 28.5

The failure direction under test throughout: a dead feed, a wrong cell, a short
record or a missing verified point must RAISE or REPORT. None of them may return
a clean, empty, reassuring result (invariant 6).
"""
import csv
import json
import os

import pytest

from app import db, hazards, propagate
from app.hazards import HazardFeedError

YEARS = list(range(1997, 2026))          # 29 years, as the real API serves
PEAKS = {y: float(i + 1) for i, y in enumerate(YEARS)}   # annual maxima 1..29
Q = {"watch": 15.0, "alert": 24.0, "emergency": 27.0}    # Q2 / Q5 / Q10


# --------------------------------------------------------------------------- harness

def fake_get(url, tries=3):
    lat = float(url.split("latitude=")[1].split("&")[0])
    lon = float(url.split("longitude=")[1].split("&")[0])
    if "forecast_days" in url:
        peak = fake_get.forecast_peak
        return {"latitude": lat, "longitude": lon,
                "daily": {"time": ["2026-07-10", "2026-07-11", "2026-07-12"],
                          "river_discharge": [0.5, peak, 0.5]}}
    t, v = [], []
    for y in YEARS:
        t += [f"{y}-01-01", f"{y}-05-15", f"{y}-09-01"]
        v += [0.4, PEAKS[y] if not fake_get.dead else 0.0, 0.6 if not fake_get.dead else 0.0]
    if fake_get.dead:
        v = [0.0] * len(v)
    return {"latitude": lat, "longitude": lon,
            "daily": {"time": t, "river_discharge": v}}


fake_get.forecast_peak = 1.0
fake_get.dead = False


def write_csv(path, header, rows):
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    return str(path)


TRIGGER_HEADER = ["hazard_kind", "severity", "return_period_years", "note"]
GOOD_TRIGGERS = [["riverine_flood", "watch", "2", ""],
                 ["riverine_flood", "alert", "5", ""],
                 ["riverine_flood", "emergency", "10", ""]]

POINT_HEADER = ["reach_id", "glofas_lat", "glofas_lon", "note", "verified_by"]
GOOD_POINT = [["R1", "1.025", "34.225", "town crossing cell", "Bwayo"]]


@pytest.fixture()
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.db"))
    db._schema_ready.clear()
    db.init()
    db.seed_demo_graph()
    monkeypatch.setattr(hazards, "_get", fake_get)
    monkeypatch.setenv("USE_LIVE", "1")
    fake_get.forecast_peak, fake_get.dead = 1.0, False
    yield {"triggers": write_csv(tmp_path / "tr.csv", TRIGGER_HEADER, GOOD_TRIGGERS),
           "points": write_csv(tmp_path / "pt.csv", POINT_HEADER, GOOD_POINT),
           "tmp": tmp_path}
    db._schema_ready.clear()


def scan(live, **kw):
    return hazards.scan_live(triggers_path=live["triggers"],
                             points_path=live["points"], **kw)


def hazard_rows():
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM hazards WHERE active=1")]


# --------------------------------------------------------------- flood frequency math

def test_weibull_matches_the_hand_calculation():
    p = [float(i) for i in range(1, 30)]          # n=29
    assert hazards.weibull_q(p, 2) == 15.0
    assert hazards.weibull_q(p, 5) == 24.0
    assert hazards.weibull_q(p, 10) == 27.0
    assert hazards.weibull_q(p, 20) == pytest.approx(28.5)


def test_weibull_refuses_to_extrapolate_beyond_the_cap():
    p = [float(i) for i in range(1, 30)]
    with pytest.raises(ValueError, match="does not extrapolate"):
        hazards.weibull_q(p, 50)


def test_weibull_returns_none_beyond_the_record_not_zero():
    """None means 'unanswerable'. A caller must never read it as 'not exceeded'."""
    short = [1.0, 2.0, 3.0, 4.0, 5.0]             # n=5, T=20 -> m=0.3
    assert hazards.weibull_q(short, 20) is None
    assert hazards.weibull_q(short, 2) == 3.0     # m=3 -> 3rd largest


def test_annual_maxima_takes_one_peak_per_year():
    dates = ["1997-01-01", "1997-05-01", "1998-03-01"]
    vals = [3.0, 9.0, 4.0]
    assert hazards.annual_maxima(dates, vals) == {"1997": 9.0, "1998": 4.0}


# --------------------------------------------------------------------- triggers.csv

def test_triggers_load(live):
    t = hazards.load_triggers(live["triggers"])
    assert t[("riverine_flood", "emergency")] == 10


@pytest.mark.parametrize("rows, needle", [
    ([["mudslide", "watch", "2", ""]], "hazard_kind"),
    ([["riverine_flood", "panic", "2", ""]], "severity"),
    ([["riverine_flood", "watch", "soon", ""]], "not a number"),
    ([["riverine_flood", "watch", "1", ""]], "must exceed 1"),
    ([["riverine_flood", "watch", "50", ""]], "MAX_RETURN_PERIOD"),
])
def test_triggers_refuse_bad_rows(live, rows, needle):
    p = write_csv(live["tmp"] / "bad.csv", TRIGGER_HEADER, rows)
    with pytest.raises(HazardFeedError, match=needle):
        hazards.load_triggers(p)


def test_triggers_refuse_duplicate_and_missing(live):
    dup = GOOD_TRIGGERS + [["riverine_flood", "watch", "3", ""]]
    with pytest.raises(HazardFeedError, match="duplicate"):
        hazards.load_triggers(write_csv(live["tmp"] / "d.csv", TRIGGER_HEADER, dup))
    with pytest.raises(HazardFeedError, match="missing"):
        hazards.load_triggers(write_csv(live["tmp"] / "m.csv", TRIGGER_HEADER,
                                        GOOD_TRIGGERS[:2]))


def test_triggers_must_increase_with_severity(live):
    """A watch rarer than an emergency would fire the emergency first and never
    the watch - the severity ladder inverted, silently."""
    bad = [["riverine_flood", "watch", "10", ""],
           ["riverine_flood", "alert", "5", ""],
           ["riverine_flood", "emergency", "2", ""]]
    with pytest.raises(HazardFeedError, match="strictly increase"):
        hazards.load_triggers(write_csv(live["tmp"] / "i.csv", TRIGGER_HEADER, bad))


# ------------------------------------------------------------------ reach_glofas.csv

def test_points_require_a_signature(live):
    rows = [["R1", "1.025", "34.225", "n", ""]]
    p = write_csv(live["tmp"] / "u.csv", POINT_HEADER, rows)
    with pytest.raises(HazardFeedError, match="no verified_by"):
        hazards.load_reach_points(p)


def test_points_reject_an_unknown_or_mistyped_reach(live):
    """D-028 at load time: a hazard on a nonexistent target propagates to nothing."""
    p = write_csv(live["tmp"] / "x.csv", POINT_HEADER,
                  [["NOPE", "1.0", "34.2", "n", "Bwayo"]])
    with pytest.raises(ValueError, match="not an object in the graph"):
        hazards.load_reach_points(p)
    p2 = write_csv(live["tmp"] / "y.csv", POINT_HEADER,
                   [["V1", "1.0", "34.2", "n", "Bwayo"]])
    with pytest.raises(ValueError, match="not a river_reach"):
        hazards.load_reach_points(p2)


def test_points_reject_duplicates_and_bad_coords(live):
    with pytest.raises(HazardFeedError, match="duplicate"):
        hazards.load_reach_points(write_csv(
            live["tmp"] / "dd.csv", POINT_HEADER, GOOD_POINT + GOOD_POINT))
    with pytest.raises(HazardFeedError, match="bad lat/lon"):
        hazards.load_reach_points(write_csv(
            live["tmp"] / "bc.csv", POINT_HEADER,
            [["R1", "north", "34.2", "n", "Bwayo"]]))


# --------------------------------------------------------------- the feed fails loudly

def test_a_served_cell_far_from_the_verified_cell_is_refused(live):
    def drifted(url, tries=3):
        d = fake_get(url)
        d["latitude"] += 0.5                      # a different cell entirely
        return d
    hazards._get = drifted
    with pytest.raises(HazardFeedError, match="Re-verify"):
        scan(live)
    assert hazard_rows() == []


def test_a_dead_cell_raises_rather_than_reporting_calm_water(live):
    fake_get.dead = True
    with pytest.raises(HazardFeedError, match="modelled channel"):
        scan(live)
    assert hazard_rows() == []


def test_get_itself_raises_on_a_network_failure(monkeypatch):
    """_get's own contract, exercised directly. If it ever returns an empty
    response instead of raising, an outage becomes a calm river."""
    import urllib.request
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise OSError("connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", boom)
    monkeypatch.setattr(hazards.time, "sleep", lambda *_: None)
    with pytest.raises(HazardFeedError, match="NOT an all-clear"):
        hazards._get("https://example.invalid/x", tries=3)
    assert len(calls) == 3                        # it retried, then gave up loudly


def test_an_empty_series_is_never_read_as_no_flood(live):
    """Even a 200 OK with no data must not become 'the river is quiet'."""
    hazards._get = lambda url, tries=3: {"latitude": 1.025, "longitude": 34.225,
                                         "daily": {"time": [], "river_discharge": []}}
    with pytest.raises(HazardFeedError, match="empty reanalysis"):
        scan(live)
    assert hazard_rows() == []


def test_a_fetch_failure_is_never_an_all_clear(live):
    def dead_api(url, tries=3):
        raise HazardFeedError("GloFAS fetch failed after 3 tries: simulated outage. "
                              "A dead feed is NOT an all-clear")
    hazards._get = dead_api
    with pytest.raises(HazardFeedError, match="NOT an all-clear"):
        scan(live)
    assert hazard_rows() == []


def test_a_short_record_refuses_to_threshold(live, monkeypatch):
    monkeypatch.setattr(hazards, "MIN_ANNUAL_MAXIMA", 40)
    with pytest.raises(HazardFeedError, match="Refusing to guess"):
        scan(live)
    assert hazard_rows() == []


# --------------------------------------------------------------------- the scan itself

def test_use_live_off_raises_nothing_and_says_so(live, monkeypatch):
    monkeypatch.setenv("USE_LIVE", "0")
    res = scan(live)
    assert res["status"].startswith("live scan disabled")
    assert res["triggered"] == [] and hazard_rows() == []


def test_thresholds_are_the_hand_calculated_quantiles(live):
    th = hazards.thresholds(1.025, 34.225, hazards.load_triggers(live["triggers"]))
    assert th["n"] == 29 and th["record"] == "1997-2025"
    assert th["thresholds"] == pytest.approx(Q)
    assert "Weibull" in th["method"]


def test_a_quiet_river_raises_no_hazard_and_reports_the_numbers(live):
    fake_get.forecast_peak = 5.0                  # below Q2 = 15
    res = scan(live)
    assert res["triggered"] == [] and hazard_rows() == []
    assert res["quiet"][0]["reach_id"] == "R1"
    assert res["quiet"][0]["peak"] == 5.0
    assert res["quiet"][0]["watch_threshold"] == pytest.approx(15.0)


@pytest.mark.parametrize("peak, sev", [
    (15.0, "watch"), (23.9, "watch"),
    (24.0, "alert"), (26.9, "alert"),
    (27.0, "emergency"), (99.0, "emergency"),
])
def test_the_highest_exceeded_severity_wins(live, peak, sev):
    fake_get.forecast_peak = peak
    res = scan(live)
    assert [t["severity"] for t in res["triggered"]] == [sev]
    assert hazard_rows()[0]["severity"] == sev


def test_the_1998_level_fires_emergency_on_the_real_reach(live):
    """Replay of the record's largest peak. Real arithmetic, real thresholds."""
    fake_get.forecast_peak = max(PEAKS.values())          # the 2025 peak here = 29
    res = scan(live)
    t = res["triggered"][0]
    assert t["severity"] == "emergency" and t["created"] is True
    h = hazard_rows()[0]
    assert h["kind"] == "riverine_flood" and h["target_id"] == "R1"
    assert h["scope"] == "river"                          # D-036
    assert h["source"] == "GloFAS/Open-Meteo"
    assert "Q10" in h["trigger_detail"] and "n=29" in h["trigger_detail"]
    assert "5 km" in h["trigger_detail"]                  # the honesty caveat travels


def test_scan_is_idempotent_within_a_day(live):
    fake_get.forecast_peak = 27.0
    a = scan(live)
    b = scan(live)
    assert a["triggered"][0]["created"] is True
    assert b["triggered"][0]["created"] is False
    assert b["triggered"][0]["hazard_id"] == a["triggered"][0]["hazard_id"]
    assert len(hazard_rows()) == 1


def test_unverified_reaches_are_counted_never_silently_skipped(live):
    with db.conn() as c:
        db.add_object(c, "R2", "river_reach", "Unverified river", 1.03, 34.23,
                      {"tags": {"waterway": "river"}})
        db.add_object(c, "R3", "river_reach", "A hillside stream", 1.04, 34.24,
                      {"tags": {"waterway": "stream"}})
    res = scan(live)
    # R2 is an unverified river: it cannot trigger, and it is named.
    # R3 is a stream: D-036 excludes it from riverine triggers entirely, so it is
    # not a coverage gap and must not be reported as one.
    assert res["unverified"] == 1 and res["unverified_reaches"] == ["R2"]
    assert res["checked"] == 1


def test_scan_to_propagation_end_to_end(live):
    """The whole live chain: forecast -> threshold -> hazard -> impacts."""
    fake_get.forecast_peak = 29.0
    res = scan(live)
    hid = res["triggered"][0]["hazard_id"]
    out = propagate.run(hid)
    assert out["impacts"] > 0
    with db.conn() as c:
        states = {r["object_id"]: r["state"] for r in c.execute(
            "SELECT object_id, state FROM impacts WHERE hazard_id=?", (hid,))}
    assert states["V1"] == "ISOLATED"
    assert states["C1"] == "IMPASSABLE"


def test_the_real_data_files_load_and_are_signed():
    """data/triggers.csv and data/reach_glofas.csv as committed."""
    t = hazards.load_triggers()
    assert [t[("riverine_flood", s)] for s in hazards.SEVERITIES] == [2, 5, 10]
    with open(hazards.REACH_GLOFAS_PATH, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1
    assert rows[0]["reach_id"] == "w188321163"
    assert float(rows[0]["glofas_lat"]) == 0.925
    assert float(rows[0]["glofas_lon"]) == 34.275
    assert rows[0]["verified_by"].strip()
