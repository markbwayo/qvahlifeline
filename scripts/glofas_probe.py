"""Read-only GloFAS probe. Writes NOTHING to objects, links, hazards or impacts.

Answers the three questions that must be settled before scan_live exists:

  1. WHICH grid cell is a reach? Open-Meteo snaps a request to the centre of a
     ~0.05 deg (~5 km) cell. The demo reach w188321163 is ~4.3 km long and its
     endpoints fall in DIFFERENT cells. So "the reach's GloFAS point" is a choice,
     and the wrong choice drives the demo off a different stretch of water.

  2. WHICH reaches have a signal at all? A cell that reads 0.0 m3/s for its whole
     record is not on GloFAS's modelled channel. Attach it and that reach can
     never raise a hazard - a permanent, per-reach, silent all-clear (this is the
     Isiolo failure of D-004, one reach at a time). Such reaches must be MARKED,
     never quietly skipped.

  3. WHAT is a return-period-relative trigger, numerically? Open-Meteo exposes a
     daily discharge series and NO return periods. We compute them from the 1984-
     onward reanalysis and print both an empirical (Weibull plotting position) and
     a fitted (Gumbel, method of moments) estimate, so the engineer can choose
     which he will defend rather than have a method chosen for him.

Usage (on the VPS):
    .venv/bin/python -m scripts.glofas_probe reach w188321163
    .venv/bin/python -m scripts.glofas_probe survey

Every response is cached in db.geocache, so a re-run costs no requests.
"""
import json
import math
import sys
import time
import urllib.error
import urllib.request

from app import db

API = "https://flood-api.open-meteo.com/v1/flood"
REANALYSIS_START = "1984-01-01"
REANALYSIS_END = "2025-12-31"

# Elgon has two rainy seasons. A calendar-year maximum keeps only the bigger one.
SEASONS = {"Jan-Jun": (1, 6), "Jul-Dec": (7, 12)}


# ------------------------------------------------------------------ fetch + cache

def _get(url, tries=3):
    for i in range(tries):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return json.loads(r.read().decode())
        except (urllib.error.URLError, TimeoutError) as e:
            if i == tries - 1:
                raise
            time.sleep(2 ** i * 3)


def fetch(lat, lon, start=None, end=None, forecast_days=None):
    """Cached GET. Returns the full response dict, including the SNAPPED
    latitude/longitude the API actually served - never the coordinates we asked
    for. Provenance is the snapped cell, always."""
    if forecast_days:
        url = (f"{API}?latitude={lat}&longitude={lon}"
               f"&daily=river_discharge&forecast_days={forecast_days}")
        key = f"glofas:fc{forecast_days}:{lat:.4f},{lon:.4f}:{time.strftime('%Y-%m-%d')}"
    else:
        url = (f"{API}?latitude={lat}&longitude={lon}"
               f"&daily=river_discharge&start_date={start}&end_date={end}")
        key = f"glofas:re:{lat:.4f},{lon:.4f}:{start}:{end}"

    with db.conn() as c:
        row = c.execute("SELECT value_json FROM geocache WHERE key=?", (key,)).fetchone()
        if row:
            return json.loads(row["value_json"])
    data = _get(url)
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?)",
                  (key, json.dumps(data), db.now()))
    return data


def series(data):
    """(dates, values) with nulls dropped."""
    d = data.get("daily") or {}
    t, v = d.get("time") or [], d.get("river_discharge") or []
    pairs = [(a, b) for a, b in zip(t, v) if b is not None]
    return [a for a, _ in pairs], [b for _, b in pairs]


# ------------------------------------------------------------------ flood frequency

def annual_maxima(dates, vals):
    peaks = {}
    for d, v in zip(dates, vals):
        y = d[:4]
        peaks[y] = max(peaks.get(y, 0.0), v)
    return dict(sorted(peaks.items()))


