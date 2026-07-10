# 07 — Where the AI Lives (and where it is forbidden)

LIFELINE will be judged at an **AI-themed hackathon**, so this file matters doubly:
it is both our engineering doctrine and a pitch differentiator. The line for judges:
*"We use AI where language lives, never where lives depend on the number."*

## Forbidden zone (deterministic only)
Impact states, propagation results, why-chains, triggers, severities, and the
selection of actions. These come from: the link graph (physical facts), fragility
rules (versioned engineering heuristics), threshold triggers (published return
periods / rainfall accumulations), and the playbook table. Identical inputs →
identical outputs, always, and every output self-explains via its why-chain. A
hallucinated "bridge out" wastes an evacuation; a hallucinated "all clear" can kill.

## AI edges (each behind the single adapter `ai_edge(task, payload) -> draft`)
1. **Message drafting & translation:** the engine emits structured facts (asset, state,
   why-chain, hazard, severity, CAP-aligned fields). Broadcast text comes from
   `data/messages.csv` — committee-authored templates whose slots the engine fills
   deterministically. **Lumasaba is data, never generated** (D-052): it is the language
   that reaches the last mile, the one models are worst at, and the one nobody in the
   room can audit. The edge drafts **English polish and Swahili translation only**,
   always marked DRAFT, always human-approved before sending. The honest answer to the
   region's hundreds-of-languages problem is not to generate them — it is to make the
   committee's own words a first-class artifact and let the model help where it can be
   checked.
2. **Ingestion cleanup:** OSM tags are messy ("footbridge"? "ford"? name missing).
   The edge proposes object types/names for ambiguous features; a rule or the
   operator confirms before the object enters the graph.
3. **Playbook drafting:** given an object type × hazard, the edge proposes candidate
   actions from humanitarian practice for the committee to accept/edit — a starting
   point, never an authority.
4. **Officer Q&A (post-MVP):** natural-language questions over the graph ("which
   villages lose clinic access if Nabuyonga bridge goes?") compiled to graph queries —
   the *answer* still comes from the deterministic engine.

## Provider policy
Default Gemini free tier via one adapter, `ai_edge(task, payload)`; swapping providers
means editing `_call()` and nothing else. `urllib` only — no dependency for one HTTP POST.
No resident model on the VPS; no Anthropic API in production. The model string is
**env-configurable** (`GEMINI_MODEL`, default `gemini-2.5-flash`): Google cut free-tier
quotas in December 2025 and moved the 3.x Pro models to paid-only in April 2026, and a
demo hardcoded to a model string dies on someone else's release schedule. The key rides
in the `x-goog-api-key` header, never in the URL. Temperature is 0: a flood warning is not
a creative task. Free-tier inputs and outputs may be used by Google to improve their
products — our payload is public warning text naming villages and bridges, and carries no
personal data.

**The edge NEVER raises on failure**, and this is the exact inverse of `hazards.scan_live()`,
which raises on every feed failure. A dead river gauge reporting "no hazard" is
indistinguishable from a calm river. A dead translator costs a convenience: English and
Lumasaba render regardless, because neither passes through a model. Losing the forecast is
losing the warning. **A refusal, however, is not a failure:** asking the edge for Lumasaba
raises (D-052). Every output carries `approved: False` and `status: DRAFT` until a human
says otherwise.

## The pitch line worth memorising
"Everyone else points AI at the forecast. We point deterministic engineering at the
forecast — and AI at the only place it belongs in early warning: the words."
