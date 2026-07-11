"""Qvah LIFELINE - Phase 2 item 3. Glue + Leaflet map UI. Port 8017.

This module RENDERS. It never decides. Every number on the page is read from the
engine's own tables or from a pure function the engine already uses. Nothing is
re-inferred here, nothing is recomputed with a second algorithm, and no model of
any kind touches this file (hard rule 1).

The read side is where three of this project's bugs have hidden, so the rules it
must obey are stated once, here, and each is locked by a test:

  * ONE HAZARD. Impacts and actions are read for exactly the hazard being
    displayed - the newest active one. The old query joined `actions` to
    `impacts` with no hazard filter at all and rendered 852 rows drawn from five
    different hazards, most of them cleared days earlier. If more than one hazard
    is active the page says so; it never silently blends them.

  * CONSEQUENCE, NOT URGENCY. The action list comes from `actions.actions_for()`,
    which orders by the number of settlements an object is PROVED to have cut off
    (D-045, D-046). Ordered by lead time - as this file used to do - three
    unnamed ford nodes at 12 h print above the B112 deck at 24 h that cuts
    fifty-one villages.

  * NEVER FAIL TOWARD ALL-CLEAR (invariant 6), on the screen as much as in the
    engine. Four ways a page can lie by omission, all of them closed here:
      - an unknown state falling back to the OK green (COLORS is checked at
        import against STATE_ORDER, and a miss raises rather than renders green);
      - an impact with no action rendering as a red village with an empty action
        column, indistinguishable from "nothing to do" -> the coverage panel is
        ALWAYS rendered, and names every uncovered impact, including when there
        are none;
      - a disabled or failed GloFAS scan rendering as a calm river -> the scan
        banner distinguishes "not run", "disabled", "feed down" and "quiet";
      - a nameless crossing rendering as "(unnamed bridge)" - the same string for
        thirty-two different objects, one of which cuts off eight settlements ->
        a crossing with no name is labelled by its object id (09, v0.9).
"""
import json
import traceback
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import actions, ai_edge, approvals, db, hazards, messages, propagate
from .ontology import ONTOLOGY_VERSION, STATE_ORDER

SCAN_KEY = "ui:last_scan"      # geocache row: the last scan attempt (02: no in-memory truth)

COLORS = {
    "OK": "#166534",
    "AT_RISK": "#ca8a04",
    "DEGRADED": "#ca8a04",
    "REROUTED": "#ca8a04",
    "FLOOD_EXPOSED": "#ea580c",
    "SERVICE_AT_RISK": "#ea580c",
    "LIKELY_IMPASSABLE": "#dc2626",
    "SEVERED": "#dc2626",
    "IMPASSABLE": "#7f1d1d",
    "ISOLATED": "#7f1d1d",
}

# A state the palette does not know must never inherit the OK green. `.get(st,
# green)` did exactly that: add a state to the ontology, forget the colour, and
# an ISOLATED village renders as a healthy one. Fail at import instead.
_missing = [s for s in STATE_ORDER if s not in COLORS]
if _missing:
    raise RuntimeError(
        f"COLORS has no colour for {_missing}. A state with no colour would "
        f"render as OK green - a false all-clear on the map (invariant 6).")
if [s for s in STATE_ORDER if s != "OK" and COLORS[s] == COLORS["OK"]]:
    raise RuntimeError("a non-OK state shares the OK colour")

FLOODED_REACH_COLOR = "#1e3a8a"    # the channel actually in flood
RIVER_COLOR = "#60a5fa"            # every other watercourse
ROAD_OK_COLOR = "#9ca3af"


@asynccontextmanager
async def _lifespan(_app):
    """Schema + seed at startup, not at import. Importing this module must have
    no side effect on the database, or a test cannot point it at a temp file."""
    db.init()
    if not db.objects():
        db.seed_demo_graph()
    yield


app = FastAPI(title="Qvah LIFELINE", lifespan=_lifespan)


# --------------------------------------------------------------------- reads

def label(oid, name):
    """A crossing with no OSM name and no operator row keeps its object id as its
    label (09, v0.9). `(unnamed bridge)` was the same string for thirty-two
    objects; `w747829218` is at least the one the why-chain names."""
    return name if (name or "").strip() else oid


def active_hazards(c):
    return [dict(r) for r in c.execute(
        "SELECT * FROM hazards WHERE active=1 ORDER BY id DESC")]


