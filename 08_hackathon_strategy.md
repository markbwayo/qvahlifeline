# 08 — ICPAC Hackathon Strategy ("Early Warning in the Age of AI")

## The facts (re-verify on the hackathon page before submitting)
- Remote build window ends with **online submission by 31 July 2026**. Internal
  deadline **30 July** (D-010).
- **Top 10 finalists** get a sponsored 5-day physical evaluation workshop; prize pool
  **$10,000**, **$4,000 first place**.
- Open across the 11 ICPAC member states; theme: climate communication & early
  warning solutions that protect communities in East Africa.
- Published judging weights ~**30/30/25/15** — confirm the exact labels on the
  official page and map the pitch to their wording, not ours.

## Criteria mapping (how LIFELINE scores)
- **Innovation:** first ontology/dependency-graph early-warning engine in the region —
  asset-level, why-chain-explainable, action-generating. Bounded claim: "no regional
  tool does this today" (Hazards Watch, FloodHub, SMS/IVR systems compared honestly).
- **Impact/relevance:** built directly on the region's named failure mode (Mai Mahiu
  2024 pattern: forecasts existed, asset-level translation didn't); outputs are
  CAP-alignable and anticipatory-action-ready (triggers → pre-agreed actions), which
  is ICPAC's own EW4All agenda.
- **Technical feasibility:** running system, free open data, ~$0 run-rate,
  deterministic and auditable core — demo live, not slideware. ICPAC's own GeoPortal
  layers cited/consumed where possible (judges seeing their data respected is worth
  points).
- **Presentation:** the 2-minute story below; a local founder-engineer from an
  affected region who has built the exact culverts the model watches.

## The demo storyline (rehearse until boring)
1. **The map:** "This is Manafwa district, at Bubulo — 381 objects: every bridge,
   ford, clinic, school, water point and village, and the dependencies between them.
   As a civil engineer from this region, I have built crossings like these. This graph
   is engineering knowledge, digitised." Thirty-five crossings. Sixteen came from OpenStreetMap, one I classified myself
   from satellite because no map has it, and eighteen the system found where a road
   line crosses a river line. It classified none of them. A machine can find a
   crossing; only an engineer says what it is."
2. **The hazard:** "GloFAS puts the Manafwa at its ten-year flow — 19.4 cubic metres
   per second. That level was reached in 1997, 1998 and 2002. Watch." *(click)*
3. **The propagation:** Manafwa Bridge — the B112, the town's only tarmac crossing —
   turns red. Sixty-two villages flag ISOLATED. Why-chain opens:
   flood → Manafwa reach → Manafwa Bridge → Bumayeku B → Namuembi Medical Centre.
   "No AI decided this. Physics and dependencies did. That's why an officer can trust it."
4. **The second bridge (the beat that wins it):** "There is another bridge twenty metres
   away — Old Manafwa bridge. Ask the engine to route over it." It won't. Same river
   reach, same flood, impassable at the same hour. It appears in **zero** of the 62
   why-chains. Nobody told the engine that. Reachability found it.
5. **The actions:** the playbook fires per impact: alert the chiefs by radio and
   WhatsApp (drafted in Lumasaba/Swahili at the AI edge, marked DRAFT, human-approved);
   pre-position the clinic drug kit on the south bank **before** the water arrives;
   stage closure signage. Owners and lead times on screen. **No alternate route is
   offered, because there is none — the engine says so rather than inventing one.**
6. **The close:** "Forecasts already exist. LIFELINE is the missing layer between the
   forecast and the field — and every action it proposes was pre-agreed by the district
   committee, which is exactly the structure anticipatory-action funders pay for."

## The three lines to say before a judge asks
- **Severity:** "This is `emergency` — a high return-period event, not a routine season.
  Both town bridges are engineered; at `alert` the table scores them AT_RISK and nothing
  is severed. We do not cry wolf."
- **Assumptions:** "Eighteen crossings are unclassified, and we score them as the *most*
  fragile structure, never the least. Reclassify every one of them as an engineered
  bridge and the 62 does not move. It is topology, not assumption."
- **Scale:** "Sixty-two named settlements. We do not have population per village and we
  will not estimate one on this stage."
- **Trigger:** "The threshold is not a number I chose. It is the tenth-largest of
  twenty-nine annual peaks in the GloFAS reanalysis for the cell that contains the
  town bridge — a cell I verified by hand, because the two cells either side of it
  model a different river and read twenty times the discharge. We compute Q2, Q5 and
  Q10 from the record. We refuse to compute Q50, because twenty-nine years cannot
  support it."

## Submission checklist (Phase 4, 26–30 Jul)
- [ ] Working deployment on VPS (port 8017) + `USE_LIVE=0` fallback tested
- [ ] 2-minute video (screen capture + voiceover; record by 27 Jul, two takes)
- [ ] Write-up per ICPAC's required format (check page/word limits on the portal)
- [ ] Architecture diagram (schematic in this bundle, refreshed)
- [ ] Repo README presentable; ODbL/CC-BY/data attributions visible in UI footer
- [ ] Honest-limits paragraph: OSM completeness; GloFAS ~5 km grid is screening-grade
      at village scale — three cells under one 4.3 km reach disagree 23x, so the
      trigger cell is operator-verified, not snapped; thresholds are empirical over
      29 annual maxima (1997–2025) and the code refuses to extrapolate past Q20;
      fragility rules are engineering heuristics v1; single-carrier crossings
      over-state the break (road ways not yet split at crossings); 7 bare ford
      nodes have no carrier road; demo severity is `emergency`, not a routine season
- [ ] Submit **30 July**, confirm receipt

## Week-by-week (from 4 Jul)
- **Wk1 → 11 Jul:** D-004 pilot data check + lock; OSM ingestion; propagation on real
  graph. *Milestone: real bridge, real village, real why-chain.*
- **Wk2 → 18 Jul:** GloFAS/CHIRPS live triggers + daily scan; playbook filled with
  committee-realistic actions; add/edit-object path for missing assets.
- **Wk3 → 25 Jul:** demo polish (map states, why-chain panel, message drafts EN +
  local language); dry-run the 2-minute demo; record video.
- **26–30 Jul:** submission pack, buffer for breakage, submit early.
- Passport/XPRIZE (17 Aug) resumes full priority 1 August.

## After the hackathon (the "life after" slide)
District/county disaster committees (Kenya NDMA/NDOC, Uganda OPM DDMCs) as users;
anticipatory-action funders and operators (CERF, IFRC DREF, Red Cross FbF) as the
revenue/deployment path — LIFELINE generates the trigger→action structures their
protocols require; ICPAC partnership as the asset-level layer under Hazards Watch.
