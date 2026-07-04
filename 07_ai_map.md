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
1. **Message drafting & translation (the big one):** the engine emits structured
   facts (asset, state, why, action, owner, lead time, CAP-aligned fields); the edge
   drafts broadcast-ready text in English + local languages (Swahili, Lumasaba, ...).
   Always marked DRAFT; a human approves before anything is sent. This is the honest
   answer to the region's hundreds-of-languages problem.
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
degrades gracefully: the system runs fully without AI (English template text), which
is itself a resilience talking point.

## The pitch line worth memorising
"Everyone else points AI at the forecast. We point deterministic engineering at the
forecast — and AI at the only place it belongs in early warning: the words."