def impact_map(c, hazard_id):
    """object_id -> (state, why_chain) for ONE hazard. Never a join across all."""
    if hazard_id is None:
        return {}
    rows = c.execute(
        "SELECT object_id, state, why_chain_json FROM impacts WHERE hazard_id=? "
        "ORDER BY object_id", (hazard_id,)).fetchall()
    return {r["object_id"]: (r["state"], json.loads(r["why_chain_json"])) for r in rows}


def coverage(hazard_id):
    """Which impacts of this hazard have no action beside them, and why.

    Two different failures wear the same face on screen - a red asset with an
    empty action column:
      * `uncovered` - the playbook has no row for (object_type, state, kind).
        Legitimate: the committee may choose not to act on `bridge AT_RISK`.
        It may never do so invisibly (D-044).
      * `unfired`   - the playbook HAS a row and no action exists anyway. That is
        a bug, not a choice, and it is rendered as one.
    """
    empty = {"impacts": 0, "uncovered": [], "unfired": [], "error": None}
    if hazard_id is None:
        return empty
    try:
        covered = actions.covered_triples()
    except Exception as e:                       # noqa: BLE001 - shown, not swallowed
        return dict(empty, error=f"{type(e).__name__}: {e}")

    with db.conn() as c:
        hz = c.execute("SELECT kind FROM hazards WHERE id=?", (hazard_id,)).fetchone()
        if hz is None:
            return empty
        rows = c.execute(
            "SELECT i.id, i.object_id, i.state, o.type AS otype, o.name, "
            "(SELECT COUNT(*) FROM actions a WHERE a.impact_id=i.id) AS n "
            "FROM impacts i JOIN objects o ON o.id=i.object_id "
            "WHERE i.hazard_id=? ORDER BY i.object_id", (hazard_id,)).fetchall()

    uncovered, unfired = [], []
    for r in rows:
        if r["n"]:
            continue
        item = {"object_id": r["object_id"], "label": label(r["object_id"], r["name"]),
                "object_type": r["otype"], "state": r["state"]}
        triple = (r["otype"], r["state"], hz["kind"])
        (uncovered if triple not in covered else unfired).append(item)
    return {"impacts": len(rows), "uncovered": uncovered, "unfired": unfired,
            "error": None}


def save_scan(result):
    with db.conn() as c:
        c.execute("INSERT OR REPLACE INTO geocache VALUES (?,?,?)",
                  (SCAN_KEY, json.dumps(result), db.now()))


def load_scan():
    with db.conn() as c:
        row = c.execute("SELECT value_json, fetched_utc FROM geocache WHERE key=?",
                        (SCAN_KEY,)).fetchone()
    if not row:
        return None
    out = json.loads(row["value_json"])
    out["_at"] = row["fetched_utc"]
    return out


def flooded_set(objs_by_id, hz):
    """The reaches this hazard actually floods - from the engine's own function,
    not a second implementation of it."""
    if not hz:
        return set()
    return propagate.flooded_reaches(objs_by_id, hz["target_id"],
                                     hz.get("scope") or "reach")


# --------------------------------------------------------------- broadcast reads

def broadcast_panel(hazard_id):
    """Everything the last-mile layer needs to render, and NOT ONE network call.

    A live Gemini translation is 4-6 s of generation (measured, D-060). Sixty-two
    villages in a page render is five minutes of blocking. So this reader:
      * gets the English broadcasts and the gaps from `messages.messages_for`
        (pure DB, one CSV load per page via the `book=` path);
      * reads the Lumasaba gap the same way - `missing` is committee data nobody
        has written yet, shown by village name (D-052);
      * looks up any Swahili DRAFT that ALREADY EXISTS in the cache via
        `ai_edge.cached_draft` - read-only, ungated, no provider (D-060);
      * reads standing approvals from the `approvals` table, keyed to the exact
        draft bytes (a re-translation under a changed prompt is not pre-approved).

    A village whose Swahili is not cached shows a Draft button, which is the only
    place a provider call happens - behind a click, never in a page load.
    """
    if hazard_id is None:
        return None
    en = messages.messages_for(hazard_id, "en")
    lum = messages.messages_for(hazard_id, "lum")
    signed = approvals.approved_for(hazard_id, "sw")

    villages, crossings = [], []
    for m in en["messages"]:
        draft = ai_edge.cached_draft(m["text"], "sw")   # dict | None, no network
        sw_text = draft["draft"] if draft and draft["status"] == "DRAFT" else None
        row = {
            "impact_id": m["impact_id"], "object_id": m["object_id"],
            "label": label(m["object_id"], m.get("facts", {}).get("settlement")
                           or m.get("facts", {}).get("crossing") or m["object_id"]),
            "state": m["state"], "en": m["text"], "cap": m["cap"],
            "needs_name": bool(m["crossing_id"] and not m["crossing_named"]),
            "crossing_id": m["crossing_id"],
            "sw": sw_text,
            # approval is over the SWAHILI bytes, so it moves if the draft moves
            "approved": bool(sw_text and m["impact_id"] in signed
                             and signed[m["impact_id"]]["text_hash"]
                             == approvals.text_hash(sw_text)),
        }
        (villages if m["object_type"] == "settlement" else crossings).append(row)

    return {
        "hazard_id": hazard_id,
        "villages": villages, "crossings": crossings,
        "en_count": len(en["messages"]),
        "lum_missing": [m["label"] for m in lum["missing"]],
        "errors": en["errors"],
        "needs_name": en["needs_name"],
        "not_broadcast": en["not_broadcast"],
    }


