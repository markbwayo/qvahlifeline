# 06 — Session Log

Newest entry at the top. Start each session by reading this. **Submission: 31 July
2026; internal deadline 30 July.**

## Session 20 — Phase 2 item 3: the map UI (D-048, D-049, D-050)
- Spine-name check PASSED: `w128611448` = "Manafwa Bridge (B112 town crossing)",
  `name_source=operator`. D-041 landed and the injection ran on the live DB. No
  links.py work needed. 35 crossings reconcile: 16 OSM + 1 operator-only culvert
  + 18 synth. Three are named.
- What changed: app/main.py rewritten (593 lines). tests/test_map_ui.py new (29).
  09 -> v1.3 (the read side). D-048..D-050. Docs committed before code.
- THREE LIVE BUGS, all on the read side, engine untouched and correct throughout:
  (1) both demo buttons called demo_flood() -> scope=reach -> 0 ISOLATED / 43
  REROUTED. Anyone opening port 8017 saw a calm district. (2) the action query had
  NO hazard filter (852 rows, five hazards) and sorted by lead time (three unnamed
  12 h fords above the 24 h B112 that cuts 51 villages). (3) COLORS.get(state,
  OK_GREEN) — a state with no colour would render as a healthy asset.
- Also closed: 32 of 35 crossings rendered as "(unnamed bridge)", the same string
  for w747829218 (cuts 8) and 18 synth candidates -> object id, per 09 v0.9.
  Coverage panel always rendered (uncovered vs unfired distinguished). Scan banner
  has four states. Footer no longer attributes WorldPop/SRTM (never ingested).
  db.init()/seed moved out of import into a FastAPI lifespan so a test can point
  db.DB_PATH at a temp file.
- The alert button KEPT and captioned (Bwayo's call): at Q5 both town bridges are
  AT_RISK, nothing severs. The table refusing to cry wolf, made clickable.
- Tested + result: tests/test_map_ui.py 29 new + prior = 216 passed. FOURTEEN
  negative controls run; each reddens exactly the tests it should, listed in the
  session transcript. The COLORS fallback control found a live latent all-clear.
- actions.generate() is now unused. Left in place (test-locked); retire post-hackathon.
- Live: hazard #14, 381 objects / 35 crossings on screen. Emergency: 62 ISOLATED,
  5 IMPASSABLE, 5 LIKELY_IMPASSABLE, 1 SEVERED, 4 SERVICE_AT_RISK = 77 impacts,
  213 actions, 0 uncovered, 15 precautionary. Spine reads "Manafwa Bridge (B112 town
  crossing)" and prints first at 51 cut off; w902422828 reads 0 cut / 2 carriers /
  precautionary. Alert: 5 LIKELY_IMPASSABLE + 5 AT_RISK, 0 ISOLATED — the fords go
  amber, the villages keep their road. Scan banner: "has not been run in this
  deployment" (grey), never silence. Header count corrected 362 -> 381 in 08.
- Header count corrected 362 -> 381 in 08: 362 is Step A ingest, +1 operator culvert,
  +18 synth candidates = what the live UI actually shows. A presenter saying 362 while
  the screen reads 381 hands a judge a free question.
- PROCESS BREACH, recorded not hidden (second occurrence; first was Session 17): the
  code commit a77e06d landed before the docs commit, and the docs commit also carried
  Session 19's uncommitted D-047 spec text and 08 limits. Hard rule 3 says spec first.
  Cause both times: the docs block is pasted into Notepad by hand while the code files
  are one click away. Countermeasure from Session 21: run `git status --short` and
  refuse to `git add app/` while any `.md` is dirty.
- The spine fires TWO actions at 24 h (DDMC comms warns the boda stages; district
  engineer inspects and signs). Not a duplicate — two playbook rows share the triple,
  D-043 fires both. Verified by reading the live rows, not assumed from the count.
- Days to deadline: 20 (internal 30 Jul).
- NEXT STEP: Phase 2 item 4 — message drafts at the AI edge (D-009, 07): the engine's
  structured facts in, English + Lumasaba/Swahili wording out, CAP-aligned, marked
  DRAFT, human-approved, behind one adapter, Gemini free tier. The engine never sends.

