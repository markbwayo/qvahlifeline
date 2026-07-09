# 09 — Ontology Specification v0.6 (THE core artifact)

Palantir-style semantic layer: **objects** (typed things with properties), **links**
(typed relationships), **hazard propagation** (deterministic rules over links),
**actions** (first-class, pre-agreed, owned). Code follows this file, never the
reverse. Version every change.

## Object types (MVP set)
| Type | Key properties | Notes / OSM mapping |
|---|---|---|
| `river_reach` | name, glofas_lat/lon | waterway=river/stream, split at crossings |
| `bridge` | name, structure (bridge/culvert/ford/causeway), crossing_class (main_road/minor_road/footpath), single_point_of_failure | bridge=yes, tunnel=culvert, ford=yes; crossing_class gates vehicle reachability |
| `road_segment` | name, class, all_weather (bool) | highway=* between junctions/assets |
| `settlement` | name, population (WorldPop) | place=village/hamlet/town |
| `clinic` | name, level | amenity=clinic/hospital/health_post |
| `school` | name | amenity=school (shelter potential) |
| `water_point` | name, kind (borehole/spring/tap) | man_made=water_well etc. |
| `hazard` | kind (riverine_flood, extreme_rain), severity (watch/alert/emergency), source, valid_from/to, trigger_detail | created by feeds or manually |
| `impact` | state, why_chain (ordered ids), hazard_id, object_id | engine output only |
| `action` | text, owner_role, lead_time_hrs, status, impact_id | from playbook only |
### Crossing provenance & reconciliation (v0.4)
- A crossing's `source` is one of `seed | osm | operator | synth`. Operator crossings
  are satellite-verified engineer classifications from `data/operator_crossings.csv`.
- On a match the operator's `structure`/`crossing_class` win, but the OSM object's
  id, name and coordinates are preserved (map/demo/link stability). `source` becomes
  `operator`; provenance kept in props (`osm_id`, `osm_structure`, `dedup_dist_m`,
  `operator_id`). No second object is created.
- **Identity is never guessed.** Resolution order per operator row: (1) already
  injected (by `operator_id`) -> update in place; (2) explicit `match_hint` (an OSM id)
  -> that object; (3) no hint and exactly one OSM crossing within ~50 m -> that one;
  (4) no hint and *more than one* within ~50 m -> injection REFUSES and prints the
  cluster; (5) none within ~50 m -> new operator object. See D-022.
- `crossing_class` (from CSV `road_class`) gates the vehicle graph: a `footpath`
  crossing never receives a `carries` link and is excluded from clinic-route
  reachability. (Enforced in sub-step 3.)
- CSV columns: `id, structure, name, lat, lon, road_class, source, note, match_hint`
  (match_hint optional).
All objects: `id, type, name, lat, lon, props_json, source, created_utc`.

### Synthesised crossings (v0.4)
- Where a VEHICLE `road_segment` polyline intersects a `river_reach` polyline and no
  crossing exists within ~50 m, a crossing candidate is synthesised: `type=bridge`,
  `source=synth`, `needs_review=True`, **no `structure`**, provenance in props
  (`synth_road_id`, `synth_reach_id`, `synth_road_class`, `inferred_by=road_x_river`).
- Structure is never guessed — a synthesised crossing carries no fragility state and
  cannot produce an impact until a human classifies it (operator CSV or add/edit).
  How propagation treats an unclassified crossing is defined in sub-step 3.
- Only vehicle highway classes are intersected; footway/path/pedestrian/steps/
  cycleway/bridleway are excluded (a footbridge is not a clinic lifeline).
- Synthesis is deterministic and idempotent (coordinate-stable ids; ~50 m self-dedup
  and dedup against existing crossings).

## Link types
| Link | From → To | Meaning / how inferred |
|---|---|---|
| `crosses` | bridge → river_reach | bridge node on/near waterway (≤50 m) |
| `carries` | road_segment → bridge | road passes over the bridge |
| `connects` | road_segment ↔ road_segment | shared junction |
| `access_via` | settlement/facility → road_segment | nearest vehicle-road entry point; applies to settlements AND serving facilities (clinic/school/water_point), which the reachability BFS uses as start/goal nodes |
| `serves` | clinic/school/water_point → settlement | catchment rule: nearest facility within threshold; committee-editable |
| `on_floodplain` | settlement/asset → river_reach | elevation within Δh of reach AND within buffer distance (SRTM heuristic, v1) |
A `bridge` (crossing) object is only created for a bridge/culvert/ford that carries a
vehicle road_segment. Footpath/ditch/stream crossings are out of scope. Untagged
road×river crossings are synthesised geometrically at link-inference time.

Inference is rules-first; ambiguous cases go to the operator (or the AI edge proposes,
human confirms). Every link stores `inferred_by` and can be manually overridden —
committee knowledge always outranks the algorithm.

## Fragility rules v0.2 (deterministic; versioned; my engineering judgement, tunable)
`(object_type, structure, hazard_kind, severity) → state`
- bridge/ford/causeway + riverine_flood: watch → AT_RISK; alert → LIKELY_IMPASSABLE;
  emergency → IMPASSABLE. Engineered bridge: watch → OK; alert → AT_RISK;
  emergency → LIKELY_IMPASSABLE. Culvert: one level worse than bridge (blockage risk).
- road_segment (not all_weather) + extreme_rain ≥ alert → DEGRADED.
- settlement/asset with `on_floodplain` link to a flooded reach: severity ≥ alert →
  FLOOD_EXPOSED.
### Unknown-structure rule (v0.6)
- A crossing whose `structure` is missing or unrecognised (e.g. a `source=synth`,
  `needs_review` crossing) is scored as the **most fragile** known structure (`ford`),
  never the least. Encoded as `ontology.UNKNOWN_STRUCTURE_ASSUMPTION`.
- Rationale: base rate (an unmapped rural crossing is more likely a ford/culvert than
  an engineered bridge) plus asymmetric cost (a false "may be out" costs an inspection;
  a false "all clear" leaves a village unwarned). **Never fail toward all-clear.**
- The substitution is declared in the why-chain as `assumed_structure:ford(unclassified)`,
  so no impact hides the fact that its structure was unknown (invariant 2).
- A table miss on *hazard kind* still yields OK — that hazard genuinely doesn't act on
  the object. Only a miss on *structure* triggers the conservative assumption.

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