# ------------------------------------------------------------------ rendering

def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def chain_html(chain, names):
    """Render one why-chain. Three element kinds are not object ids and must not
    be silently looked up as such."""
    out = []
    for x in chain:
        if x.startswith("hazard:"):
            out.append(f"<span class='ch-h'>{esc(x)}</span>")
        elif x.startswith("assumed_structure:"):
            # D-027. The engine assumed a structure because nobody classified the
            # crossing. That admission is part of the impact and is never hidden.
            out.append(f"<span class='ch-a'>{esc(x)}</span>")
        elif x.startswith("alternate_via:"):
            roads = x.split(":", 1)[1].split(">")
            out.append("<span class='ch-alt'>alternate via "
                       + " &rsaquo; ".join(esc(names.get(r, r)) for r in roads)
                       + "</span>")
        else:
            out.append(f"<span class='ch-o'>{esc(names.get(x, x))}</span>")
    return " <b>&rarr;</b> ".join(out)


def scan_html(scan):
    """'No hazard' and 'we could not look' must never render identically."""
    if scan is None:
        return ("<div class='sc grey'>GloFAS scan has not been run in this "
                "deployment. This is not an all-clear: the feed has not been "
                "consulted.</div>")
    at = esc(scan.get("_at", ""))
    st = scan.get("status", "")
    if st == "FEED FAILURE":
        return (f"<div class='sc red'><b>GLOFAS FEED FAILURE</b> at {at}. The "
                f"river was not read. This is not an all-clear.<br>"
                f"<code>{esc(scan.get('error', ''))}</code></div>")
    if st.startswith("live scan disabled"):
        return (f"<div class='sc yellow'><b>LIVE SCAN DISABLED</b> (USE_LIVE=0), "
                f"checked {at}. The forecast was not consulted. The demo runs the "
                f"hazard from the graph, not from the feed (D-008).</div>")
    trig = scan.get("triggered") or []
    if trig:
        bits = ", ".join(
            f"{esc(t['reach_id'])}: <b>{esc(t['severity'])}</b> "
            f"(peak {t['peak']:.2f} &ge; {t['threshold']:.2f} m&sup3;/s)" for t in trig)
        return (f"<div class='sc red'><b>GLOFAS TRIGGERED</b> at {at} &mdash; "
                f"{bits}. Unverified river reaches: {scan.get('unverified')}.</div>")
    quiet = scan.get("quiet") or []
    q = "; ".join(
        f"{esc(x['reach_id'])} peak {x['peak']:.2f} m&sup3;/s vs watch "
        f"{x['watch_threshold']:.2f}" for x in quiet)
    return (f"<div class='sc green'><b>GloFAS read, river quiet</b> at {at} &mdash; "
            f"{q or 'no verified points'}. {scan.get('checked', 0)} verified "
            f"point(s) checked; {scan.get('unverified')} river reaches carry no "
            f"verified GloFAS cell and cannot trigger.</div>")


def _msg_row(r):
    """One broadcast. The Swahili is a DRAFT until a human signs THESE bytes; a
    row that failed the edge's sanity check is REJECTED, never DRAFT (D-056)."""
    cap = r["cap"]
    head = (f"<td><b>{esc(r['label'])}</b>"
            f"<br><span class='st'>{esc(r['state'])} &middot; CAP "
            f"{esc(cap['severity'])}/{esc(cap['certainty'])}/{esc(cap['urgency'])}</span>"
            + ("<span class='nn'>bare crossing id &mdash; only an operator with "
               "satellite imagery can name it (data/operator_crossings.csv)</span>"
               if r["needs_name"] else "") + "</td>")
    en = f"<td>{esc(r['en'])}</td>"

    if r["sw"]:
        badge = ("<span class='badge' style='background:#166534'>APPROVED</span>"
                 if r["approved"] else
                 "<span class='badge' style='background:#b45309'>DRAFT — not approved</span>")
        sw = f"<td>{esc(r['sw'])}<br>{badge}</td>"
        if r["approved"]:
            act = "<td class='ok'>signed</td>"
        else:
            act = (f"<td><form method='post' action='/approve/{r['impact_id']}'>"
                   f"<button class='sm'>Approve</button></form></td>")
    else:
        # no cached draft: the only place a provider call may originate, and it is
        # behind a click (4-6 s), never in the page load.
        sw = "<td class='muted'>no Swahili draft yet</td>"
        act = (f"<td><form method='post' action='/draft/{r['impact_id']}'>"
               f"<button class='sm scan'>Draft Swahili</button></form></td>")
    return f"<tr>{head}{en}{sw}{act}</tr>"


