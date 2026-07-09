# 09 — Ontology Specification v0.9 (THE core artifact)

Palantir-style semantic layer: **objects** (typed things with properties), **links**
(typed relationships), **hazard propagation** (deterministic rules over links),
**actions** (first-class, pre-agreed, owned). Code follows this file, never the
reverse. Version every change.

## Object types (MVP set)
| Type | Key properties | Notes / OSM mapping |
|---|---|---|
| `river_reach` | name, waterway (river/stream), geometry, glofas_lat/lon | waterway=river/stream; `waterway` decides hazard scope (see below) |
| `bridge` | name, name_source (osm/operator/object_id), structure (bridge/culvert/ford/causeway), crossing_class (main_road/minor_road/footpath), needs_review, single_point_of_failure | bridge=yes, tunnel=culvert, ford=yes; crossing_class gates vehicle reachability |
| `road_segment` | name, class, geometry, all_weather (bool) | highway=* between junctions/assets |
| `settlement` | name, population (WorldPop) | place=village/hamlet/town |
| `clinic` | name, level | amenity=clinic/hospital/health_post |
| `school` | name | amenity=school (shelter potential) |
| `water_point` | name, kind (borehole/spring/tap) | man_made=water_well etc. |
| `hazard` | kind (riverine_flood, extreme_rain), severity (watch/alert/emergency), scope (reach/river), source, valid_from/to, trigger_detail | created by feeds or manually |
| `impact` | state, why_chain (ordered ids), hazard_id, object_id | engine output only |
| `action` | text, owner_role, lead_time_hrs, status, impact_id | from playbook only |
### Crossing provenance & reconciliation (v0.4)
- A crossing's `source` is one of `seed | osm | operator | synth`. Operator crossings
  are satellite-verified engineer classifications from `data/operator_crossings.csv`.
- On a match the operator's `structure`/`crossing_class` win, but the OSM object's
  id and coordinates are preserved (map/demo/link stability). `source` becomes
  `operator`; provenance kept in props (`osm_id`, `osm_structure`, `dedup_dist_m`,
  `operator_id`). No second object is created.

### Naming a reconciled crossing (v0.9)
- The OSM `name` is preserved **only when it is non-empty** — the district knows the
  structure by that label and the operator must never silently rewrite it. When the
  OSM name is empty, the operator's CSV `name` becomes the object's name.
- `props.name_source` ∈ `osm | operator | object_id` records which, is written once,
  and is never flipped by a re-run (invariant 1). `props.osm_name` keeps the original
  (often `null`).
- **Why the hole exists.** OSM does not always put a structure's name on `name`. The
  demo spine `w128611448` carries `noname=yes` with `bridge:name=Manafwa Bridge` and
  `bridge:ref=B112`, so ingest reads `tags.name` and stores NULL. Preserving that NULL
  rendered the district's only tarmac crossing — the object 51 of 62 ISOLATED
  why-chains name — as the bare string `w128611448` on the map and in the why-chain
  panel, while the least load-bearing structure (Old Manafwa bridge, present in zero
  isolated chains) was the only named bridge on screen. See D-041.
- `bridge:name` is captured as `props.osm_bridge_name` for provenance and audit. It is
  **never** promoted to the object's name: an operator classification is ground truth,
  a secondary OSM tag is not. Fixing the general nameless-crossing case at ingest
  (e.g. `w747829218`, unnamed, cuts off 8 settlements) is post-hackathon.
- A crossing with no OSM name and no operator row keeps its object id as its label.
- **Identity is never guessed.** Resolution order per operator row: (1) already
  injected (by `operator_id`) -> update in place; (2) explicit `match_hint` (an OSM id)
  -> that object; (3) no hint and exactly one OSM crossing within ~50 m -> that one;
  (4) no hint and *more than one* within ~50 m -> injection REFUSES and prints the
  cluster; (5) none within ~50 m -> new operator object. See D-022.
- `crossing_class` (from CSV `road_class`) gates the vehicle graph: a `footpath`
  crossing never receives a `carries` link — primary or fallback — and is therefore
  excluded from clinic-route reachability.
- CSV columns: `id, structure, name, lat, lon, road_class, source, note, match_hint`
  (match_hint optional).
All objects: `id, type, name, lat, lon, props_json, source, created_utc`.

### Synthesised crossings (v0.4)
- Where a VEHICLE `road_segment` polyline intersects a `river_reach` polyline and no
  crossing exists within ~50 m, a crossing candidate is synthesised: `type=bridge`,
  `source=synth`, `needs_review=True`, **no `structure`**, provenance in props
  (`synth_road_id`, `synth_reach_id`, `synth_road_class`, `inferred_by=road_x_river`).
- Structure is never guessed. Propagation treats an unclassified crossing under the
  Unknown-structure rule below: it is scored as the **most fragile** structure, so it
  can never silently keep a route open. A human classifies it (operator CSV or
  add/edit) to replace the assumption with knowledge.
- Only vehicle highway classes are intersected; footway/path/pedestrian/steps/
  cycleway/bridleway are excluded (a footbridge is not a clinic lifeline).
- Synthesis is deterministic and idempotent (coordinate-stable ids; ~50 m self-dedup
  and dedup against existing crossings).

### Hazard scope (v0.8)
- A hazard carries `scope`, one of `reach | river`.
  - `reach` floods only the trigger `river_reach`.
  - `river` floods the trigger reach **plus every reach of the same `waterway` value
    that is vertex-connected to it** (~1.1 m grid). This is the demo default
    (`hazards.demo_flood_river`). See D-036.
