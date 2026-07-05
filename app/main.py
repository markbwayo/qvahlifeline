"""Qvah LIFELINE - Phase 0/1. Glue + Leaflet map UI. Port 8017.

Phase 1 change: the map now frames whatever is in the graph (fitBounds to the
ingested objects instead of the old seed setView), the header shows the live object
count + source, crossings (type=bridge) are drawn larger with a dark outline so a
sparse crossing set is easy to spot, and popups show structure + OSM id. No change to
hazards, propagation, fragility, or actions.
"""
import json

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from . import actions, db, hazards, propagate
from .ontology import ONTOLOGY_VERSION

app = FastAPI(title="Qvah LIFELINE")
db.init()
if not db.objects():
    db.seed_demo_graph()

ICONS = {"river_reach": "~", "bridge": "=", "road_segment": "-", "settlement": "V",
         "clinic": "+", "school": "S", "water_point": "o"}
COLORS = {"OK": "#166534", "AT_RISK": "#ca8a04", "DEGRADED": "#ca8a04",
          "REROUTED": "#ca8a04", "FLOOD_EXPOSED": "#ea580c",
          "LIKELY_IMPASSABLE": "#dc2626", "SERVICE_AT_RISK": "#ea580c",
          "SEVERED": "#dc2626", "IMPASSABLE": "#7f1d1d", "ISOLATED": "#7f1d1d"}


def state_map():
    with db.conn() as c:
        rows = c.execute(
            "SELECT i.object_id, i.state, i.why_chain_json FROM impacts i "
            "JOIN hazards h ON h.id=i.hazard_id WHERE h.active=1").fetchall()
    return {r["object_id"]: (r["state"], json.loads(r["why_chain_json"])) for r in rows}