def broadcast_html(bp):
    if bp is None:
        return "<div class='sc grey'>No active hazard: no broadcasts to send.</div>"
    parts = [f"<div class='sum'><b>{bp['en_count']}</b> English broadcasts ready "
             f"&middot; {bp['not_broadcast']} impact(s) correctly not broadcast "
             f"(a severed road or a service-at-risk facility needs a task, not a "
             f"village warning).</div>"]

    if bp["errors"]:
        parts.append("<div class='sc red'><b>BUG: a template exists and the facts "
                     "would not fill it.</b> "
                     + ", ".join(f"{esc(e['label'])}: {esc(e['error'])}"
                                 for e in bp["errors"]) + "</div>")

    # Lumasaba: committee data nobody has written yet. A gap, shown by name (D-052).
    if bp["lum_missing"]:
        parts.append(
            "<div class='sc yellow'><b>Lumasaba not yet written &mdash; "
            f"{len(bp['lum_missing'])} broadcast(s) have no template in the language "
            "that reaches the last mile.</b> This is committee data, authored in "
            "data/messages.csv, never generated by a model. Until it is written these "
            "villages are warned in English: "
            + ", ".join(esc(v) for v in bp["lum_missing"]) + "</div>")
    else:
        parts.append("<div class='sc green'>Every broadcast has a Lumasaba "
                     "template.</div>")

    # needs_name: an operator task list, not an error (D-055).
    if bp["needs_name"]:
        parts.append(
            "<div class='sc yellow'><b>Crossings broadcast as a bare OSM id "
            "&mdash; an operator task, not a code fix.</b> A way id read aloud to a "
            "chief is not a warning. Name each in data/operator_crossings.csv: "
            + ", ".join(f"<code>{esc(n['crossing_id'])}</code> ({n['broadcasts']} "
                        f"broadcast{'s' if n['broadcasts'] != 1 else ''})"
                        for n in bp["needs_name"]) + "</div>")

    def _table(rows, title):
        if not rows:
            return ""
        body = "".join(_msg_row(r) for r in rows)
        return (f"<h3>{title}</h3><table><tr><th>Audience</th><th>English "
                f"(committee template, engine facts)</th><th>Swahili "
                f"(AI edge &mdash; DRAFT)</th><th></th></tr>{body}</table>")

    parts.append(_table(bp["villages"], "Village broadcasts"))
    parts.append(_table(bp["crossings"], "Crossing closure notices"))
    return "".join(parts)


