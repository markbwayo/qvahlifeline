# 06 — Session Log

Newest entry at the top. Start each session by reading this. **Submission: 31 July
2026; internal deadline 30 July.**

## Session 13 — Step B sub-step 5 COMPLETE: the spine is proven
- What changed: propagate.py rewritten for correctness (per-settlement why-chain,
  severed-road endpoints, deterministic sorted BFS, alternate named on REROUTED).
  D-030 logged. STEP B IS COMPLETE.
- FIRST REAL RESULT (emergency on w188321163, real 362-object graph): 18 impacts -
  4 IMPASSABLE + 3 LIKELY_IMPASSABLE crossings, 5 SEVERED roads, 3 ISOLATED
  settlements (Bumufuni Central, Nasitsapi, Bumufuni), 3 SERVICE_AT_RISK facilities
  including Namuembi Medical Centre. The engine found the clinic-access failure on
  its own; the SPOF was not pre-declared.
- Bugs closed: three false-negative paths in the engine, incl. a village on a SEVERED
  road reporting NO IMPACT (a live false all-clear). Regression-tested by running the
  new suite against the old engine (5/10 fail).
- Tested + result: tests/test_spine_isolation.py (10 new) + prior = 73 passed.
- Days to deadline: 22 (internal 30 Jul).
- NEXT STEP: Phase 2 - actions.py/playbook.csv wired to the real impacts, then the
  map UI showing states + why-chains. Also open: hazard scope (see below).

## Session 12 — Step B sub-step 4: demo hazard on the real Manafwa reach
- What changed: hazards.py demo now targets w188321163 via resolve_demo_reach()
  (env -> real -> seed -> raise); create_hazard validates target existence and type;
  D-028 + D-029 logged.
- Tested + result: tests/test_demo_hazard.py (14 new) + prior = 63 passed. Live
  propagation at emergency on the real graph: <fill states + counts>.
- Known defect (fix in sub-step 5): propagate.py builds a settlement's why-chain from
  an ARBITRARY severed road (`next(iter(severed))`), not the one on that settlement's
  blocked path. State is correct; the explanation can name the wrong bridge.
- Days to deadline: 22 (internal 30 Jul).
- NEXT STEP: sub-step 5 — prove the spine: assert the settlements whose only clinic
  route crosses the Manafwa town bridges go ISOLATED with a CORRECT why-chain, and
  villages with an alternate route go REROUTED. Fix the arbitrary-severed-road bug.

## Session 11 — Step B sub-step 3c: conservative unknown-structure fragility (D-027)
- What changed: ontology.py gains resolve_structure() + bridge_state_explained() and
  UNKNOWN_STRUCTURE_ASSUMPTION="ford"; propagate.py drops its unsafe "bridge" default
  and records assumed_structure in the why-chain. ontology -> v0.2; 09 -> v0.6.
- Bug closed: at ALERT an unclassified crossing scored AT_RISK (non-severing) -> no
  road severed -> no village isolated. A false all-clear on all 18 synth crossings.
  Now LIKELY_IMPASSABLE -> severs. Engineered bridges unchanged.
- Tested + result: tests/test_conservative_fragility.py (12 new: unit + real-engine
  integration + why-chain assertions) + prior = 49 passed. Includes a test proving the
  assumed structure is at least as fragile as EVERY known structure at every severity.
- Days to deadline: 22 (internal 30 Jul).
- NEXT STEP: sub-step 4 — point the demo hazard at the real Manafwa reach w188321163
  (replace seed id R1 in hazards.py), run propagation on the real graph, inspect which
  settlements come back ISOLATED / REROUTED.

## Session 10 — Fix: demo spine had zero carriers (D-026)
- What changed: carries threshold 15m -> 20m (measured: spine's own road 17.7 m,
  other town bridge's road 23.9 m); added nearest-road fallback (100 m cap,
  geom_carries_fallback) for any crossing left with zero carriers.
- Discovered: w128611448 (the demo spine) had ZERO carriers after 3a - a live
  wrong-impact bug (a flood on the spine would have severed nothing, isolated no
  one). Caught by running the carrier-check on the real graph before proceeding.
- Tested + result: tests/test_infer_crossing_links.py + prior = 37 passed, including
  a regression test locking in the exact real-world gap (18 m captured / 24 m not).
  Live re-run: w128611448 now carried by <...> via geom_carries. <F> crossings used
  the fallback: <list>. <N> still with no carrier at all.
- Days to deadline: 22 (internal 30 Jul).
- NEXT STEP: sub-step 3c - fix the unsafe bridge_state fallback in ontology.py
  (structure=None currently defaults to the LEAST fragile "bridge" type; must
  default to MOST fragile so needs_review/no-carrier crossings can't silently
  rescue a route). Must land before pointing a hazard at the real reach.

## Session 9 — Step B sub-step 3b: reachability graph inference
- What changed: app/links.py gains infer_road_network() (connects) and
  infer_access_and_serves() (access_via + serves); 09 -> v0.5 (access_via covers
  facilities); D-025 logged.