- Rationale: GloFAS forecasts discharge on the modelled **river channel**. A spike
  raises the whole connected mainstem, not one OSM way. Reach scope let settlements
  detour over crossings that a real flood would also close — measured on the pilot
  graph: **0 ISOLATED / 43 REROUTED** at reach scope, **62 ISOLATED / 0 REROUTED** at
  river scope, with 2 clinics losing catchment.
- `waterway=stream` tributaries are **excluded**: GloFAS does not resolve them, and
  they are a pluvial / `extreme_rain` hazard (see 04.D), not a riverine one.
- **Sensitivity, stated honestly in the pitch:** widening scope to include the 6
  streams touching the mainstem moves ISOLATED 62 → 63; including the district's other
  named rivers moves it not at all. The result is network topology, not over-warning.
- Endpoint-only adjacency is insufficient — tributaries and continuations join
  mid-reach — so connectivity is computed on **shared vertices**. A watercourse that is
  not connected to the trigger reach is never flooded by that trigger.
- Reaches are largely unnamed in OSM (3 of 85 in the pilot box), so scope groups by
  the `waterway` tag and geometry, never by name.

## Link types
| Link | From → To | Meaning / how inferred |
|---|---|---|
| `crosses` | bridge → river_reach | nearest reach within ~50 m of the crossing point |
| `carries` | road_segment → bridge | every vehicle road whose line passes within ~20 m; a crossing left with zero carriers falls back to its single nearest vehicle road (≤100 m, `inferred_by=geom_carries_fallback`) — a crossing that carries nothing can never sever a route |
| `connects` | road_segment ↔ road_segment | shared junction vertex; ALSO roads carrying the same crossing (`inferred_by=via_crossing`) — in OSM the bridge is its own way, so the roads either side share no vertex and the banks would never join |
| `access_via` | settlement/facility → road_segment | nearest vehicle-road entry point; applies to settlements AND serving facilities (clinic/school/water_point), which the reachability BFS uses as start/goal nodes |
| `serves` | clinic/school/water_point → settlement | catchment rule: nearest facility of each type within threshold; committee-editable |
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
1. Hazard of `kind` at severity `S` on trigger reach `R`, with `scope`. The **flooded
   set** is `{R}` when `scope=reach`, or the vertex-connected same-`waterway` channel
   containing `R` when `scope=river` (see Hazard scope above).
2. Direct: every object linked `crosses` / `on_floodplain` to **any flooded reach**
   takes its fragility state. A crossing whose state is IMPASSABLE or
   LIKELY_IMPASSABLE is *blocked*.
3. Network: apply each blocked crossing to the road graph. The **crossing** holds the
   impassable state — it is the deck that fails, not the road either side.
   - **≥2 carrier roads** (the crossing is a distinct OSM way): the `connects` **edge
     between the carriers is cut**. The approach roads stay drivable on their own bank
     and take **no state**. Marking them SEVERED while still routing traffic over them
     would tell an officer "this road is cut — now drive it".
   - **exactly 1 carrier road** (the crossing sits mid-way through one unsplit way):
     the break cannot be localised, so that road is **SEVERED** and dropped whole.
     This over-states the break, which is the safe direction.
   - A dropped road is untraversable — including as a path's first or last hop, so a
     settlement whose own access road is dropped cannot be "reachable in zero hops".
     No alternate route ever traverses a SEVERED road.
4. Reachability is evaluated **per facility** that `serves` the settlement: for each,
   no path over the remaining network → **ISOLATED** (naming that facility); a longer
   path → **REROUTED** (with the alternate named). A settlement that loses its clinic
   but keeps its local school is still ISOLATED — pooling facilities would hide it.
   A facility is **SERVICE_AT_RISK** only for settlements that had baseline access and
   lost it; never for settlements it could never reach.
5. Every produced impact records the full why-chain:
   `hazard → reach → bridge → road → settlement (→ facility)`. Each impact names the
   reach **its own** crossing spans and the crossing that actually blocks **that**
   settlement's route — never an arbitrary member of the blocked set. The `road` step
   appears only when a road was dropped; a cut crossing edge names the crossing.
6. States are ordered (OK < AT_RISK < DEGRADED/REROUTED < LIKELY_IMPASSABLE/
   FLOOD_EXPOSED < IMPASSABLE/SEVERED/ISOLATED); an object keeps its worst state.
7. Determinism: all traversal iterates **sorted** containers. Python randomises string
   hashes per process, so set iteration order is not stable across runs — unsorted BFS
   silently broke invariant 1 by producing different why-chains for identical input.

## Action playbook (data/playbook.csv)
`object_type, state, hazard_kind, action_text, owner_role, lead_time_hrs`
Examples: settlement+ISOLATED+riverine_flood → "Send pre-agreed local-language alert
to chief & radio; verify boat/alternate crossing" (owner: DDMC comms, 48h);
clinic+SERVICE_AT_RISK → "Pre-position essential drug kit on far side of crossing"
(owner: DHO, 72h); bridge+LIKELY_IMPASSABLE → "Deploy inspection; stage closure
signage" (owner: district engineer, 24h). The committee owns this table; the tool
fires it.

## Invariants (test these forever)
1. Same inputs → same impacts **and same why-chains**, always.
2. No impact without a complete why-chain.
3. Severing the only crossing isolates exactly the settlements with no alternate
   path — and nothing else.
4. No action without a matching impact; no impact state outside the fragility table.
5. Removing the hazard clears all derived impacts/actions (idempotent re-scan).
6. No impact may fail toward all-clear: an unknown structure, an unclassified crossing,
   a missing hazard target, or a stale schema must raise or over-warn — never reassure.
