# 09 — Ontology Specification v0.1 (THE core artifact)

Palantir-style semantic layer: **objects** (typed things with properties), **links**
(typed relationships), **hazard propagation** (deterministic rules over links),
**actions** (first-class, pre-agreed, owned). Code follows this file, never the
reverse. Version every change.

## Object types (MVP set)
| Type | Key properties | Notes / OSM mapping |
|---|---|---|
| `river_reach` | name, glofas_lat/lon | waterway=river/stream, split at crossings |
| `bridge` | name, structure (bridge/culvert/ford/causeway), single_point_of_failure | bridge=yes, tunnel=culvert, ford=yes |
| `road_segment` | name, class, all_weather (bool) | highway=* between junctions/assets |
| `settlement` | name, population (WorldPop) | place=village/hamlet/town |
| `clinic` | name, level | amenity=clinic/hospital/health_post |
| `school` | name | amenity=school (shelter potential) |
| `water_point` | name, kind (borehole/spring/tap) | man_made=water_well etc. |
| `hazard` | kind (riverine_flood, extreme_rain), severity (watch/alert/emergency), source, valid_from/to, trigger_detail | created by feeds or manually |
| `impact` | state, why_chain (ordered ids), hazard_id, object_id | engine output only |
| `action` | text, owner_role, lead_time_hrs, status, impact_id | from playbook only |

All objects: `id, type, name, lat, lon, props_json, source, created_utc`.

## Link types
| Link | From → To | Meaning / how inferred |
|---|---|---|
| `crosses` | bridge → river_reach | bridge node on/near waterway (≤50 m) |
| `carries` | road_segment → bridge | road passes over the bridge |
| `connects` | road_segment ↔ road_segment | shared junction |
| `access_via` | settlement → road_segment | nearest road entry point(s) of the settlement |
| `serves` | clinic/school/water_point → settlement | catchment rule: nearest facility within threshold; committee-editable |
| `on_floodplain` | settlement/asset → river_reach | elevation within Δh of reach AND within buffer distance (SRTM heuristic, v1) |

Inference is rules-first; ambiguous cases go to the operator (or the AI edge proposes,
human confirms). Every link stores `inferred_by` and can be manually overridden —
committee knowledge always outranks the algorithm.

## Fragility rules v0.1 (deterministic; versioned; my engineering judgement, tunable)
`(object_type, structure, hazard_kind, severity) → state`
- bridge/ford/causeway + riverine_flood: watch → AT_RISK; alert → LIKELY_IMPASSABLE;
  emergency → IMPASSABLE. Engineered bridge: watch → OK; alert → AT_RISK;
  emergency → LIKELY_IMPASSABLE. Culvert: one level worse than bridge (blockage risk).
- road_segment (not all_weather) + extreme_rain ≥ alert → DEGRADED.
- settlement/asset with `on_floodplain` link to a flooded reach: severity ≥ alert →
  FLOOD_EXPOSED.

## Propagation (the engine, deterministic BFS)
1. Hazard on river_reach R at severity S.
2. Direct: every object linked `crosses`/`on_floodplain` to R gets its fragility
   state.
3. Network: a road_segment is SEVERED if a bridge it `carries` is IMPASSABLE /
   LIKELY_IMPASSABLE.
4. Reachability: for each settlement, test whether any path over non-severed,
   non-degraded road segments reaches each facility that `serves` it.
   No path at all → **ISOLATED**; only a longer alternate path → **REROUTED** (with
   the alternate named); facility itself impacted → **SERVICE_AT_RISK**.
5. Every produced impact records the full why-chain:
   `hazard → reach → bridge → road → settlement (→ facility)`.
6. States are ordered (OK < AT_RISK < DEGRADED/REROUTED < LIKELY_IMPASSABLE/
   FLOOD_EXPOSED < IMPASSABLE/SEVERED/ISOLATED); an object keeps its worst state.

## Action playbook (data/playbook.csv)
`object_type, state, hazard_kind, action_text, owner_role, lead_time_hrs`
Examples: settlement+ISOLATED+riverine_flood → "Send pre-agreed local-language alert
to chief & radio; verify boat/alternate crossing" (owner: DDMC comms, 48h);
clinic+SERVICE_AT_RISK → "Pre-position essential drug kit on far side of crossing"
(owner: DHO, 72h); bridge+LIKELY_IMPASSABLE → "Deploy inspection; stage closure
signage" (owner: district engineer, 24h). The committee owns this table; the tool
fires it.

## Invariants (test these forever)
1. Same inputs → same impacts, always.
2. No impact without a complete why-chain.
3. Severing the only crossing isolates exactly the settlements with no alternate
   path — and nothing else.
4. No action without a matching impact; no impact state outside the fragility table.
5. Removing the hazard clears all derived impacts/actions (idempotent re-scan).