@app.get("/", response_class=HTMLResponse)
def home():
    objs = db.objects()
    objs_by_id = {o["id"]: o for o in objs}
    names = {o["id"]: label(o["id"], o["name"]) for o in objs}

    with db.conn() as c:
        actives = active_hazards(c)
        hz = actives[0] if actives else None
        states = impact_map(c, hz["id"] if hz else None)

    flooded = flooded_set(objs_by_id, hz)

    features = []
    for o in sorted(objs, key=lambda x: x["id"]):
        st, chain = states.get(o["id"], ("OK", []))
        f = {"id": o["id"], "type": o["type"], "name": names[o["id"]],
             "lat": o["lat"], "lon": o["lon"], "state": st, "color": COLORS[st],
             "why": chain_html(chain, names) if chain else "",
             "structure": o["props"].get("structure") or "",
             "source": o.get("source") or "",
             "flooded": o["id"] in flooded}
        if o["type"] in ("road_segment", "river_reach"):
            g = o["props"].get("geometry")
            if g and len(g) > 1:
                f["geom"] = g
        features.append(f)

    # ---- header
    n_cross = sum(1 for o in objs if o["type"] == "bridge")
    srcs = "+".join(sorted({(o.get("source") or "?") for o in objs}))
    stat = f"{len(objs)} objects &middot; {n_cross} crossings &middot; source: {esc(srcs)}"

    # ---- hazard banner
    if hz:
        hz_html = (f"<div class='hz on'><b>ACTIVE HAZARD #{hz['id']}</b>: "
                   f"{esc(hz['kind'])} / <b>{esc(hz['severity'])}</b>, scope "
                   f"<b>{esc(hz.get('scope') or 'reach')}</b> on "
                   f"{esc(names.get(hz['target_id'], hz['target_id']))} "
                   f"&mdash; {len(flooded)} reaches in flood"
                   f"<br><span class='sub'>{esc(hz['trigger_detail'])} "
                   f"(source {esc(hz['source'])})</span></div>")
    else:
        hz_html = ("<div class='hz off'>No active hazard. The graph is loaded and no "
                   "flood is being propagated. Run a trigger below.</div>")
    if len(actives) > 1:
        hz_html += (f"<div class='sc red'><b>{len(actives)} HAZARDS ARE ACTIVE.</b> "
                    f"This page shows only #{actives[0]['id']}. Impacts from "
                    f"different hazards are never blended. Clear, then re-run.</div>")

    # ---- impacts, worst first, then deterministic by id (invariant 1)
    imp = [f for f in features if f["state"] != "OK"]
    imp.sort(key=lambda f: (-STATE_ORDER.index(f["state"]), f["id"]))
    counts = {}
    for f in imp:
        counts[f["state"]] = counts.get(f["state"], 0) + 1
    summary = " &middot; ".join(
        f"<b style='color:{COLORS[s]}'>{counts[s]} {s}</b>"
        for s in reversed(STATE_ORDER) if s in counts) or "all assets OK"

    impact_html = "".join(
        f"<li><b>{esc(f['name'])}</b> "
        f"<span class='badge' style='background:{f['color']}'>{f['state']}</span>"
        f"<div class='why'>{f['why']}</div></li>" for f in imp) \
        or "<li>All assets OK.</li>"

    # ---- actions: consequence first (D-045/046), read through the module API
    rows = actions.actions_for(hz["id"]) if hz else []
    prec = sum(1 for a in rows if a["precautionary"])
    act_html = "".join(
        "<tr>"
        f"<td><b>{esc(label(a['object_id'], a['object_name']))}</b>"
        f"<br><span class='st'>{esc(a['object_type'])} &middot; {esc(a['state'])}</span></td>"
        f"<td class='num'>{a['consequence']}</td>"
        f"<td>{esc(a['action_text'])}"
        + ("<span class='prec'>precautionary &mdash; no settlement in this graph "
           "loses a route through it. The action still stands: a flooded crossing "
           "endangers whoever drives into it, and a gap in our road data may never "
           "silence a warning.</span>" if a["precautionary"] else "")
        + f"</td><td>{esc(a['owner_role'])}</td>"
        f"<td class='num'>{a['lead_time_hrs']}h</td>"
        f"<td class='num'>{'' if a['carriers'] is None else a['carriers']}</td></tr>"
        for a in rows) or "<tr><td colspan=6>No active hazard. Run a trigger.</td></tr>"

    # ---- coverage: always rendered, including when it is clean
    cov = coverage(hz["id"] if hz else None)
    if cov["error"]:
        cov_html = (f"<div class='sc red'><b>PLAYBOOK WILL NOT LOAD</b> &mdash; no "
                    f"action coverage can be claimed for this hazard.<br>"
                    f"<code>{esc(cov['error'])}</code></div>")
    elif not hz:
        cov_html = "<div class='sc grey'>No hazard: no impacts to cover.</div>"
    else:
        n_cov = cov["impacts"] - len(cov["uncovered"]) - len(cov["unfired"])
        parts = [f"<b>{n_cov} of {cov['impacts']}</b> impacts carry at least one "
                 f"pre-agreed action. {prec} of {len(rows)} actions are "
                 f"precautionary."]
        if cov["unfired"]:
            parts.append("<div class='sc red'><b>BUG: the playbook has a row for "
                         "these impacts and no action was fired.</b> "
                         + ", ".join(f"{esc(u['label'])} ({esc(u['state'])})"
                                     for u in cov["unfired"]) + "</div>")
        if cov["uncovered"]:
            parts.append("<div class='sc yellow'><b>UNCOVERED &mdash; the playbook "
                         "has no row for these, so no action is proposed. That is a "
                         "committee decision, not an all-clear:</b> "
                         + ", ".join(f"{esc(u['label'])} &mdash; {esc(u['object_type'])} "
                                     f"{esc(u['state'])}" for u in cov["uncovered"])
                         + "</div>")
        else:
            parts.append(" <span class='ok'>Every impact of this hazard carries at "
                         "least one action.</span>")
        cov_html = f"<div class='sc grey'>{''.join(parts)}</div>"

    # ---- broadcasts: read-only, no network in this page render (D-060)
    try:
        bcast_html = broadcast_html(broadcast_panel(hz["id"] if hz else None))
    except Exception as e:                       # noqa: BLE001 - shown, not swallowed
        bcast_html = (f"<div class='sc red'><b>BROADCAST PANEL ERROR</b> &mdash; the "
                      f"message layer could not be read. This is not an all-clear.<br>"
                      f"<code>{esc(type(e).__name__)}: {esc(e)}</code></div>")

    legend = "".join(f"<span class='lg'><i style='background:{COLORS[s]}'></i>{s}</span>"
                     for s in STATE_ORDER)

    js = (_JS.replace("__FEATURES__", json.dumps(features))
             .replace("__FLOODCOL__", FLOODED_REACH_COLOR)
             .replace("__RIVERCOL__", RIVER_COLOR)
             .replace("__ROADCOL__", ROAD_OK_COLOR))

    return (_PAGE.replace("__ONTOLOGY__", esc(ONTOLOGY_VERSION))
                 .replace("__PLAYBOOK__", esc(actions.PLAYBOOK_VERSION))
                 .replace("__STAT__", stat)
                 .replace("__HAZARD__", hz_html)
                 .replace("__SCAN__", scan_html(load_scan()))
                 .replace("__SUMMARY__", summary)
                 .replace("__LEGEND__", legend)
                 .replace("__COVERAGE__", cov_html)
                 .replace("__IMPACTS__", impact_html)
                 .replace("__ACTIONS__", act_html)
                 .replace("__BROADCAST__", bcast_html)
                 .replace("__JS__", js))


