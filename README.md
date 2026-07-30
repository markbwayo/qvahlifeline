# Qvah LIFELINE

## What it does

Qvah LIFELINE turns a river-flood trigger into impacts on named bridges, roads,
settlements, clinics, schools, and water points. It propagates the hazard through
a graph of physical and service dependencies, records a why-chain for each impact,
and selects pre-agreed actions with owners and lead times. Its AI edge only drafts
Swahili translations, marks every draft `DRAFT`, and requires human approval.

## Architecture

```text
OpenStreetMap assets + operator review
                 |
                 v
       typed objects and links
                 |
GloFAS via Open-Meteo -> deterministic propagation -> impacts + why-chains
                                                     |
                                                     v
                                      playbook actions + message facts
                                                     |
                                                     v
                               optional Swahili DRAFT -> human approval
```

## File map

```
app/main.py       glue + Leaflet map UI (port 8017)
app/ontology.py   type registry + fragility rules (mirrors 09_ontology_spec.md)
app/db.py         SQLite graph (objects, links)
app/links.py      link inference: crosses, carries, connects, access_via, serves
app/propagate.py  THE engine: deterministic BFS, why-chains, invariants
app/actions.py    playbook lookup (data/playbook.csv — committee-owned)
app/hazards.py    demo trigger and live GloFAS scan
app/ingest_osm.py real OSM assets for the locked pilot bbox
app/messages.py   broadcast rendering from committee templates + CAP fields
app/ai_edge.py    the single AI adapter: Swahili translation drafts only
app/approvals.py  human approval records for drafted translations
data/playbook.csv object_type x state x hazard -> action, owner, lead time
data/messages.csv committee-authored broadcast templates
data/operator_crossings.csv engineer-classified crossings
data/reach_glofas.csv operator-verified GloFAS cells
data/triggers.csv severity to return period
tests/            335 tests including negative controls
deploy/           systemd unit + Caddy snippet
```

## Run it

```
cd /opt/lifeline
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8017
```

The deployment can run with `USE_LIVE=0`. This prevents a failed external feed from
looking like a calm river during the demo.

## Data sources and attribution

- **OpenStreetMap** supplies mapped assets through the Overpass API. The data is
  licensed under ODbL. Display the attribution `© OpenStreetMap contributors`, and
  observe the ODbL share-alike requirement for a derived database.
- **GloFAS river discharge via the Open-Meteo flood API** supplies the live river
  forecast. Open-Meteo provides free access for non-commercial and open projects.
  Attribute both GloFAS and Open-Meteo, and recheck the terms before
  commercialisation.

## Honest limits

- OpenStreetMap completeness varies. Operator review is required, and missing local
  assets must be added.
- The GloFAS grid is about 5 km and is screening-grade at village scale. Three cells
  under one 4.3 km reach disagree by more than an order of magnitude, so the trigger cell is
  operator-verified rather than automatically snapped.
- Thresholds use 29 annual maxima from 1997–2025. The code refuses to extrapolate
  past Q20.
- Fragility rules are versioned engineering heuristics v1, not a hydraulic model.
- A crossing represented by one carrier can overstate the break because road ways
  are not yet split at crossings.
- 7 bare ford nodes have no carrier road.
- Five unnamed OSM crossings render as their object IDs in their own closure
  notices. They never appear in a village warning. The interface reports the
  source identifier instead of hiding the missing OSM name.
- The earlier bare-ID problem in village broadcasts is fixed. Operator-reviewed
  rows now name `w747829218` as Namakhutu bridge and `w160219946` as Namutebi
  bridge. Zero village broadcasts name a bare object ID.
- The demonstrated district result uses `emergency` severity, not a routine-season
  forecast.
- There is no delivery integration. English messages are available in the current
  build. Swahili output is only an optional AI-generated `DRAFT` and must be approved
  by a human.
- Lumasaba templates are committee-authored data, not generated text. They have not
  yet been written. English-only ships, and the officer's screen lists every village
  missing a local-language template by name. A model could generate Lumasaba text
  that nobody present could audit, so each row stays empty until the committee fills
  it.

## Safety boundary

No model decides triggers, impacts, severities, why-chains, or actions. Those outputs
come from the graph, versioned fragility rules, thresholds, and the playbook. The AI
edge only drafts Swahili translations, always marked `DRAFT` and always subject to
human approval.