- Tested + result: tests/test_infer_reachability_graph.py + prior = 33 passed,
  including a real-engine end-to-end that returns ISOLATED. Live on real graph:
  <connects> connects, <access> access_via (farthest <m> m), <serves> serves.
- Days to deadline: 23 (internal 30 Jul).
- NEXT STEP: sub-step 3c — conservative fragility for unclassified crossings (fix the
  `structure or "bridge"` fallback so needs_review crossings are treated MOST fragile,
  not least), ontology.py + bridge_state unit test + 09 fragility note. MUST land
  before any hazard is pointed at a real reach.

## Session 8 — Step B sub-step 3a: crosses + carries inference
- What changed: app/links.py gains infer_crossing_links() (crosses = nearest reach
  <=50 m; carries = vehicle roads <=15 m; footpath gate; synth-aware; idempotent).
  D-024 logged. No 09 change (crosses/carries/inferred_by already in spec).
- Tested + result: tests/test_infer_crossing_links.py + prior = 26 passed. Live on real
  graph: <C> crosses, <K> carries. Town-bridge carrier check: w128611448 -> <...>,
  w902422828 -> <...> (no cross-link / cross-link -> retuned).
- Days to deadline: 23 (internal 30 Jul).
- NEXT STEP: sub-step 3b — connects + access_via + serves (the reachability graph),
  each with inferred_by + a test.

## Session 7 — Step B sub-step 2: geometric crossing synthesis
- What changed: app/links.py gains synthesise_crossings() (vehicle road×river
  intersections -> source=synth, needs_review, NO structure); 09 -> v0.4; D-023 logged.
- Tested + result: tests/test_synthesise_crossings.py + sub-step 1 = 17 passed
  (intersection math, existing-crossing suppression, footpath ignored, parallel = none,
  two-crossings-far-apart, idempotent). Live synth on real graph: <N> candidates created.
- Days to deadline: 24 (internal 30 Jul).
- NEXT STEP: sub-step 3 — infer links (crosses/carries/connects/access_via/serves/
  on_floodplain) from geometry, each with inferred_by; decide conservative propagation
  treatment of needs_review crossings (with a test).

## Session 6 — Step B sub-step 1 fix: deterministic crossing reconciliation
- What changed: links.py gains match_hint + ambiguous-cluster refusal; operator CSV
  gets a match_hint column (TC row -> w128611448); 09 -> v0.3; D-022 logged. Spine
  corrected to Manafwa Bridge B112 (w128611448), NOT Old Manafwa bridge.
- Discovered: two real bridges 19.8 m apart on the same reach w188321163; 4 clinics all
  ~1.3 km north; settlements on both banks -> south-bank settlements depend on the
  crossing to reach north-bank clinics (the isolation story, to be proven in sub-step 5).
- Tested + result: tests/test_inject_operator.py — 10 passed (hint resolves the cluster,
  no-hint cluster refuses, bad hint refuses, idempotent, atomic rollback).
- Days to deadline: 25 (internal 30 Jul).
- NEXT STEP: sub-step 2 — synthesise crossings where a vehicle road polyline intersects
  a river_reach polyline and no crossing exists within ~50 m, + its test.

## Session 5 Close - Map polish (D-021): roads/rivers as polylines from stored geometry; assets+crossings
  as dots. Render-tested (line/dot split, geomless fallback, braces). Phase 1 Step A +
  hardening + map polish all committed. Graph unchanged (362 objects).
- NEXT STEP: Step B on OPUS — link inference with test cases (see handoff).

## Session 5 — Phase 1 Step A COMPLETE (real Manafwa district loaded)
- What changed: Vehicle-road crossing filter applied. Loaded 362 objects (16 crossings,
  4 clinics, 83 settlements). Old Manafwa bridge (tertiary) confirmed as the operator's
  TC crossing. Cache-by-box-only trap hit — needed --refresh; hardening pending.
- Tested: crossing filter verified; live counts in window; graph written.
- Days to deadline: 25 (internal 30 Jul)
- NEXT STEP: (a) small hardened ingest_osm.py (query-hash cache key + fetch backoff),
  then (b) quick map polish (roads/rivers as polylines), then Step B on OPUS
  (inject operator_crossings.csv, synthesise road×river crossings, infer all links,
  target the real Manafwa reach, confirm TC-bridge failure isolates villages from a clinic).
- Hardened ingest (D-020): query-hash cache key + fetch backoff + failure isolation +
  write-abort. Tested offline (4 hardening checks + happy-path write). Graph unchanged
  (362 objects already loaded). --refresh no longer routinely needed.

## Session 5 — Pilot box corrected; operator crossings captured
- What changed: Box moved north to 0.905,34.260,0.962,34.305 to include the Manafwa
  Town Council bridge (0.9406,34.2802) and north footpath culvert (0.9565,34.2897).
  Re-ingest counts: <fill>. data/operator_crossings.csv created (2 crossings,
  operator-classified: bridge=main road, culvert=footpath).
