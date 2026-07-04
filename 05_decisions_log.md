# 05 — Decisions Log

Append a line whenever a real decision is made. Newest at the bottom.

| ID | Decision | Why |
|----|----------|-----|
| D-001 | Ontology doctrine: typed objects + links + hazard propagation + action playbook; deterministic core, AI at edges only | The product IS the semantic model; wrong impacts/actions can cost lives — must be exact, explainable, testable |
| D-002 | SQLite two-table graph (objects, links) + pure-Python BFS; no graph DB, no networkx at MVP | District-scale graphs are small; keep installs trivial and the engine readable |
| D-003 | Port 8017 at /opt/lifeline, repo markbwayo/qvahlifeline, git-only workflow | Next free Qvah port; standard plumbing |
| D-004 | Pilot area decided by a Day-1 data check, not preference: candidate A = Marsabit/Isiolo corridor (research-verified coverage, Kenya NDMA relevance), candidate B = Mt Elgon corridor Mbale–Manafwa–Bududa (founder story, flood+landslide history). Check OSM asset density + GloFAS river points for both; pick the one that demos better; log result here | Depth in one convincing area beats breadth; don't ingest before locking |
| D-005 | Hazard feeds: GloFAS via Open-Meteo flood API + CHIRPS; triggers are watch/alert screening levels, stated honestly | Free, no-key, daily; 5 km resolution means we prioritise and explain, not predict per-metre |
| D-006 | Every impact stores its why-chain (ordered hazard→object link path); UI must render it | Explainability is the differentiator vs dashboards and vs black-box AI |
| D-007 | Playbook and fragility rules are versioned data (CSV / one table), never buried in code | Committees must be able to read, challenge, and tune them |
| D-008 | Demo must run with USE_LIVE=0 (cached/seeded data) | A dead network can never kill the pitch or the video |
| D-009 | Message templates aligned to CAP fields; English + one local language (AI-drafted, human-approved, marked as draft) | National adoption path + last-mile reality; AI never decides content of the impact, only wording |
| D-010 | Scope guard: submission on 30 July, one day early; any feature threatening that is cut and logged | Hackathons are lost to deadline slippage more than to missing features |
| D-011 | Post-event feedback capture (what actually happened per asset) is in the roadmap/pitch but NOT built for MVP | It's the moat later; it's scope creep now |
| D-012 | No Anthropic API in production; edge model default = Gemini free tier behind one adapter function | Cost + policy consistent across Qvah |
