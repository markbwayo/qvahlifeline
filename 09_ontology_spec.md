# 09 — Ontology Specification v1.5 (THE core artifact)

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

## Hazard triggers (v1.2) — GloFAS → severity

`data/reach_glofas.csv` (operator-verified points) × `data/triggers.csv`
(committee-tunable severity → return period) → `hazards.scan_live()`.

### The GloFAS point is verified, never snapped
- A `river_reach` triggers only if an engineer has signed a GloFAS cell for it in
  `data/reach_glofas.csv` (`reach_id, glofas_lat, glofas_lon, note, verified_by`).
  A row without `verified_by` is refused at load: an unsigned point is an auto-snap.
- **Why.** Open-Meteo snaps a request to the centre of a ~0.05° (~5 km) cell, and
  GloFAS models ONE channel per cell — the one with the largest accumulated upstream
  area. Measured on the pilot: the 4.3 km demo reach `w188321163` straddles THREE
  cells reading 67.7, 6.1 and 91.5 m³/s mean, non-monotonic downstream. Water does not
  do that; two of those cells model a different river. A dead cell reads 0.0 and
  screams. A wrong cell reads 91.5 and looks like data. Geometry proposes
  (`scripts/glofas_probe.py`), the engineer signs.
- The served cell is re-checked on every fetch against the verified one
  (`CELL_TOLERANCE_DEG = 0.03`). A drift means the thresholds no longer describe the
  water that was verified: refuse.
- An **unverified** river reach cannot raise a hazard, and every scan reports the count
  by name. Under `scope=river` one verified reach floods the whole connected channel,
  so the pilot needs one point, not thirty-three. `waterway=stream` reaches are outside
  riverine triggers (D-036) and are not counted as a coverage gap.

### Thresholds are empirical and refuse to extrapolate
- **Annual maximum series**, one peak per calendar year — one flood population.
  Seasonal maxima would double n but mix a lesser season's peaks into the sample.
- **Weibull plotting position**, `T = (n+1)/m`. No distribution is fitted.
  `MAX_RETURN_PERIOD = 20`: beyond it the code raises rather than answering, and
  `weibull_q` returns `None` for any T beyond the record — which a caller must treat as
  *unanswerable*, never as *not exceeded*.
- **Why not a fitted curve.** The reanalysis serves from **1997, not 1984** (the API
  silently clips the requested window — `reanalysis()` asserts the served window rather
  than trusting the request). n = 29. Q10 rests on the third-largest peak; Q20
  interpolates between the top two; Q50 does not exist. A Gumbel fit returns Q10 = 17.5
  against the empirical 19.4 because it flattens the 1998 El Niño outlier. A fitted
  number past the record is an extrapolation wearing a decimal point.
- Fewer than `MIN_ANNUAL_MAXIMA = 20` years → refuse to threshold.

### severity → return period is data
| severity | T | Manafwa @ Bubulo (m³/s) | exceeded |
|---|---|---|---|
| watch | Q2 | 12.37 | ~15 of 29 years |
| alert | Q5 | 14.81 | ~6 of 29 |
| emergency | Q10 | 19.37 | 1997, 1998, 2002 |
Return periods must **strictly increase** with severity — a watch rarer than an
emergency inverts the ladder silently, and is refused at load.

### The scan
`scan_live()` takes the forecast peak over the next 7 days and raises a hazard at the
**highest severity actually exceeded**, `scope=river`, `source=GloFAS/Open-Meteo`, with
the peak, the threshold, the return period, the record length and the ~5 km caveat in
`trigger_detail`. One hazard per reach per severity per UTC day.

**A fetch failure, an empty series, a dead cell, a drifted cell, a short record or a
missing verified point all RAISE.** None of them returns a clean empty result. "No
hazard" and "we could not look" must never render identically on a map (invariant 6).
`USE_LIVE=0` returns an explicit *disabled* status, never `triggered: []` alone.

## Action playbook (data/playbook.csv) v1.0
`object_type, state, hazard_kind, action_text, owner_role, lead_time_hrs`

- **Match is an exact triple** `(object_type, state, hazard_kind)`. There are no
  wildcards: a `*` row can silently shadow a specific one (D-043). Several rows may
  share a triple — all of them fire, sorted by `(lead_time_hrs, owner_role,
  action_text)` so the action list is identical on every run (invariant 1).
- Every row is validated against the ontology at load: `object_type ∈ OBJECT_TYPES`,
  `state ∈ STATE_ORDER` (never `OK` — an OK object has no impact), `hazard_kind ∈
  HAZARD_KINDS`, non-empty `owner_role` (an action nobody owns is not an action),
  integer `lead_time_hrs ≥ 0`, no duplicate rows. A bad row raises with its line
  number. `ontology.HAZARD_KINDS` is the registry the CSV is checked against.