# ------------------------------------------------------------------- endpoints

def run_demo(severity):
    """Demo trigger. scope=river, ALWAYS (D-036): a GloFAS spike raises the whole
    connected channel, not one OSM way. At reach scope the pilot graph reports 0
    ISOLATED and 43 REROUTED - villages detouring over crossings that the same
    flood closes. This file used to call demo_flood(), whose scope defaults to
    'reach', so every button press under-warned."""
    hazards.clear_hazards()
    hid = hazards.demo_flood_river(severity)
    propagate.run(hid)
    actions.fire_actions(hid)
    return hid


@app.post("/demo/alert")
def demo_alert():
    run_demo("alert")
    return RedirectResponse("/", status_code=303)


@app.post("/demo/emergency")
def demo_emergency():
    run_demo("emergency")
    return RedirectResponse("/", status_code=303)


@app.post("/demo/clear")
def demo_clear():
    hazards.clear_hazards()
    return RedirectResponse("/", status_code=303)


@app.post("/scan")
def scan():
    """Run the live GloFAS scan and RECORD what happened, whatever happened.

    hazards.scan_live() raises on every feed failure, by design (D-047). The
    engine must raise; the page must not disappear. So the exception is caught
    here at the presentation boundary and rendered as a red FEED FAILURE banner.
    It is never converted into an empty result - that is the conversion that
    makes a dead feed look like a calm river.
    """
    try:
        res = hazards.scan_live()
    except Exception as e:                       # noqa: BLE001 - displayed, not swallowed
        save_scan({"status": "FEED FAILURE", "error": f"{type(e).__name__}: {e}",
                   "trace": traceback.format_exc()[-800:]})
        return RedirectResponse("/", status_code=303)

    for t in res.get("triggered") or []:
        if t.get("created"):
            propagate.run(t["hazard_id"])
            actions.fire_actions(t["hazard_id"])
    save_scan(res)
    return RedirectResponse("/", status_code=303)


@app.post("/draft/{impact_id}")
def draft(impact_id: int):
    """Ask the edge for ONE Swahili draft, then redirect. This is the only route
    that reaches a provider (4-6 s, D-060), and it does so for one impact behind a
    click - never for 62 villages in a page load. The edge caches the result, so a
    second click on the same text is free. Any failure (dead net, bad key, 4xx)
    returns a status and is shown on the next render; it never raises here, because
    a dead translator costs a convenience, not a warning (D-058)."""
    try:
        m = messages.render(impact_id, "en")
        ai_edge.draft_swahili(m)                 # writes to cache on success; harmless on failure
    except messages.MessageError:
        pass                                     # a village with no template gets no draft; the gap is already shown
    return RedirectResponse("/", status_code=303)