def seasonal_maxima(dates, vals):
    """Two peaks per year, one per rainy season. 2n points instead of n."""
    peaks = {}
    for d, v in zip(dates, vals):
        y, m = d[:4], int(d[5:7])
        for name, (a, b) in SEASONS.items():
            if a <= m <= b:
                k = f"{y}-{name}"
                peaks[k] = max(peaks.get(k, 0.0), v)
    return dict(sorted(peaks.items()))


def weibull_q(peaks, T):
    """Empirical quantile at return period T via the Weibull plotting position
    T = (n+1)/m. No distributional assumption; honest only within the record."""
    x = sorted(peaks, reverse=True)
    n = len(x)
    m = (n + 1) / T
    if m < 1:
        return None                       # T beyond the record: refuse to answer
    if m >= n:
        return x[-1]
    lo = int(math.floor(m))
    frac = m - lo
    return x[lo - 1] + (x[lo] - x[lo - 1]) * frac


def gumbel_q(peaks, T):
    """Gumbel (EV1) by method of moments. Extrapolates beyond the record, at the
    price of assuming the distribution. State the assumption or do not use it."""
    n = len(peaks)
    if n < 2:
        return None
    mean = sum(peaks) / n
    var = sum((v - mean) ** 2 for v in peaks) / (n - 1)
    if var <= 0:
        return mean
    beta = math.sqrt(6) * math.sqrt(var) / math.pi
    u = mean - 0.5772 * beta
    return u - beta * math.log(-math.log(1 - 1 / T))


def describe(peaks, label):
    p = list(peaks.values())
    print(f"\n  {label}: n={len(p)}  min={min(p):.2f}  "
          f"mean={sum(p)/len(p):.2f}  max={max(p):.2f}")
    print(f"    {'T':>4} {'Weibull (empirical)':>22} {'Gumbel (fitted)':>18}")
    for T in (2, 5, 10, 20, 50):
        w, g = weibull_q(p, T), gumbel_q(p, T)
        ws = f"{w:.2f}" if w is not None else "beyond record"
        print(f"    {T:>4} {ws:>22} {g:>18.2f}")
    top = sorted(peaks.items(), key=lambda kv: -kv[1])[:5]
    print("    largest on record:", ", ".join(f"{k}={v:.1f}" for k, v in top))


# ------------------------------------------------------------------ reach -> cells

def reach_cells(reach, samples=5):
    """Distinct GloFAS cells touched by a reach, found by asking the API to snap
    a few vertices. We never assume the grid geometry; the API reports the cell
    centre it served, and that centre is the provenance we would store."""
    geom = reach["props"].get("geometry") or []
    if not geom:
        return []
    idx = sorted({int(i * (len(geom) - 1) / (samples - 1)) for i in range(samples)})
    seen, cells = set(), []
    for i in idx:
        lat, lon = geom[i]
        d = fetch(lat, lon, forecast_days=1)
        snapped = (round(d["latitude"], 5), round(d["longitude"], 5))
        if snapped in seen:
            continue
        seen.add(snapped)
        cells.append({"vertex": i, "asked": (lat, lon), "cell": snapped})
        time.sleep(0.4)
    return cells