## Session 19 — Phase 2 item 2: live GloFAS triggers (D-047)
- What changed: hazards.py gains _get/_cached/_check_cell/reanalysis/forecast,
  annual_maxima/weibull_q, load_triggers/load_reach_points/thresholds, and a real
  scan_live(). New data/reach_glofas.csv (operator-verified cells) and
  data/triggers.csv (severity -> return period). 09 -> v1.2; D-047; 08 limits updated.
  Docs committed before code.
- THE FINDING: the 4.3 km demo reach w188321163 straddles THREE 0.05 deg GloFAS cells
  reading 67.7 / 6.1 / 91.5 m3/s mean - non-monotonic downstream, so two of them model
  a DIFFERENT river. GloFAS resolves one channel per 5 km cell. A dead cell reads 0.0
  and screams; a wrong cell reads 91.5 and looks like data. Cells are therefore
  operator-verified, never snapped. A "pick the highest-discharge cell" heuristic was
  proposed and WITHDRAWN - it selects 91.5, the wrong water.
- Also found: the reanalysis serves from 1997, not the requested 1984. n=29, not 42.
  reanalysis() now asserts the served window. Q10 rests on the 3rd-largest peak; Q20
  interpolates the top two; Q50 does not exist. Gumbel gives Q10=17.5 vs empirical 19.4
  by flattening the 1998 El Nino outlier -> empirical only, capped at Q20 (Bwayo's call).
- Decisions taken (Bwayo): Weibull empirical / annual maxima / watch=Q2, alert=Q5,
  emergency=Q10. Manafwa @ Bubulo: 12.37 / 14.81 / 19.37 m3/s. Emergency exceeded in
  1997, 1998, 2002 - three years in twenty-nine. The 62 is now "a 1-in-10-year flow".
- 0 of 33 river reaches are dead cells. 4 distinct cells cover all 33. 32 remain
  unverified: they cannot trigger, they are named in every scan, and scope=river
  (D-036) means one verified point floods the whole connected channel.
- Tested + result: tests/test_glofas_triggers.py (35 new) + prior = 187 passed.
  Seven NEGATIVE CONTROLS run: swallowed fetch failure / empty series / drifted cell /
  extrapolation past the record / dead cell as calm water / inverted severity ladder /
  stacked duplicate hazards - each break reddens exactly one test. The first control
  caught a test of mine that asserted a guarantee it never checked (it replaced _get
  wholesale). Fixed before shipping.
- Live tonight: forecast peak ~6.19 m3/s vs watch 12.37 -> quiet river, no hazard,
  numbers reported. The demo therefore stays USE_LIVE=0 (D-008), as planned.
- Days to deadline: 20 (internal 30 Jul).
- NEXT STEP: Phase 2 item 3 — map UI (app/main.py). States on the map, why-chain panel,
  action list ordered by consequence with the precautionary flag visible. FIRST CHECK:
  does the spine marker read "Manafwa Bridge (B112 town crossing)" or still
  w128611448? If the latter, main.py isn't reading objects.name. Also surface
  `uncovered` impacts and the live-scan status — a disabled scan must never render as
  a calm river.

## Session 18 — D-045 consequence ordering, and D-046, the bug it hid
- What changed: app/actions.py gains _dependents()/_carrier_counts(); actions_for()
  returns `consequence`, `carriers`, `precautionary`, ordered consequence-then-lead-time.
  No engine change. 09 -> v1.1; D-045, D-046 logged. Docs committed BEFORE code.
- D-045: a blocked crossing fires its closure action regardless of carriers or
  dependents. Zero dependents is a fact about OUR graph (7 bare OSM ford nodes have no
  carrier within 100 m), not the world. Suppressing would let a link-inference gap
  silence a warning (invariant 6). Suppression needs an operator classification in
  operator_crossings.csv, never a code rule. Regression-proved: wrote the "skip
  zero-carrier crossings" tidy-up; the new test goes red on it.
- Ordering bug fixed: by lead time alone, three unnamed fords (12h) printed above the
  B112 deck (24h) that cuts 51 villages. Urgency is not consequence.
- D-046, found by reading the live output, not by a test: both schools came back
  `consequence=0, precautionary=True` while isolated_from said 3 settlements lost a
  school. Cause — a settlement stores ONE why-chain, so a village losing clinic AND
  school records only the clinic; counting ISOLATED chains alone left the school with
  zero dependents. `precautionary` next to a shelter check for a school 3 villages just
  lost is an under-warning. propagate.py was correct all along: it writes the victims
  into the facility's own chain. The read side never looked. Now it does — charged to
  the FACILITY only, never to the bridges in that chain (their list is a union across
  all its lost settlements; cross-charging would let w128611448 claim w747829218's 8).
  Spine consequence unchanged at 51.
- Unplanned finding, keep for the pitch: `precautionary` is NOT "no carrier".
  w902422828 (Old Manafwa bridge) is blocked, HAS 2 carrier roads, and has consequence
  0. D-038 is now a data field, not just a line in the script.
- Tested + result: 41 in tests/test_playbook_actions.py (7 new) + prior = 152 passed.
  Both D-046 tests verified against the pre-fix code: W1 fails with 0 dependents.
- Live: <fill: precautionary count, the two schools' dependents, spine = 51>.
- Days to deadline: 20 (internal 30 Jul).
- NEXT STEP: Phase 2 item 2 — hazards.scan_live: GloFAS triggers, return-period-relative
  (D-005), require_reach() on every target (D-028), cached in db.geocache, USE_LIVE=0
  always works (D-008). Elgon discharge is 4–7 m³/s absolute — the trigger is relative,
  never absolute. One real judgement call waits: Open-Meteo returns a discharge series
  and no return periods. We decide explicitly what "return-period-relative" means, and
  log it, before a line of code.

## Session 17 — Phase 2 item 1: the action layer (D-043, D-044)
- What changed: app/actions.py rewritten (load_playbook, fire_actions, actions_for,
  clear_actions, generate() alias for main.py, CLI `python -m app.actions <hid> |
  --validate`); data/playbook.csv v1.0 = 18 actions over 13 (object_type, state,
  hazard_kind) triples; ontology.py gains HAZARD_KINDS, -> v0.3. 09 -> v1.0.
- PROCESS BREACH, recorded not hidden: the code commit (1bcc1d4) landed BEFORE the
  docs commit. Hard rule 3 says spec first. Docs pushed immediately after. No
  divergence resulted, but the ordering must not repeat — the docs block goes in the
  same message as the file downloads next time.
- The risk this step closes: an impact with no playbook row fires nothing and renders
  as a red village with an empty action column — indistinguishable from "no action
  needed". fire_actions RETURNS every `uncovered` impact by name. Proved by running
  the new test against a naive fire (look up, insert if found, move on): it reports
  success and never mentions the two ISOLATED villages.
- Also closed at CSV load: an ISOLATED action may not contain a road-alternate phrase.
  The BFS proved there is none; Old Manafwa bridge fails in the same flood (D-038).
- main.py calls actions.generate(hid) (Phase 0 name). Kept as a documented wrapper
  around fire_actions(); retire when main.py is rewritten (Phase 2 item 3). Test-locked.
- Tested + result: tests/test_playbook_actions.py (34 new: loader guards, invariant 4
  both halves, invariant 5 idempotence, invariant 1 ordering, coverage of every state
  the engine can emit) + prior = 145 passed on the VPS.
- LIVE, demo_flood_river("emergency"), real graph: 77 impacts -> 213 actions,
  uncovered NONE. By state: ISOLATED 186 (62 villages x 3), IMPASSABLE 10,
  LIKELY_IMPASSABLE 10, SERVICE_AT_RISK 6, SEVERED 1. By owner: DDMC comms 72,
  DDMC health 62, DDMC relief 62, district engineer 11, DHO 4, DEO 2.
- FOUND (for the map UI, not an engine bug): sorted by lead time, the list opens with
  three unnamed ford NODES (n8381841167/69/78) at 12h, above the B112 bridge that cuts
  51 villages at 24h. Ordering is by urgency, not consequence. Action panel must group
  by consequence. Open question for Bwayo: should a blocked crossing with ZERO carrier
  roads (7 of them, limitation #3) fire a closure action at all?
- Days to deadline: 21 (internal 30 Jul).
- NEXT STEP: Phase 2 item 2 — hazards.scan_live: GloFAS triggers, return-period-
  relative (D-005), require_reach() on every target (D-028), cached in db.geocache,
  USE_LIVE=0 always works (D-008). Elgon discharge is 4–7 m³/s absolute — the trigger
  is relative, never absolute.

## Session 17 — Phase 2 item 1: the action layer (D-043, D-044)
- What changed: app/actions.py rewritten (load_playbook, fire_actions, actions_for,
  clear_actions, CLI `python -m app.actions <hazard_id> | --validate`);
  data/playbook.csv v1.0 = 18 actions over 13 (object_type, state, hazard_kind)
  triples; ontology.py gains HAZARD_KINDS, -> v0.3. 09 -> v1.0 (playbook contract).
- The risk this step closes: an impact with no playbook row fires nothing and renders
  as a red village with an empty action column — indistinguishable from "no action
  needed". fire_actions now RETURNS every `uncovered` impact by name. Proved by
  running the new test against a naive fire (look up, insert if found, move on):
  it reports success and never mentions the two ISOLATED villages.
- Also closed: ISOLATED actions may not contain a road-alternate phrase (the engine
  proved there is none; Old Manafwa bridge co-fails). Enforced at CSV load.
- Tested + result: tests/test_playbook_actions.py (33 new: loader guards, invariant 4
  both halves, invariant 5 idempotence, invariant 1 ordering, coverage of every state
  the engine can emit) + prior = 144 passed.
- Live on the real graph: 77 impacts -> <fill> actions, uncovered <fill>.
- Days to deadline: 21 (internal 30 Jul).
- NEXT STEP: Phase 2 item 2 — hazards.scan_live: GloFAS triggers, return-period-
  relative (D-005), require_reach() on every target (D-028), cached in db.geocache,
  USE_LIVE=0 always works (D-008). Elgon discharge is 4–7 m³/s absolute — the trigger
  is relative, never absolute.
- main.py calls actions.generate(hid) (Phase 0 name). Kept as a documented wrapper
  around fire_actions() so the app survives this commit untouched; retire it when
  main.py is rewritten (Phase 2 item 3). Locked by a test.
- Open for the map UI: main.py's action panel does not yet surface `uncovered`
  impacts. A red village with no action must show WHY it has none.

## Session 16 — Step B closed: the demo numbers are real
- What changed: no code. Ran `demo_flood_river("emergency")` on the real graph and read
  the result for the first time. 09 → v0.9; D-038..D-042 logged; 08 storyline filled.
- The numbers: 77 impacts, 31 reaches flooded, **62 settlements ISOLATED — all 62 from a
  clinic**, 3 from a school; 2 clinics + 2 schools SERVICE_AT_RISK; 10 crossings blocked
  (5 IMPASSABLE, 5 LIKELY_IMPASSABLE); 1 road SEVERED. 0 REROUTED.
- Blockers: w128611448 (spine) cuts 51; w747829218 cuts 8; w160219946 cuts 3. All three
  are structure=bridge. No synthesised/unclassified crossing blocks anybody.
- Sensitivity (on a /tmp copy): reclassifying all 18 synth crossings ford→bridge changes
  nothing (62/3). The D-027 ford assumption is not load-bearing for the demo (D-039).
- Old Manafwa bridge co-fails but appears in 0/62 chains — it was never an alternate (D-038).
- Found: spine object has name=None (OSM `noname=yes`; name sits on `bridge:name`). Fix is
  an injection rule in links.py, spec'd into 09 v0.9 first (D-041).
- Found: 08 step 4 promised "open the alternate route" — there is none. Corrected.
- Tested + result: 105 passing (`pytest tests/ -q`).
- Days to deadline: 21 (internal 30 Jul).
- NEXT STEP: code commit — links.py operator-name fallback + its test. Then Phase 2 item 1:
  actions.py + data/playbook.csv with its invariant-4 test.

## Session 15 — Hazard scope (D-036); self-healing schema (D-037); STEP B ACTUALLY COMPLETE
- What changed: propagate.py gains flooded_reaches() and hazards.gains scope
  (reach|river) + demo_flood_river(); hazards table migrated via a new scope column.
  db.conn() now self-heals schema+migrations on every connection, not just inside
  init() — a live crash ("table hazards has no column named scope") showed a
  migration only run from init() gets missed by ad-hoc scripts. D-036, D-037 logged.
  09 -> v0.8 (hazard scope block; propagation steps rewritten to match D-034/D-035
  exactly; new invariant 6: never fail toward all-clear).
- Why scope existed to fix: Session 13's "complete" result (3 ISOLATED) was itself
  wrong — diagnosed in this session as two compounding graph defects (D-031: the
  road network was two disjoint components, no vehicle route crossed the river at
  all; D-032/033: reachability pooled facilities and mis-attributed SERVICE_AT_RISK).
  Fixing those first gave 0 ISOLATED / 43 REROUTED at single-reach scope — correct
  code, but physically wrong: villages were detouring across crossings on the SAME
  river that a real GloFAS spike would also flood. Scope=river fixes that.
- REAL RESULT, river scope, emergency severity, 31 connected reaches flooded:
  ~62 settlements ISOLATED, 0 REROUTED, 2 clinics SERVICE_AT_RISK. Sensitivity
  checked: widening scope to the 6 touching streams moves ISOLATED 62->63; the
  district's other named rivers move it not at all — the number is topology, not
  over-warning tuning. Exact isolated_from breakdown (clinic vs school vs water_point
  count) still to be captured after the D-037 fix lands on the VPS — do this first in
  the next session.
- Tested + result: tests/test_hazard_scope.py (21 new, incl. the exact real-world
  detour-vs-isolate scenario in miniature, and the no-init() legacy-table regression)
  + prior = 105 passed.
- Days to deadline: 21 (internal 30 Jul).
- NEXT STEP: on the VPS, confirm D-037 fixed the live crash, re-run demo_flood_river,
  capture the real isolated_from breakdown into this log. Docs (05/06/09) then commit
  separately from code, per the two-commit convention (see 00 / project instructions).
  Then Phase 2: actions.py + playbook.csv wired to real impacts (see Session 13's
  original next-step, still valid), then live GloFAS triggers, then map UI.

## Session 14 — Step B correctness pass: the graph didn't actually connect (D-031..D-035)
- What changed: links.py gains infer_crossing_connects() (roads carrying the same
  crossing become mutually `connects` via_crossing — D-031). propagate.py rewritten:
  reachability evaluated per facility not pooled (D-032); SERVICE_AT_RISK only for
  settlements that had and lost baseline access (D-033); blocking a multi-carrier
  crossing cuts the connects EDGE between its roads rather than deleting the roads
  (D-034), refined so the crossing itself (not the approach roads) holds the
  impassable state and only a single-carrier crossing severs its one road (D-035).
- Discovered (diagnostic, not a test - this is why the real-graph check habit
  matters): Session 13's "3 ISOLATED" result was an artifact. The real road network
  was TWO DISJOINT COMPONENTS (72 + 67 segments) because in OSM a bridge is its own
  way, so the approach and continuation roads share no vertex with each other - only
  10 of 83 settlements had ANY baseline road path to a clinic, before any flood.
  The 3 "isolated" villages were actually losing a same-bank SCHOOL, and
  Namuembi Medical Centre's SERVICE_AT_RISK was spurious (villages that could never
  have reached it). Both a false all-clear risk and a false alarm, simultaneously.
- Also found and fixed: an alternate REROUTED path could traverse a road that was
  itself SEVERED ("alternate_via: ...>w169219432>...", w169219432 SEVERED) - fixed by
  D-035's edge-cut/road-removal split.
- Tested + result: tests/test_crossing_connects.py (14 new, incl. a live-bug
  reproduction: old engine gives a village on a severed road NO IMPACT) + prior =
  87 passed.
- Days to deadline: 21 (internal 30 Jul).
- NEXT STEP: with the graph now actually connected, decide hazard scope - single
  reach lets villages detour over crossings on the same river that would also flood
  in reality. Simulate candidate scopes before choosing (see Session 15).

## Session 13 — Step B sub-step 5: why-chain + determinism fixes (NOT yet complete —
  see Sessions 14–15)
- What changed: propagate.py rewritten for correctness (per-settlement why-chain,
  severed-road endpoints, deterministic sorted BFS, alternate named on REROUTED).
  D-030 logged.
- FIRST REAL RESULT (emergency on w188321163, real 362-object graph): 18 impacts -
  4 IMPASSABLE + 3 LIKELY_IMPASSABLE crossings, 5 SEVERED roads, 3 ISOLATED
  settlements (Bumufuni Central, Nasitsapi, Bumufuni), 3 SERVICE_AT_RISK facilities
  including Namuembi Medical Centre. The engine found the clinic-access failure on
  its own; the SPOF was not pre-declared.
  **CORRECTION (Session 14): this result was itself an artifact of a disconnected
  road graph - see D-031. Do not cite the "3 ISOLATED" number; the real result is
  Session 15's ~62 ISOLATED at river scope.**
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