- **An impact with no matching row is `uncovered`, and is reported, never dropped.**
  `fire_actions()` returns every uncovered impact and the CLI prints it. A red village
  with no action beside it is indistinguishable on screen from "nothing to do" —
  the action-layer form of a false all-clear (invariant 6). The committee may
  legitimately choose not to act on `bridge AT_RISK`; it may never do so invisibly.
- **An `ISOLATED` action must never propose a road alternate.** The BFS has proved
  there is none, and on the Manafwa spine the only candidate (Old Manafwa bridge)
  fails under the same flood (D-038). Enforced at load: `alternate route`,
  `alternative route`, `detour`, `reroute`, `another route` are rejected in ISOLATED
  rows. Verifying a boat or foot crossing is not a road route and is permitted.
- Action text is **verbatim** from the CSV. No interpolation, no model. The AI edge
  may later translate an action for broadcast (marked DRAFT, human-approved); it
  never selects or writes one (hard rule 1, `07`).
- Firing is idempotent: `fire_actions()` clears this hazard's actions and rebuilds
  them; `clear_derived()` removes them with their impacts (invariant 5).

Examples: settlement+ISOLATED+riverine_flood → "Send the pre-agreed local-language
alert to the chief by radio and WhatsApp; state plainly that no road alternate exists"
(owner: DDMC comms, 48h); clinic+SERVICE_AT_RISK → "Pre-position the essential drug kit
and delivery supplies on the far side of the crossing" (owner: DHO, 72h);
bridge+LIKELY_IMPASSABLE → "Deploy an inspection team; stage closure signage and
barriers at both approaches" (owner: district engineer, 24h).
The committee owns this table; the tool fires it.

### Action ordering and the precautionary flag (v1.1)
- `actions_for()` returns actions ordered by **consequence** (descending), then
  `lead_time_hrs`, then object id. `consequence` = the number of **distinct settlements
  an object is proved to have cut off**, read from the engine's own why-chains at read
  time — never stored, never re-inferred. Two chain families carry that proof and both
  must be read:
    - an **ISOLATED settlement's** chain names the crossing and road that blocked *that*
      settlement's route; every object in it is charged with that one settlement;
    - a **SERVICE_AT_RISK facility's** chain lists every settlement that lost it. This
      family is not optional: a settlement stores only ONE chain, so a village that lost
      its clinic *and* its school records only the clinic, and the school would otherwise
      report zero dependents.
  Victims from a facility chain are charged to the **facility alone**, never to the
  bridges named in it: that bridge list is a union across all the facility's lost
  settlements, so charging each bridge with each settlement would let one bridge claim
  villages another blocked. A bridge earns a dependent only from the ISOLATED chain that
  names it.
- **A `SERVICE_AT_RISK` facility can never be `precautionary`.** D-033 grants that state
  only to a facility some settlement had and lost, so zero dependents on one is
  arithmetically impossible. Test-locked.
- **Urgency is not consequence.** Ordered by lead time alone, three unnamed ford nodes
  (12 h) print above the B112 bridge (24 h) that cuts fifty-one villages. An officer
  reading top-down must meet the deck that isolates a sub-county before he meets a
  closure order for a crossing nobody depends on.
- `precautionary` = `consequence == 0`. Such an action **still fires and still carries
  full weight** — a flooded ford is a hazard to whoever drives into it. Zero dependents
  means only that no settlement *in this graph* loses a route through it: either the
  crossing truly carries no vehicle road, or link inference never found the road it
  sits on (7 bare OSM ford nodes have no `carries` link within 100 m). A gap in our
  data may never silence a warning (invariant 6). The flag explains an action; it never
  suppresses one. Suppression would require an operator classification, not a code rule.
- `precautionary` is not "no carrier". `w902422828` (Old Manafwa bridge) is blocked,
  has a carrier road, and appears in zero of the 62 isolated why-chains. It is
  precautionary because it is never an alternate (D-038), which the field now states
  in the action list rather than only in the pitch.
- `carriers` = count of `carries` links into the crossing; `None` for non-crossings.

## The read side (v1.3)

The UI renders; it never decides. It re-implements no rule and re-infers no number.
Three of this project's bugs lived on the read side while the engine was correct, so
the contract is spec'd, not left to the file:

- **One hazard.** Impacts and actions are read for exactly one hazard — the newest
  active one. Never a join across `impacts`/`actions` with no hazard filter, which
  rendered 852 rows from five hazards, most of them cleared days earlier. When more
  than one hazard is active the page declares it and shows one; it never blends them.
- **Consequence, not urgency.** The action list comes from `actions.actions_for()`
  and keeps its order (D-045, D-046). A page that re-sorts by lead time undoes the
  decision.
- **Coverage is always rendered**, including when nothing is uncovered. "No uncovered
  panel" and "no uncovered impacts" must not look alike (invariant 6). An impact whose
  playbook triple exists but which fired no action is a BUG and renders as one, not as
  a committee choice.