@app.post("/approve/{impact_id}")
def approve(impact_id: int):
    """A human signs the CURRENT cached Swahili draft for this impact. The signature
    is over the exact bytes (approvals.text_hash), so it does not carry over to a
    re-translation under a changed prompt. If no draft is cached, nothing is signed
    and the page still renders - approval of a thing that does not exist is not a
    silent success."""
    try:
        m = messages.render(impact_id, "en")
        d = ai_edge.cached_draft(m["text"], "sw")
        if d and d["status"] == "DRAFT" and d["draft"]:
            approvals.approve(impact_id, "sw", d["draft"])
    except messages.MessageError:
        pass
    return RedirectResponse("/", status_code=303)


@app.get("/api/graph")
def api_graph():
    return JSONResponse({"objects": db.objects(), "links": db.links()})


@app.get("/api/impacts")
def api_impacts():
    with db.conn() as c:
        actives = active_hazards(c)
        hid = actives[0]["id"] if actives else None
        rows = [dict(r) for r in c.execute(
            "SELECT i.*, o.name, o.type FROM impacts i JOIN objects o "
            "ON o.id=i.object_id WHERE i.hazard_id=? ORDER BY i.object_id",
            (hid,))] if hid else []
    return JSONResponse({"hazard_id": hid, "active_hazards": len(actives),
                         "impacts": rows})


@app.get("/api/actions")
def api_actions():
    with db.conn() as c:
        actives = active_hazards(c)
    if not actives:
        return JSONResponse({"hazard_id": None, "actions": [], "coverage": None})
    hid = actives[0]["id"]
    return JSONResponse({"hazard_id": hid, "actions": actions.actions_for(hid),
                         "coverage": coverage(hid)})


@app.get("/api/scan")
def api_scan():
    return JSONResponse(load_scan() or {"status": "never run"})


# ----------------------------------------------------------------- the template

_JS = """
var m = L.map('map');
L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',
 {attribution:'© OpenStreetMap contributors'}).addTo(m);
var fs = __FEATURES__;
var lineGroup = L.featureGroup();
var dotGroup = L.featureGroup();
fs.forEach(function(f){
  var layer;
  var isLine = (f.type === 'road_segment' || f.type === 'river_reach')
               && f.geom && f.geom.length > 1;
  if (isLine) {
    var col, wt;
    if (f.type === 'river_reach') {
      col = f.flooded ? '__FLOODCOL__' : '__RIVERCOL__';
      wt  = f.flooded ? 5 : 2;
    } else {
      col = (f.state === 'OK') ? '__ROADCOL__' : f.color;
      wt  = (f.state === 'OK') ? 2 : 5;
    }
    layer = L.polyline(f.geom, {color: col, weight: wt, opacity: 0.9});
    layer.addTo(lineGroup);
  } else {
    var isBridge = f.type === 'bridge';
    layer = L.circleMarker([f.lat,f.lon],{
      radius: isBridge ? 9 : 5,
      color: isBridge ? '#111111' : f.color,
      weight: isBridge ? 3 : 1,
      fillColor: f.color, fillOpacity: 0.9
    });
    layer.addTo(dotGroup);
  }
  var pop = '<b>'+f.name+'</b><br>'+f.type
          + (f.structure ? ' ('+f.structure+')' : '')
          + ' — <b style="color:'+f.color+'">'+f.state+'</b>';
  if (f.why) pop += '<div style="font-size:11px;margin-top:4px">'+f.why+'</div>';
  pop += '<br><span style="font-size:10px;color:#999">'+f.id+' · '+f.source+'</span>';
  layer.bindPopup(pop, {maxWidth: 420});
  layer.bindTooltip(f.name);
});
lineGroup.addTo(m);
dotGroup.addTo(m);
try {
  var b = lineGroup.getBounds();
  if (!b.isValid()) b = dotGroup.getBounds();
  else b.extend(dotGroup.getBounds());
  m.fitBounds(b.pad(0.08));
} catch(e) { m.setView([0.9406,34.2802],13); }
"""