- Days to deadline: 25 (internal 30 Jul)
- NEXT STEP: Step B (Opus, with test cases) — inject operator_crossings.csv as
  source=operator crossing objects; synthesise any extra road×river crossings from
  geometry; infer crosses/carries/connects/access_via/serves/on_floodplain; point the
  demo hazard at the real Manafwa reach; confirm the TC bridge failing isolates the
  right villages from the clinic.

## Session 4 — Phase 1 Step A loaded; map recentered on pilot
- What changed: Ran ingest_osm (live) → 180 objects written (source=osm) for the
  Manafwa @ Bubulo box. Healthy: 79 settlements, 12 schools, 2 clinics, 82 roads,
  3 river reaches. CROSSINGS THIN: only 2 tagged bridges (off-town, no culverts/fords)
  — expected OSM gap (D-016). main.py recentered (fitBounds), header shows live
  count/source, crossings emphasized on the map.
- Tested + result: ingest tested offline (classification/dedupe/structure/fragility);
  main.py rendered + brace-checked with seed and osm data — pass. Live: 180 objects,
  map frames pilot.
- Map review notes (fill): real Manafwa crossings I can see are at <...>; SPOF
  candidate <...>.
- Days to deadline: <fill> (internal 30 Jul)
- NEXT STEP: Step B (Opus, with test cases) — synthesise crossings from road×river
  intersections + infer crosses/carries/connects/access_via/serves/on_floodplain from
  stored geometry; then point the demo hazard at the real river_reach. I classify the
  key crossings' structure.

## Session 4 — Phase 1 Step A: OSM ingest built + loaded (Manafwa @ Bubulo)
- What changed: app/ingest_osm.py written against real Phase 0 schema. Objects only,
  no links. Crossings -> type bridge + props.structure. Geometry stored for Step B.
  Dry-run count: <fill> objects; final bbox <fill>. SPOF crossing chosen: <fill>.
- Tested + result: mocked end-to-end offline (classification, dedupe, structure map,
  schema round-trip, fragility lookup) all pass; live dry-run on VPS <fill counts>.
- Days to deadline: <fill> (internal 30 Jul)
- NEXT STEP: Step B — link inference (crosses/carries/connects/access_via/serves/
  on_floodplain) from stored geometry, WITH test cases, then point demo hazard at the
  real river_reach + recenter main.py map. RUN THIS ON OPUS (architecture fork).

## Session 3 — Pilot corridor locked (Manafwa @ Bubulo); schema pull before ingest
- What changed: Corridor locked (D-014): Manafwa R @ Bubulo, tight bbox ~25 km².
  SPOF crossing not pre-named — chosen from ingest output.
- Awaiting: app/db.py + app/ontology.py to write ingest_osm.py against the real
  Phase 0 schema (avoid corrupting the objects table with a guessed schema).
- Days to deadline: 25 (internal 30 Jul)
- NEXT STEP: build ingest_osm.py (Step A — OSM assets → objects; store way geometry
  in props_json for later link inference; print per-category counts + crossings list;
  idempotent wipe+reload of pilot objects). Then Step B (link inference:
  crosses/access_via/serves/on_floodplain) as an Opus session with test cases.

## Session 2 — Pilot region locked (Mt Elgon); corridor selection open
- What changed: Ran scripts/day1_datacheck.py on the VPS. Result logged in 05 (D-004):
  Mt Elgon wins on every axis (density 1107 vs 119 /100km², crossings 490 vs 156,
  river signal 2 vs 0; Isiolo GloFAS = 0.0 across the board → drought corridor).
  Region LOCKED = Mt Elgon.
- Flagged: check bbox (~12,266 objects) is far too big to ingest — must tighten to one
  river corridor (~150–400 objects) before ingest_osm.py (new decision D-013). Also:
  Elgon GloFAS discharge is low in absolute terms (4–7 m³/s) — keep triggers
  return-period-relative (D-005) and verify a real spike during demo prep.
- Tested + result: n/a (read-only data check)
- Days to deadline: 25 (internal 30 Jul; submission 31 Jul)
- NEXT STEP: Bwayo names the tight pilot corridor + the specific single-point-of-failure
  crossing and the villages/clinic it serves → tighten bbox → build + run ingest_osm.py
  (OSM → objects; infer crosses/access_via/serves/on_floodplain per 09) with link-
  inference test cases.

## Session 1 — Phase 0 starter delivered
- Built and tested the ontology engine end-to-end on a seed graph (river, bridge,
  culvert, road segments, two villages, clinic, borehole, school): demo flood hazard
  → propagation → bridge IMPASSABLE, village ISOLATED with full why-chain → playbook
  actions with owners and lead times. Leaflet map UI renders objects, hazard state,
  why-chains, and the action list.
- Verified: severing the bridge isolates exactly the villages whose only access_via
  path crosses it; villages with an alternate route degrade to AT_RISK, not ISOLATED.
- NEXT STEP (Phase 1, Week 1): run the D-004 Day-1 data check on both pilot
  candidates (OSM asset density via Overpass count queries + GloFAS point sanity via
  Open-Meteo for the main rivers), lock the pilot in 05, then run ingest_osm.py for
  the locked bounding box.

## Template
## Session N — <title>
- What changed:
- Tested + result:
- Days to deadline:
- NEXT STEP:
