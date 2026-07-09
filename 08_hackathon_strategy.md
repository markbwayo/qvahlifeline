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
1. **The map:** "This is <pilot district> — every bridge, culvert, clinic, water
   point and village, and the dependencies between them. This one bridge is the only
   clinic route for 11,000 people. As a civil engineer, I've built these crossings —
   this graph is engineering knowledge, digitised."
2. **The hazard:** "This morning's free GloFAS forecast puts the river above its
   5-year flow in 3 days. Watch." *(click)*
3. **The propagation:** bridge turns red → villages flag ISOLATED → why-chain opens:
   flood → bridge → road → village → clinic. "No AI decided this — physics and
   dependencies did. That's why an officer can trust it."
4. **The actions:** playbook fires: notify chiefs (messages drafted in Lumasaba/
   Swahili by AI, approved by a human), pre-position clinic stock across the bridge,
   open the alternate route. Owners and lead times on screen.
5. **The close:** "Forecasts already exist. LIFELINE is the missing layer between
   the forecast and the field — and every action it proposes was pre-agreed by the
   district committee, which is exactly the structure anticipatory-action funders
   pay for."

## Submission checklist (Phase 4, 26–30 Jul)
- [ ] Working deployment on VPS (port 8017) + `USE_LIVE=0` fallback tested
- [ ] 2-minute video (screen capture + voiceover; record by 27 Jul, two takes)
- [ ] Write-up per ICPAC's required format (check page/word limits on the portal)
- [ ] Architecture diagram (schematic in this bundle, refreshed)
- [ ] Repo README presentable; ODbL/CC-BY/data attributions visible in UI footer
- [ ] Honest-limits paragraph (OSM completeness, GloFAS resolution, heuristic
      fragility v1) — pre-empting the tough question beats dodging it
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