def cmd_reach(reach_id):
    objs = {o["id"]: o for o in db.objects()}
    r = objs.get(reach_id)
    if r is None or r["type"] != "river_reach":
        raise SystemExit(f"{reach_id} is not a river_reach in the graph")
    geom = r["props"].get("geometry") or []
    ww = (r["props"].get("tags") or {}).get("waterway")
    print(f"reach {reach_id}  name={r['name']!r}  waterway={ww}  "
          f"{len(geom)} vertices")

    cells = reach_cells(r)
    print(f"\n{len(cells)} DISTINCT GloFAS cell(s) under this one reach:")
    for c in cells:
        print(f"  vertex {c['vertex']:>4}  asked {c['asked'][0]:.4f},{c['asked'][1]:.4f}"
              f"  ->  cell {c['cell'][0]:.5f},{c['cell'][1]:.5f}")
    if len(cells) > 1:
        print("  >>> the reach straddles cells. Which one IS the reach is a decision.")

    for c in cells:
        lat, lon = c["cell"]
        print("\n" + "=" * 72)
        print(f"CELL {lat:.5f},{lon:.5f}   (reach vertex {c['vertex']})")
        d = fetch(lat, lon, REANALYSIS_START, REANALYSIS_END)
        dates, vals = series(d)
        if not vals:
            print("  no data returned")
            continue
        zeros = sum(1 for v in vals if v == 0.0)
        print(f"  reanalysis {dates[0]}..{dates[-1]}  n={len(vals)} days  "
              f"mean={sum(vals)/len(vals):.2f}  max={max(vals):.2f}  "
              f"zeros={zeros} ({100*zeros/len(vals):.1f}%)")
        if max(vals) == 0.0:
            print("  >>> DEAD CELL: 0.0 m3/s across the whole record. Not on the")
            print("      modelled channel. A reach pinned here can NEVER trigger.")
            continue
        describe(annual_maxima(dates, vals), "annual maxima (calendar year)")
        describe(seasonal_maxima(dates, vals), "seasonal maxima (2 per year)")

        fc = fetch(lat, lon, forecast_days=30)
        fd, fv = series(fc)
        if fv:
            am = list(annual_maxima(dates, vals).values())
            print(f"\n  forecast {fd[0]}..{fd[-1]}: max={max(fv):.2f} m3/s "
                  f"on {fd[fv.index(max(fv))]}")
            print(f"    next 7 days max = {max(fv[:7]):.2f}")
            for T in (2, 5, 10):
                q = weibull_q(am, T)
                if q is not None:
                    mark = "EXCEEDS" if max(fv) >= q else "below"
                    print(f"    vs Q{T}(empirical)={q:.2f}  -> {mark}")
        time.sleep(0.5)


def cmd_survey():
    """Cheap signal check across every river reach: one cell, one year. Prints
    which reaches have NO GloFAS signal - the ones that could silently never fire."""
    reaches = [o for o in db.objects() if o["type"] == "river_reach"
               and (o["props"].get("tags") or {}).get("waterway") == "river"]
    print(f"{len(reaches)} waterway=river reaches (streams excluded per D-036)\n")
    cells, dead, live = {}, [], []
    for r in sorted(reaches, key=lambda o: o["id"]):
        geom = r["props"].get("geometry") or []
        if not geom:
            print(f"  {r['id']:<14} NO GEOMETRY")
            continue
        lat, lon = geom[len(geom) // 2]        # midpoint vertex
        d = fetch(lat, lon, "2020-01-01", "2020-12-31")
        cell = (round(d["latitude"], 5), round(d["longitude"], 5))
        _, vals = series(d)
        mx = max(vals) if vals else 0.0
        cells.setdefault(cell, []).append(r["id"])
        (live if mx > 0 else dead).append((r["id"], cell, mx))
        time.sleep(0.4)

    print(f"{len(cells)} distinct cells cover {len(reaches)} reaches\n")
    print(f"LIVE signal ({len(live)}):")
    for rid, cell, mx in live:
        print(f"  {rid:<14} cell {cell[0]:.5f},{cell[1]:.5f}  2020 max={mx:.2f}")
    print(f"\nDEAD - 0.0 m3/s all of 2020 ({len(dead)}):")
    for rid, cell, mx in dead:
        print(f"  {rid:<14} cell {cell[0]:.5f},{cell[1]:.5f}")
    print("\n>>> A dead reach must be MARKED (no_signal), never silently skipped.")
    print(">>> Reaches sharing a cell share a trigger. That is a fact to state,")
    print("    not a bug: GloFAS is ~5 km and the district is ~5 km wide.")


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "survey":
        cmd_survey()
    elif len(sys.argv) == 3 and sys.argv[1] == "reach":
        cmd_reach(sys.argv[2])
    else:
        print("usage: python -m scripts.glofas_probe reach <reach_id> | survey",
              file=sys.stderr)
        raise SystemExit(2)
