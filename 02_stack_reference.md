# 02 — Stack & Workflow Reference

## VPS and layout
- Contabo VPS, Ubuntu 24, ~8 GB RAM, IP 161.97.147.210, user `operator`. Sunk cost —
  LIFELINE adds ~$0/month.
- Project root **`/opt/lifeline/`**, repo `markbwayo/qvahlifeline`, port **8017**
  (Passport 8011, CarbonProof 8012, TitleProof 8013, TaxProof 8014, FundProof 8015,
  IrriProof 8016 — don't collide).
- **Git only**: Git Bash on Windows → GitHub → `git pull` on VPS. No WinSCP.

## Stack
- **API/UI:** FastAPI + uvicorn; single-page UI with **Leaflet via CDN** over free OSM
  tiles (attribution required and included). No frontend framework.
- **Store:** SQLite (`data/lifeline.db`). The graph lives in two tables (objects,
  links) — plenty for a district-scale graph (thousands of nodes); no graph DB.
- **Graph logic:** pure-Python BFS/DFS in `propagate.py`. No networkx needed at MVP
  scale (add it only if analysis demands).
- **Geospatial:** haversine + simple bbox math; `shapely` only if polygon work forces it.
- **Process:** systemd unit + Caddy snippet in `deploy/`; APScheduler (or a cron call
  to a `/scan` endpoint) for the daily hazard check in Phase 2.

## Free data (licensing checked)
| Need | Source | Access | License |
|---|---|---|---|
| Assets: bridges, roads, clinics, schools, water points, settlements | **OpenStreetMap** (incl. HOT mapping) | Overpass API, free | ODbL — attribute "© OpenStreetMap contributors"; share-alike on derived DB |
| River flood forecast | **GloFAS river discharge** via **Open-Meteo flood API** | `flood-api.open-meteo.com`, free, no key | free for non-commercial & open projects — fine for hackathon; recheck terms at commercialisation |
| Rainfall (observed + seasonal context) | **CHIRPS** | direct download / ClimateSERV API | public domain-style, free |
| Elevation / low-crossing detection | **SRTM 30 m** | Open Topo Data public API | public domain |
| Population per settlement | **WorldPop** | downloads/API | CC-BY 4.0 — attribute |
| Regional hazard layers (later) | **ICPAC GeoPortal / Hazards Watch** | WMS/WFS endpoints | check per-layer terms; cite ICPAC — judges' own data is a plus |
| **Banned** | GEE free tier, FABDEM | — | non-commercial licences |

Cache every external response in SQLite (`geocache`); the demo must also run with
`USE_LIVE=0` so a dead Wi-Fi link can never kill the pitch.

## Run commands
```
cd /opt/lifeline
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8017
```
Service: `sudo cp deploy/qvah-lifeline.service /etc/systemd/system/ && sudo systemctl
daemon-reload && sudo systemctl enable --now qvah-lifeline`

## Conventions
- Modules: `ontology.py` (type registry + fragility rules), `db.py` (state),
  `ingest_osm.py` (assets in), `hazards.py` (feeds in), `propagate.py` (the engine),
  `actions.py` (playbook out), `main.py` (glue + UI). Keep each small.
- **Every impact row stores its why-chain** (ordered list of object/link ids). If a
  result can't explain itself, it doesn't ship.
- The playbook is data (`data/playbook.csv`), never code. Fragility rules live in one
  table in `ontology.py` with a version string shown in the UI.
- All state in SQLite; no in-memory truth. Secrets (none expected) in `.env`.
- Budget: **~$0/month**; anything that costs money needs a decision in 05 first.