- **Four scan states, never one.** `not run` / `disabled (USE_LIVE=0)` / `feed failure`
  / `quiet, with numbers`. `scan_live()` raises (D-047); the presentation boundary
  catches the raise and displays it. It never converts a raise into an empty result.
- **A crossing with no name renders as its object id** (see *Naming a reconciled
  crossing*). `(unnamed bridge)` was one string for thirty-two objects, one of which
  (`w747829218`) cuts off eight settlements.
- **Every state in `STATE_ORDER` must have a colour**, checked at import. A state with
  no colour inheriting the OK green is a false all-clear on the map.
- The footer attributes the data actually ingested — OSM (ODbL) and GloFAS via
  Open-Meteo — and nothing else. WorldPop is not ingested (D-040); no link infers
  `on_floodplain`, so no SRTM.

## Broadcast messages (data/messages.csv) v1.0

`object_type, state, hazard_kind, lang, template`

The last mile is a chief with a radio. What reaches him is the only output of this
system a judge cannot audit, because it is not in English. So it is not generated.

- **The sentence is committee data**; the **facts come from the impact's own why-chain**
  and nowhere else. Not a second traversal, not a regex over `trigger_detail`, not a
  model. The AI edge may later draft an English polish or a Swahili translation, marked
  DRAFT and human-approved. **Lumasaba is never generated** (D-052).
- **`ontology.BROADCAST_STATES`** decides which impacts a community is warned about:
  `settlement/ISOLATED`, `bridge/IMPASSABLE`, `bridge/LIKELY_IMPASSABLE`. A template for
  any other state is refused at load. An officer does not need a message; he needs a
  task, and the playbook already gives him one with an owner and a lead time.
- **`ontology.MESSAGE_SLOTS`** is a per-type whitelist and the enforcement point for
  D-051: `lead_time` and `threshold` are not slots, so they cannot enter a broadcast by
  a typo. A slot typo raises with its line number.
- **A slot that cannot be filled RAISES.** "The road to  crosses ." is worse than no
  message. A nameless crossing renders as its object id, never as blank (09, v0.9).
- **A `lang != en` row with no `en` row for the same triple is refused.** English is what
  the system degrades to; a translation with nothing behind it degrades to silence.
- **An `ISOLATED` message may not contain a road-alternate phrase.** The list also
  matches *denials* — "there is no other road" is refused alongside "take the other
  road" — because `in` cannot read English and negation flips meaning. It refuses in the
  safe direction, at load, loudly. Say "It is the only road" instead (D-053).
- **Every broadcast-required impact with no template in the requested language is
  reported by name.** A village warned in a language nobody reads, with no sign on the
  officer's screen that its own was never written, is the last-mile form of a false
  all-clear (invariant 6). `messages_for()` returns `missing` and `errors` separately: a
  missing template is a committee gap, a template that will not fill is a bug.
- **A crossing broadcast as a bare OSM way id is reported** (`messages_for().needs_name`),
  with a count of the broadcasts that name it. The message still renders — a labelled id
  beats silence — but *"the road crosses w747829218"* is not a sentence a chief can act
  on, and only an operator with satellite imagery can fix it. On the pilot graph 11 of 62
  village broadcasts name a bare id (`w747829218` ×8, `w160219946` ×3). The fix is a row
  in `data/operator_crossings.csv`, never code (D-055).
- `render()` returns `facts` alongside `text`, so a caller may check that the proper names
  the **engine** produced survived a translation — a check against the graph, not the prose.

### CAP alignment (v1.4)
Every field is derived from something the engine computed. Nothing is invented to fill a slot.

| CAP field | Source |
|---|---|
| `event` | `hazard.kind (severity)` |
| `severity` | `ontology.CAP_SEVERITY`: watch→Moderate, alert→Severe, emergency→Extreme |
| `certainty` | `Possible` if the blocking crossing's why-chain declares `assumed_structure:` (D-027), else `Likely` |
| `urgency` | **`Unknown`, always.** CAP urgency is a TIME. The trigger is a discharge return period; `lead_time_hrs` is an owner's completion deadline. We do not model arrival time (D-051) and will not write a value we never computed |
| `area` | the impacted object's name |
| `instruction` | the impact's playbook actions, **verbatim**, ordered by `(lead_time_hrs, owner_role, action_text)` |

`instruction` is the only correct home for `action_text`: prose would have to paraphrase
committee words, and an impact can carry more than one action (the B112 deck carries two
at 24 h), so "the action" is not a fact about an impact.

## Invariants (test these forever)
1. Same inputs → same impacts **and same why-chains**, always.
2. No impact without a complete why-chain.
3. Severing the only crossing isolates exactly the settlements with no alternate
   path — and nothing else.
4. No action without a matching impact; no impact state outside the fragility table.
5. Removing the hazard clears all derived impacts/actions (idempotent re-scan).
6. No impact may fail toward all-clear: an unknown structure, an unclassified crossing,
   a missing hazard target, or a stale schema must raise or over-warn — never reassure.
