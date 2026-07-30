# Qvah LIFELINE

## Problem

Flood forecasts describe hazard over grid cells and administrative areas. District
officers still need to know which named crossing may fail, which settlement loses
access, which service is affected, and who should act.

That last translation depends on local infrastructure. A bridge can carry the only
road between a settlement and its clinic. A map of flood depth alone does not encode
that dependency.

## What LIFELINE does

LIFELINE represents a district as typed objects and links. Objects include river
reaches, crossings, roads, settlements, clinics, schools, and water points. Links
record physical and service dependencies.

A flood trigger creates a hazard on the river graph. The engine calculates affected
crossings and roads, tests access to each facility, and records an impact on each
affected object. Every impact carries a why-chain. A data-owned playbook then selects
pre-agreed actions, owners, and lead times.

As an illustration, every impact records a chain in this form:

```text
flood -> Manafwa river reach -> Manafwa Bridge (B112 town crossing) ->
Bumayeku B -> Namuembi Medical Centre
```

## Why it is different

The operational core is deterministic. Triggers, severities, propagation, impacts,
why-chains, and action selection come from explicit thresholds, graph links,
versioned engineering heuristics, and playbook rows. Identical inputs produce
identical outputs.

AI is kept at the language edge. It does not decide whether a bridge is impassable,
whether a settlement is isolated, or which action should run. It only drafts
Swahili translations. Every translation is marked `DRAFT` and requires human
approval.

Lumasaba is handled differently. Its templates are committee-authored data and are
never generated. Those templates have not yet been written, so English-only ships.
The officer's screen lists every village missing a local-language template by name.
A model could generate Lumasaba text immediately, but nobody present could audit it.
The row therefore stays empty until the committee fills it.

## How it works

The propagation chain is:

```text
river-flood trigger
        |
        v
connected river reaches
        |
        v
crossings become affected under the fragility rules
        |
        v
carrier roads or crossing connections are removed
        |
        v
each settlement-to-facility path is tested again
        |
        v
ISOLATED, REROUTED, and SERVICE_AT_RISK impacts
        |
        v
why-chains and pre-agreed playbook actions
```

Reachability is evaluated per facility. A settlement that loses its clinic remains
isolated even if it can still reach a school. A facility is marked
`SERVICE_AT_RISK` only when a settlement had baseline access and then lost it.

## Results on the pilot district

The pilot graph covers Manafwa at Bubulo. It contains 381 objects and 35 crossings:
16 from OpenStreetMap, 1 operator-only culvert, and 18 synthesised from road and
river geometry.

At river scope and `emergency` severity, the engine produced 77 impacts:

- 62 settlements were isolated from a clinic.
- 3 of those settlements were also isolated from a school.
- The playbook produced 213 actions with 0 uncovered impacts.
- The message layer produced 72 broadcast messages with 0 errors.

The current VPS test suite reports 335 passing tests.

An earlier naming gap is fixed. Operator-reviewed rows now name `w747829218` as
Namakhutu bridge and `w160219946` as Namutebi bridge. Zero village broadcasts name
a bare object ID.

These are topology results, not population estimates. The system does not have a
population figure for each settlement.

### The second bridge

A second bridge stands about 20 metres from the main town crossing on the same river
reach. It is the natural alternate route and the first route anyone asks about. The
engine was never instructed to exclude it. It appears in zero of the 62 isolation
why-chains because it crosses the same reach and fails in the same flood.
Reachability found this without being instructed to.

## Honest limits

OpenStreetMap completeness varies. The district graph needs operator review and
local additions.

The GloFAS grid is about 5 km and is screening-grade at village scale. Three cells
under one 4.3 km reach disagree by more than an order of magnitude. The trigger cell is therefore
operator-verified, not automatically snapped.

Thresholds are empirical over 29 annual maxima from 1997–2025. The code refuses to
extrapolate past Q20. Fragility rules are versioned engineering heuristics v1.

A crossing represented by one carrier can overstate the break because road ways are
not yet split at crossings. There are 7 bare ford nodes with no carrier road. The
pilot result uses `emergency` severity, not a routine-season forecast.

Five unnamed OSM crossings still render as their object IDs. Each appears only
in its own closure notice, never in a village warning. The interface keeps this
source identifier visible instead of hiding the missing OSM name.

There is no delivery integration. Swahili is an optional AI translation draft, not
an approved warning. Lumasaba committee templates have not been written.
English-only ships. The officer's screen names every village whose local-language
template is missing. Those rows remain empty until the committee supplies text it
can audit.

## What is next after the hackathon

The next work is co-production with a district disaster committee. Officers should
review missing assets, crossing classifications, fragility assumptions, and every
playbook row.

The pilot should then be run through a rainy season. Officers can record what
actually happened to each asset and use that evidence to revise the district model.

The same trigger-to-action structure can support anticipatory-action programmes.
Expansion to another district should follow only after the pilot graph, operating
procedure, and committee-authored language templates have been validated.
