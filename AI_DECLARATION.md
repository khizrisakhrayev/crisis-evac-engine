# AI Declaration

This project was built with AI assistance. Every AI-assisted task is logged below with its
timestamp, the tool used, the prompt (condensed to its key requirements), a short summary of
what was generated, and the files changed. Every change was reviewed by a team member before push.

Timestamps are the time of the git commit that completed each task.

---

## 2026-11-15 11:47
- *Tool:* Claude Code
- *Prompt:* "Use plan mode first, then implement. Scaffold the "Urban Crisis & Crowd Evacuation Engine" prototype: FastAPI + SQLite backend skeleton, static vanilla-JS frontend placeholders, seed data, CLAUDE.md and an AI usage log. No business logic yet, only the skeleton and stub endpoints. 1) Create CLAUDE.md with the given content (stack, layout, API contract, domain rules, design-for-change rules, mandatory after-task steps). 2) .gitignore, requirements.txt, .venv with python3.12. 3) Models Zone, Shelter, RoadNode, RoadEdge, SOS, Brigade, Alert; thresholds in config.py. 4) Idempotent Baku seed: 5 zones, 10 shelters, 6 brigades, a road graph of about 25 nodes / 45 edges, run on startup if the DB is empty. 5) All routers registered with stubs (501 or empty lists) except GET /api/health and GET /api/shelters. 6) Citizen and dispatcher placeholder pages, shared api.js, i18n.js (az/en + t()), style.css. 7) README with a short run section. macOS/zsh, no Docker, no extra frameworks, keep files small."
- *Summary:* Scaffolded the FastAPI + SQLite backend with models, config thresholds, an idempotent Baku seed and contract-matching stub routers, plus static citizen/dispatcher pages with az/en i18n. Health, shelter list (10 seeded), both pages and the WebSocket were verified with pytest and curl.
- *Files changed:* CLAUDE.md, README.md, .gitignore, requirements.txt, pytest.ini, docs/.gitkeep, backend/app/{main,config,db,models,schemas,seed}.py, backend/app/routers/{shelters,routing,sos,dispatch,auth}.py, backend/app/services/{geo,routing_provider,crisis,ws}.py, frontend/{citizen,dispatcher}/index.html, frontend/shared/{api.js,i18n.js,style.css}, tests/{conftest,test_smoke}.py

## 2026-11-15 11:59
- *Tool:* Claude Code
- *Prompt:* "Task B1+B2: implement nearest shelters, SOS submission and "I am safe" status. Fixes first: 1) move Baku Olympic Stadium to the Narimanov zone, seed stays idempotent; 2) a `utcnow()` helper returning naive UTC, used for every created_at default and time comparison; 3) pin dependencies with `pip freeze`. B1: GET /api/shelters/nearest (lat+lon or district required, 422 otherwise; district only uses the zone centre and lists that zone's shelters first; only open shelters; occupancy_pct, distance_m, is_full, zone name; sorted by distance) and POST /api/shelters/{id}/occupancy (dispatcher role, clamps to 0..capacity). B2: POST /api/sos with pydantic validation, zone via nearest_zone, 201; a repeat SOS from the same citizen updates the active record instead of duplicating; POST /api/sos/{id}/safe (404 if missing); GET /api/sos?status=&zone_id= newest first; a no-op `on_sos_created(db, sos)` hook in services/crisis.py called from the router. Routers thin, logic in services, don't touch frontend/, no routing or alerts yet. Add pytest tests for each acceptance item."
- *Summary:* Applied the three fixes and implemented nearest shelters, dispatcher-only occupancy updates, SOS submit with one active record per citizen, mark-safe and SOS listing, with the logic in new service modules. 22 tests pass.
- *Files changed:* requirements.txt, backend/app/{main,models,schemas,seed}.py, backend/app/routers/{shelters,sos}.py, backend/app/services/{clock,geo,crisis,shelters,sos}.py, tests/{test_shelters,test_sos,test_smoke}.py

## 2026-11-15 12:01
- *Tool:* Claude Code
- *Prompt:* "Small housekeeping task. Switch the AI usage log to a new format that keeps every prompt verbatim: rename the log to AI_DECLARATION.md with `git mv` and update every reference; a short header (project, team, tools, human-review rule); one entry per prompt, oldest first (date/time, Tool, full verbatim Prompt, Summary, Files changed); backfill entries for every prompt in this session with the real times; update step 2 of the mandatory after-task steps in CLAUDE.md to match."
- *Summary:* Renamed the log to AI_DECLARATION.md, rewrote it with verbatim prompts for every task so far, and updated CLAUDE.md to require the new format.
- *Files changed:* AI_DECLARATION.md, CLAUDE.md

## 2026-11-15 12:05
- *Tool:* Claude Code
- *Prompt:* "Small housekeeping task. Put the AI usage log into the team's final format: rewrite AI_DECLARATION.md in the given shape (intro paragraph, commit-time note, then one entry per task with date/time heading, Tool, Prompt condensed to its key requirements, 1-2 sentence Summary, Files changed); backfill one entry per finished task using the real commit times from `git log`, keeping prompts faithful to what was asked; replace step 2 of the mandatory after-task steps in CLAUDE.md with the given text."
- *Summary:* Rewrote AI_DECLARATION.md in the final condensed format with one entry per finished task, timestamped from the git commit times, and updated the CLAUDE.md logging rule.
- *Files changed:* AI_DECLARATION.md, CLAUDE.md
