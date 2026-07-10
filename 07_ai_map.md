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
Default Gemini API free tier; one adapter function so the provider can swap in an
afternoon; no resident model on the VPS; no Anthropic API in production. Edge failure
degrades gracefully: With no API key, or a dead endpoint, the edge returns `edge unavailable`; English and
   Lumasaba render regardless, because neither passes through a model. This is not a
   fallback bolted on — it is the architecture. the system runs fully without AI (English template text), which
is itself a resilience talking point.
With no API key, or a dead endpoint, the edge returns `edge unavailable`; English and
Lumasaba render regardless, because neither passes through a model. That is the
architecture, not a fallback bolted onto it.

## The pitch line worth memorising
"Everyone else points AI at the forecast. We point deterministic engineering at the
forecast — and AI at the only place it belongs in early warning: the words."
