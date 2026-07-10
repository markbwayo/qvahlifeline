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

## What the edge may be told (v1.1, D-059)
`ai_edge(task, payload)` accepts exactly three payload keys — `text`, `target_lang`,
`preserve` — and **an unknown key raises**. Not a subset it reads with a remainder it
ignores: a closed set. Hard rule 1 says a model never sees an impact, and until D-059
nothing enforced it; a later *"pass the impact id through so we can log it"* would have
put a graph identifier into a prompt with no test to redden. The module imports `db` for
its draft cache and **nothing else from the package**, and `tests/test_ai_edge.py` parses
the file with `ast` to prove it — catching `import propagate` and `from messages import …`
alike. Hard rule 1 is now a property of the signature, not of a promise.

## Provider policy (v1.2)
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

**Drafts are cached** in `geocache` by `(model, target_lang, SYSTEM, text)`. The system
prompt is part of the input (D-059): tune it after a rehearsal and, without it in the key,
every cached draft was produced under wording nobody recorded — a reproducibility hole in
the one layer whose output a human signs. Failures are never cached. The free tier is
~10 RPM against 72 broadcasts, so the cache is not an optimisation.

### Serving a draft is not making one (D-060)
The order is **`gate → cache → key → provider`**. An API key is required to *make* a draft,
never to *serve* one, and the cache key does not contain it. Before D-060 an empty key
blocked a cached draft while a garbage key sailed straight past it — one of those two had
to be wrong. If `.env` fails to load on demo morning, seventy-two rehearsed Swahili drafts
still render, each flagged `cached: True`. The gate stands in front of both: `AI_EDGE_LIVE=0`
means *do not use the edge*, and a cache is part of the edge.

**`cached_draft(text, lang) -> dict | None`** is the read-only door. It never calls the
provider, never writes, and returns `None` on a miss. It is the **only** function a page
render may call. A single round trip to Google was measured at **11.3 s** on the pilot VPS
— `getaddrinfo` returned an IPv6 address with a dead route, and `urllib` walks that list in
order while `curl` races the families and looked healthy at 0.37 s. Sixty-two villages ×
one round trip is not a page load, and the free tier's 10 RPM forbids it regardless.
`cached_draft` is ungated on purpose: `AI_EDGE_LIVE` governs whether we may *speak* to a
model, and reading a draft we already hold speaks to nobody.

**Any live probe of the edge that reuses a previously translated string is unfalsifiable**,
because it never reaches the provider. It returns a cached `DRAFT` in ~0.1 s and looks like
a pass. `--selftest` therefore takes its own text. This mistake was made twice in Session 23,
both times while checking a guard that was in fact correct.

### One retry, and only where a retry means something (D-057)
`429` and `503` mean the request was well formed and the server declined to answer *now*.
A live 503 on `gemini-2.5-flash` was observed in Session 22 — free-tier demand, and the
most likely demo-day failure. **One two-second pause, one more attempt.**

`400`, `401`, `403` and `404` mean the request will never succeed. Retrying burns quota,
doubles the latency of a certain failure, and delays the only diagnostic that matters: a
rotated key that never reached `.env` arrives as a `403`, and the presenter must see it in
one second, not twenty-two. **A timeout is not retried either** — a 429 is a prompt
response, a hang is not, and a hang offers no evidence the second attempt would return.
Worst case is `2 × TIMEOUT_S + RETRY_PAUSE_S` = 42 s, reachable only if a slow server
answers 429 twice; the realistic bound is one round trip plus two seconds.

The test that carries this decision is not *"a 429 retries"* — that passes against code
which retries everything. It is **"a 400 does not"**, asserted on the provider call count.
Every returned dict carries `retried`. Verified live against Google: a bad key returns
`HTTP 400 ... API key not valid`, `retried: false`, on a cold cache.

### Two switches, because there are two different guarantees (D-058)
`USE_LIVE` gates the **deterministic core** — the river feed, the scan, the trigger. It
exists because a dead gauge that returns "no hazard" is indistinguishable from a calm
river, and that kills people (D-008). It is not read by the edge.

`AI_EDGE_LIVE` (default `0`) gates **the edge, and only the edge**. Disabled status is
`edge disabled (AI_EDGE_LIVE=0)` and names the variable that would enable it.

The edge does not need `USE_LIVE`'s protection, because it is **safe by construction** —
which is the property `USE_LIVE` was invented to guarantee by fiat. A dead edge returns
`edge unavailable`; the English and the Lumasaba render exactly as before, because neither
ever passes through a model. Coupled, the switches force a choice between the graph-sourced
flood we need on stage and the live Swahili draft we want.

**Demo day runs `USE_LIVE=0, AI_EDGE_LIVE=1`.** The flood comes from the graph; the Swahili
comes from the model. Those are different guarantees and they are built differently.

### Failure vs refusal
**The edge NEVER raises on failure**, and this is the exact inverse of `hazards.scan_live()`,
which raises on every feed failure. A dead river gauge reporting "no hazard" is
indistinguishable from a calm river. A dead translator costs a convenience: English and
Lumasaba render regardless, because neither passes through a model. Losing the forecast is
losing the warning. **A refusal, however, is not a failure:** asking the edge for Lumasaba
raises (D-052), as does an unknown task, an unlisted language, or a payload key it must
never be handed (D-059). Every output carries `approved: False` and `status: DRAFT` until a
human says otherwise.

`status: "edge unusable"` returns the **rejected** draft so an operator can judge whether
the sanity check was too strict. A caller renders it as REJECTED. **Only `status == "DRAFT"`
is a draft** — a panel that prints `draft or "-"` shows failed text as a proposal.

## The pitch line worth memorising
"Everyone else points AI at the forecast. We point deterministic engineering at the
forecast — and AI at the only place it belongs in early warning: the words."

And, when a judge asks why the demo runs offline:
"The flood is from the graph, because a dead feed must never look like a calm river. The
Swahili is live, from the model, because a dead translator costs nothing. Those are
different guarantees and we built them differently."
