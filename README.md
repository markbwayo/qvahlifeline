# Qvah LIFELINE — Phase 0 starter

Ontology-driven early warning: named assets (bridges, culverts, roads, clinics,
water points, villages) as objects, dependencies as links, hazards propagating
deterministically through the graph into per-asset impact states — each with a
why-chain — firing pre-agreed playbook actions with owners.

## File map
```
app/main.py       glue + Leaflet map UI (port 8017)
app/ontology.py   type registry + fragility rules (mirrors knowledge/09)
app/db.py         SQLite graph (objects, links) + seed demo corridor
app/propagate.py  THE engine: deterministic BFS, why-chains, invariants
app/actions.py    playbook lookup (data/playbook.csv — committee-owned)
app/hazards.py    demo trigger now; GloFAS/CHIRPS live scan in Phase 2
app/ingest_osm.py Phase 1 module: real OSM assets for the locked pilot bbox
data/playbook.csv object_type x state x hazard -> action, owner, lead time
deploy/           systemd unit + Caddy snippet
```

## Run
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8017
```
Open the page, click **Run demo hazard (alert)**: the culvert goes red, Bumasata
village flags ISOLATED (why-chain: flood -> culvert -> road -> village), Bunamubi
flags REROUTED + FLOOD_EXPOSED, the clinic flags SERVICE_AT_RISK, and the playbook
fires owned actions. **Escalate (emergency)** takes the bridge too — both villages
isolate. **Clear** proves idempotency.

## Hard rules
- No model decides impacts, triggers, or actions. BFS + fragility rules + playbook.
- Seed graph is FICTIONAL demo data until Phase 1 OSM ingestion.
- Attribution: © OpenStreetMap contributors (ODbL); WorldPop CC-BY; SRTM; GloFAS/
  Open-Meteo; CHIRPS.
