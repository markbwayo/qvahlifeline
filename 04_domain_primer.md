# 04 — Domain Primer (early warning, plain + precise)

## A. The early-warning value chain and where it breaks
The WMO/UN model has four pillars: (1) risk knowledge, (2) monitoring & forecasting,
(3) dissemination & communication, (4) preparedness & response. East Africa is
strongest at pillar 2 (ICPAC, national met services) and weakest at 3–4: warnings are
issued for areas, not assets; in English/French, not local languages; with no
specified action, owner, or confirmation loop. The UN **Early Warnings for All
(EW4All)** initiative exists precisely because coverage of pillars 3–4 lags.

**Impact-based forecasting (IBF)** is WMO's shift from *what the weather will be* to
*what the weather will do*. Regionally it is implemented as hazard rasters × exposure
rasters (population grids) → risk maps per admin area. LIFELINE's thesis: the useful
unit of "what it will do" is not a raster cell — it is a **named asset and the
community depending on it**.

**Anticipatory action / forecast-based financing** (CERF, IFRC DREF, Red Cross FbF):
money is released *before* disaster when a pre-agreed **trigger** fires, funding
pre-agreed **actions**. Operationally these programmes struggle to write asset-level
triggers and action lists — LIFELINE generates exactly that structure.

## B. The failure case to cite (carefully and respectfully)
April–May 2024, Kenya (El Niño floods): area-level heavy-rain warnings existed days
ahead; at Mai Mahiu a blocked culvert/embankment failure sent a flash flood through
settlements that had received no specific instruction to move — dozens died. Same
season: bridges and causeways washed out across the region, isolating communities
from clinics and markets — impacts that were *structurally predictable from the road
network* before the water arrived. The lesson judges already believe: forecasts were
not the failure; asset-level translation was.

## C. Lifelines thinking (my engineering domain, the product's namesake)
"Lifelines" is the standard civil-engineering term for the networks communities
depend on: transport, water, power, health access. Two properties make them ideal
for an ontology:
1. **Dependencies are physical and mappable** — a village's clinic access runs over
   specific road segments and one specific bridge; a borehole serves a knowable set
   of settlements.
2. **Failure propagates along the network, not the raster** — flood severity at a
   point matters only through what it severs. Single points of failure (the only
   bridge, the only causeway) are where early warning has the highest value, and an
   engineer can identify them on sight.

## D. Hazard feeds in practice (Phase 2)
- **Riverine flood:** GloFAS forecasts river discharge globally on a grid; the
  Open-Meteo flood API exposes it per lat/lon, free, daily, ~5 km resolution, with
  return-period context. Trigger style: "forecast discharge exceeds the 5-year
  return-period flow within N days" → hazard object on that river reach. Resolution
  caveat: 5 km grid ≠ your exact stream; treat triggers as *watch/alert* levels, and
  say so honestly in the pitch.
- **Extreme rainfall (pluvial/landslide proxy):** CHIRPS observed rainfall (fast,
  public) for accumulation triggers, e.g. "3-day total > X mm on Elgon slopes".
  Landslide triggers are rainfall-threshold heuristics — label them as such;
  never present them as deterministic physics.
- **Drought (later):** CHIRPS anomalies / ICPAC seasonal outlooks; slow-onset logic
  (water-point stress) differs from flood logic — out of MVP scope, in the roadmap.

## E. Vocabulary judges use (use it back)
Impact-based forecasting; last mile; anticipatory action; trigger; lead time; common
alerting protocol (CAP — align message fields with CAP so national systems can adopt
outputs); community-based EWS; "co-production" (design with the district committee).

## F. Honesty lines that protect credibility
- OSM completeness varies — the model improves as officers add local assets;
  LIFELINE is a living district model, not a finished map.
- GloFAS/CHIRPS are screening-grade at village scale — LIFELINE prioritises and
  explains; verification stays human.
- Fragility rules are engineering heuristics v1, tuned per district with the
  committee — versioned, visible, and improvable, never black-box.
