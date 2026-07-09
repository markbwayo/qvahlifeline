# 01 — Product Blueprint: Qvah LIFELINE

## One line
The layer between the forecast and the field: hazards propagate through a live map of
named bridges, roads, clinics, water points and villages — their real dependencies —
to produce per-asset impact predictions with why-chains and pre-agreed actions with
owners.

## The gap it fills (evidence)
- ICPAC and national met services already produce good hazard forecasts (East Africa
  Hazards Watch, GHACOF seasonal outlooks, grid-based impact tools built on CLIMADA /
  Flood-PROOFS). Their output stops at **grid cells and admin polygons**.
- The documented failure is the **last mile**: warnings exist, but no one is told
  *which* asset, *which* community, *which* action. In the April 2024 Kenya floods
  (Mai Mahiu), area-level warnings existed days ahead; the specific settlements in the
  flow path were not individually warned or evacuated — dozens died. The Horn of
  Africa drought produced the same pattern in slow motion.
- The UN **Early Warnings for All** initiative explicitly names warning dissemination
  and "translation into action" as the weakest pillars in the region.
- Meanwhile the region's infrastructure dependencies are brittle and knowable: one
  washed-out culvert isolates a market; one bridge is the only clinic route for a
  whole sub-county. **That dependency knowledge is engineering knowledge — my native
  domain — and no early-warning tool in the region models it.**

## What is genuinely new here
Existing tools are dashboards over rasters (hazard maps) or messengers (SMS/IVR
alerts). LIFELINE is an **ontology**: the district as a graph of typed objects and
links, where a hazard is an object whose effects propagate deterministically along
edges (river → bridge → road → village → clinic), producing impact objects, each
carrying its why-chain, each triggering playbook actions. Nobody in the ICPAC space
does asset-level, dependency-aware, action-generating early warning. (Novelty is
bounded honestly in 08 — say "no regional tool does this", not "no one on Earth".)

## Who it serves (and after the hackathon, who pays)
- **Demo user:** a District/County Disaster Management Committee officer.
- **After:** anticipatory-action funders and operators (CERF, IFRC DREF, Red Cross
  FbF programmes) who must pre-agree triggers and actions — LIFELINE is literally a
  machine for their trigger→action logic; national disaster agencies (Kenya NDMA/NDOC,
  Uganda OPM/DDMCs); NGOs pre-positioning supplies; ICPAC itself as the asset-level
  layer under Hazards Watch.

## The loop
1. **Model** the pilot area once: ingest OSM assets → objects; infer links
   (crosses, access_via, serves, downstream_of) with rules + human confirmation.
2. **Watch** free hazard feeds daily: GloFAS river discharge (Open-Meteo flood API),
   CHIRPS rainfall; thresholds create hazard objects.
3. **Propagate** deterministically through the graph → impact states per object,
   each with its why-chain.
4. **Act:** playbook maps (object type × hazard × severity) → actions with owner
   roles, lead times, and message templates (English + local language draft at the
   AI edge, human-approved).
5. **Learn:** after the event, officers mark what actually happened per asset —
   the feedback loop every regional review says is missing, and the future data moat.

## Build phases (deadline-scoped; dates in 08)
- **Phase 0 (this bundle):** seed graph + demo hazard + propagation + actions + map UI.
- **Phase 1:** real OSM ingestion for the locked pilot area; link inference + review.
- **Phase 2:** live GloFAS/CHIRPS triggers; playbook filled; daily scan loop.
- **Phase 3:** demo polish — why-chains on the map, message templates, offline-safe
  demo mode, 2-minute video.
- **Phase 4:** submission pack, submitted 30 July.
- **Post-hackathon:** feedback loop, WhatsApp/Telegram delivery to committee groups,
  second district, funder conversations.

## What success looks like
Hackathon: top-10 workshop invite minimum; the $4,000 first prize is the target.
After: one district committee using it through one rainy season; one anticipatory-
action pilot wired to its triggers. Long game: the asset-level ontology layer under
the region's early-warning stack — the same Qvah spine (deterministic rails for East
African decisions) in a third market.