_PAGE = """<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Qvah LIFELINE</title>
<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'/>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<style>
body{font-family:Georgia,serif;margin:0;color:#222}
header{background:#0b2e18;color:#fff;padding:10px 16px}
header h1{margin:0;font-size:18px} header p{margin:2px 0 0;font-size:12px;color:#b7d4c0}
#map{height:52vh}
.wrap{padding:10px 16px;max-width:1200px}
.hz{padding:9px 11px;font-size:13px;margin:8px 0;border-left:5px solid}
.hz.on{background:#fef2f2;border-color:#dc2626}
.hz.off{background:#f0f7f1;border-color:#166534}
.hz .sub{font-size:11px;color:#555}
.sc{padding:8px 11px;font-size:12px;margin:6px 0;border-left:5px solid}
.sc.red{background:#fef2f2;border-color:#dc2626}
.sc.yellow{background:#fef9c3;border-color:#eab308}
.sc.green{background:#f0fdf4;border-color:#166534}
.sc.grey{background:#f6f6f6;border-color:#9ca3af}
.sc code{font-size:11px;color:#7f1d1d}
.ok{color:#166534}
button{background:#14532d;color:#fff;border:0;padding:8px 14px;margin-right:6px;
  cursor:pointer;font-family:Georgia,serif;font-size:13px}
button.alt{background:#7f1d1d} button.scan{background:#1e3a8a} button.clear{background:#4b5563}
.cap{font-size:11px;color:#555;margin:6px 0 0;font-style:italic;max-width:900px}
table{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}
td,th{border:1px solid #ccc;padding:5px 7px;text-align:left;vertical-align:top}
th{background:#f0f7f1} td.num{text-align:right;white-space:nowrap}
.st{font-size:11px;color:#b45309}
.prec{display:block;font-size:11px;color:#666;font-style:italic;margin-top:3px}
ul{padding-left:18px;font-size:13px} li{margin-bottom:5px}
.badge{color:#fff;font-size:10px;padding:1px 5px;border-radius:2px}
.why{font-size:11px;color:#555;margin-top:2px}
.ch-h{color:#1e3a8a} .ch-o{color:#222}
.ch-a{background:#fef9c3;border:1px solid #eab308;padding:0 3px}
.ch-alt{color:#b45309}
button.sm{padding:4px 9px;font-size:11px;margin:0}
.nn{display:block;font-size:10px;color:#b45309;font-style:italic;margin-top:3px}
.muted{color:#999;font-style:italic}
.lg{font-size:10px;margin-right:9px;white-space:nowrap}
.lg i{display:inline-block;width:9px;height:9px;margin-right:3px}
footer{font-size:10px;color:#666;padding:10px 16px;border-top:1px solid #ddd;margin-top:14px}
h3{color:#14532d;margin:14px 0 4px;font-size:15px}
.sum{font-size:13px;margin:6px 0}
</style></head><body>
<header><h1>Qvah LIFELINE — ontology-driven early warning</h1>
<p>__ONTOLOGY__ · __PLAYBOOK__ · __STAT__ · deterministic core, AI at the edges</p></header>
<div id='map'></div>
<div class='wrap'>
__HAZARD__
__SCAN__
<form method='post' action='/demo/alert' style='display:inline'><button>Watch-level trigger (alert = Q5)</button></form>
<form method='post' action='/demo/emergency' style='display:inline'><button class='alt'>Emergency trigger (Q10)</button></form>
<form method='post' action='/scan' style='display:inline'><button class='scan'>Run live GloFAS scan</button></form>
<form method='post' action='/demo/clear' style='display:inline'><button class='clear'>Clear</button></form>
<p class='cap'>At <b>alert</b> — the Q5 flow — five crossings go likely-impassable:
the fords, and the crossings nobody has classified, which we score as the <i>most</i>
fragile structure, never the least. Not one settlement loses its road to a clinic. That
is the fragility table refusing to cry wolf. <b>Emergency</b> is the Q10 flow: 19.37 m³/s,
reached in 1997, 1998 and 2002.</p>
<div class='sum'>__SUMMARY__</div>
<div>__LEGEND__</div>
<h3>Action coverage</h3>
__COVERAGE__
<h3>Pre-agreed actions — ordered by consequence, not by urgency</h3>
<table><tr><th>Asset</th><th>Villages<br>cut off</th><th>Action</th><th>Owner</th>
<th>Lead</th><th>Carrier<br>roads</th></tr>__ACTIONS__</table>
<h3>Impacts, each with its why-chain</h3>
<ul>__IMPACTS__</ul>
<h3>Broadcast messages — committee words, engine facts, no model in the loop</h3>
<p class='cap'>The English is a committee template with slots the engine fills from
each impact's own why-chain. Lumasaba is authored by hand and never generated (it is
the language nobody in the room can audit). The Swahili is the one thing a model
touches here — a DRAFT, never sent until a human approves these exact words.</p>
__BROADCAST__
</div>
<footer>Map data © OpenStreetMap contributors (ODbL) · River discharge: GloFAS via the
Open-Meteo flood API · No language model decides any impact, trigger, or action:
impacts come from versioned fragility rules over the link graph, actions from the
committee's playbook table, verbatim.</footer>
<script>__JS__</script></body></html>"""