@app.get("/", response_class=HTMLResponse)
def home():
    objs = db.objects()
    states = state_map()
    names = {o["id"]: (o["name"] or f"(unnamed {o['type']})") for o in objs}

    features = []
    for o in objs:
        st, chain = states.get(o["id"], ("OK", []))
        chain_txt = " \u2192 ".join(names.get(x, x) for x in chain)
        feat = {
            "id": o["id"], "type": o["type"], "name": names[o["id"]],
            "lat": o["lat"], "lon": o["lon"], "state": st,
            "color": COLORS.get(st, "#166534"), "why": chain_txt,
            "pop": o["props"].get("population", ""),
            "structure": o["props"].get("structure", ""),
            "source": o.get("source", ""),
        }
        # roads and rivers carry line geometry (stored at ingest) -> draw as polylines
        if o["type"] in ("road_segment", "river_reach"):
            g = o["props"].get("geometry")
            if g and len(g) > 1:
                feat["geom"] = g
        features.append(feat)

    # header stats
    n_obj = len(objs)
    sources = sorted({(o.get("source") or "?") for o in objs})
    n_cross = sum(1 for o in objs if o["type"] == "bridge")
    stat_txt = (f"{n_obj} objects · {n_cross} crossings · source: "
                f"{'+'.join(sources)}")

    with db.conn() as c:
        act_rows = c.execute(
            "SELECT a.action_text, a.owner_role, a.lead_time_hrs, o.name, i.state "
            "FROM actions a JOIN impacts i ON i.id=a.impact_id "
            "JOIN objects o ON o.id=i.object_id ORDER BY a.lead_time_hrs").fetchall()
        hz = c.execute("SELECT * FROM hazards WHERE active=1 "
                       "ORDER BY id DESC LIMIT 1").fetchone()

    action_html = "".join(
        f"<tr><td><b>{r['name']}</b><br><span class='st'>{r['state']}</span></td>"
        f"<td>{r['action_text']}</td><td>{r['owner_role']}</td>"
        f"<td>{r['lead_time_hrs']}h</td></tr>" for r in act_rows) or \
        "<tr><td colspan=4>No active hazard. Run the demo.</td></tr>"

    impact_html = "".join(
        f"<li><b>{f['name']}</b> — <span style='color:{f['color']}'>{f['state']}</span>"
        f"<br><span class='why'>why: {f['why']}</span></li>"
        for f in features if f["state"] != "OK") or "<li>All assets OK.</li>"

    hz_txt = (f"ACTIVE: {hz['kind']} / {hz['severity']} — {hz['trigger_detail']} "
              f"(source {hz['source']})") if hz else "No active hazard."

    return f"""<!doctype html><html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Qvah LIFELINE</title>
<link rel='stylesheet' href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'/>
<script src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'></script>
<style>
body{{font-family:Georgia,serif;margin:0;color:#222}}
header{{background:#0b2e18;color:#fff;padding:10px 16px}}
header h1{{margin:0;font-size:18px}} header p{{margin:2px 0 0;font-size:12px;color:#b7d4c0}}
#map{{height:46vh}}
.wrap{{padding:10px 16px}}
.hazard{{background:#fef9c3;border:1px solid #eab308;padding:8px;font-size:13px;margin:8px 0}}
button{{background:#14532d;color:#fff;border:0;padding:8px 16px;margin-right:6px;cursor:pointer}}
button.alt{{background:#7f1d1d}} button.clear{{background:#4b5563}}
table{{border-collapse:collapse;width:100%;font-size:13px;margin-top:6px}}
td,th{{border:1px solid #ccc;padding:5px 7px;text-align:left;vertical-align:top}}
th{{background:#f0f7f1}} .why{{font-size:11px;color:#666;font-style:italic}}
.st{{font-size:11px;color:#b45309}} ul{{padding-left:18px;font-size:13px}}
footer{{font-size:10px;color:#666;padding:8px 16px}}
h3{{color:#14532d;margin:14px 0 4px}}
</style></head><body>
<header><h1>Qvah LIFELINE — ontology-driven early warning</h1>
<p>{ONTOLOGY_VERSION} · {stat_txt} · deterministic core, AI at the edges</p></header>
<div id='map'></div>
<div class='wrap'>
<div class='hazard'>{hz_txt}</div>
<form method='post' action='/demo/alert' style='display:inline'><button>Run demo hazard (alert)</button></form>
<form method='post' action='/demo/emergency' style='display:inline'><button class='alt'>Escalate (emergency)</button></form>
<form method='post' action='/demo/clear' style='display:inline'><button class='clear'>Clear</button></form>
<h3>Impacts (each with its why-chain)</h3><ul>{impact_html}</ul>
<h3>Pre-agreed actions fired from the playbook</h3>
<table><tr><th>Asset</th><th>Action</th><th>Owner</th><th>Lead</th></tr>{action_html}</table>
</div>
<footer>Map data © OpenStreetMap contributors (ODbL) · Hazard feeds (Phase 2): GloFAS
via Open-Meteo, CHIRPS · Elevation: SRTM · Population: WorldPop (CC-BY) · No language
model decides any impact, trigger, or action.</footer>
<script>
var m = L.map('map').setView([0.9065,34.2865],13);
L.tileLayer('https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',
 {{attribution:'© OpenStreetMap contributors'}}).addTo(m);
var fs = {json.dumps(features)};
var lineGroup = L.featureGroup();   // roads + rivers (drawn first, underneath)
var dotGroup = L.featureGroup();    // villages, facilities, crossings (on top)
fs.forEach(function(f){{
  var layer;
  var isLine = (f.type === 'road_segment' || f.type === 'river_reach')
               && f.geom && f.geom.length > 1;
  if (isLine) {{
    var isRiver = f.type === 'river_reach';
    // rivers always blue; roads grey when OK, state colour + thicker when impacted
    var col = isRiver ? '#2563eb' : (f.state === 'OK' ? '#9ca3af' : f.color);
    var wt  = isRiver ? 2.5 : (f.state === 'OK' ? 2 : 4);
    layer = L.polyline(f.geom, {{color: col, weight: wt, opacity: 0.9}});
    layer.addTo(lineGroup);
  }} else {{
    var isBridge = f.type === 'bridge';   // crossings: larger, dark outline
    layer = L.circleMarker([f.lat,f.lon],{{
      radius: isBridge ? 10 : 6,
      color: isBridge ? '#111111' : f.color,
      weight: isBridge ? 3 : 1,
      fillColor: f.color, fillOpacity: 0.85
    }});
    layer.addTo(dotGroup);
  }}
  var pop = '<b>'+f.name+'</b><br>'+f.type
          + (f.structure ? ' ('+f.structure+')' : '')
          + ' — <b style="color:'+f.color+'">'+f.state+'</b>';
  if (f.pop) pop += '<br>population: '+f.pop;
  if (f.why) pop += '<br><i style="font-size:11px">why: '+f.why+'</i>';
  pop += '<br><span style="font-size:10px;color:#999">'+f.id+' · '+f.source+'</span>';
  layer.bindPopup(pop);
  layer.bindTooltip(f.name,{{permanent:false}});
}});
lineGroup.addTo(m);
dotGroup.addTo(m);
try {{
  var b = lineGroup.getBounds();
  if (!b.isValid()) b = dotGroup.getBounds();
  else b.extend(dotGroup.getBounds());
  m.fitBounds(b.pad(0.08));
}} catch(e) {{}}
</script></body></html>"""


@app.post("/demo/alert")
def demo_alert():
    hazards.clear_hazards()
    hid = hazards.demo_flood("alert")
    propagate.run(hid)
    actions.generate(hid)
    return RedirectResponse("/", status_code=303)


@app.post("/demo/emergency")
def demo_emergency():
    hazards.clear_hazards()
    hid = hazards.demo_flood("emergency")
    propagate.run(hid)
    actions.generate(hid)
    return RedirectResponse("/", status_code=303)


@app.post("/demo/clear")
def demo_clear():
    hazards.clear_hazards()
    return RedirectResponse("/", status_code=303)


@app.get("/api/graph")
def api_graph():
    return JSONResponse({"objects": db.objects(), "links": db.links()})


@app.get("/api/impacts")
def api_impacts():
    with db.conn() as c:
        rows = [dict(r) for r in c.execute(
            "SELECT i.*, o.name FROM impacts i JOIN objects o ON o.id=i.object_id")]
    return JSONResponse(rows)
