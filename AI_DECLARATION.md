# AI Usage Declaration — Urban Crisis & Crowd Evacuation Engine

Team: Xizri Saxrayev, Anar Hümmətli, Ülvi Mustafayev

Tools used: Claude Code in VS Code (Opus 5.5 / Fable 5.2) as executor; Claude project chat as architect and reviewer.

Rule: every AI change is reviewed by a human before push.

## Prompt log (oldest first)

2026-11-15 11:46
Tool: Claude Code
Prompt: "Use plan mode first, then implement.

GOAL
Scaffold the "Urban Crisis & Crowd Evacuation Engine" prototype: FastAPI + SQLite backend skeleton, static vanilla-JS frontend placeholders, seed data, CLAUDE.md, AI_LOG.md. No business logic yet, only the skeleton and stub endpoints.

STEP 1: create CLAUDE.md with exactly this content:

# Urban Crisis & Crowd Evacuation Engine
Hackathon prototype (deadline 15:00). Working MVP first, no over-engineering.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 + SQLite (crisis.db), WebSocket
- Frontend: vanilla JS + Leaflet (CDN), no build step, served by FastAPI StaticFiles
- Tests: pytest (+ httpx TestClient), Locust for load tests
- Run: `source .venv/bin/activate && uvicorn backend.app.main:app --reload` (port 8000)
- Test: `pytest -q`

## Layout
backend/app/: main.py config.py db.py models.py schemas.py seed.py
backend/app/routers/: shelters.py sos.py routing.py dispatch.py auth.py
backend/app/services/: geo.py routing_provider.py crisis.py ws.py
frontend/citizen/, frontend/dispatcher/, frontend/shared/ (api.js i18n.js style.css)
tests/, docs/, README.md, AI_LOG.md

## API contract (prefix /api)
- GET  /shelters/nearest?lat=&lon=&district=&limit=  -> shelters with distance_m, occupancy_pct
- GET  /route?from_lat=&from_lon=&shelter_id=        -> {shelter, path:[[lat,lon]], rerouted, reason}
- POST /sos {lat, lon, hazard_type: fire|collapse|flood|medical, citizen_id} -> SOS
- POST /sos/{id}/safe                                -> marks citizen safe
- POST /roads/{id}/close, POST /roads/{id}/open      -> dispatcher only
- POST /shelters/{id}/occupancy {current}            -> simulator/dispatcher
- GET  /dispatch/overview                            -> sos list, shelters, brigades, alerts
- POST /dispatch/alerts/{id}/confirm                 -> dispatch brigade + open new shelter
- WS   /ws/dispatch                                  -> live events

## Domain rules
- Reroute citizen when a road on the path is closed OR the shelter is >= 90% full.
- Red Alert when >= 4 distinct SOS within 500 m (or same zone) in 5 minutes, OR a shelter > 95% full.
- Thresholds live in config.py, never hard-coded elsewhere.

## Design for change (jury will add surprise requirements)
- Roles: auth.py has a single `require_role(...)` dependency; role comes from X-Role header for now.
- Languages: all UI strings in frontend/shared/i18n.js dictionaries (az, en). No hard-coded UI text.
- External routing sits behind services/routing_provider.py with a local-graph fallback.
- Keep routers thin; logic goes in services/.

## MANDATORY after every task (do this without being asked)
1. Run `pytest -q` (if tests exist) and make sure the server starts.
2. Append an entry to AI_LOG.md: time (HH:MM), task id, what was asked, what AI generated/changed (files), how it was verified, human review status "pending".
3. `git add -A && git commit -m "<type>: <short summary>"`. One commit per task.
4. Do NOT run `git push`. The human reviews and pushes.
5. End your reply with a 5-line summary: files changed, how to verify, commit hash.

STEP 2: scaffold
- .gitignore (Python, .venv, crisis.db, .DS_Store), requirements.txt (fastapi, uvicorn[standard], sqlalchemy, pydantic, pytest, httpx, locust).
- Create .venv with python3.12 and install requirements.
- models.py: Zone, Shelter(id, name, type: shelter|park|stadium, lat, lon, capacity, current, zone_id, is_open), RoadNode, RoadEdge(id, from_node, to_node, length_m, is_closed), SOS(id, citizen_id, lat, lon, hazard_type, status: active|safe|resolved, zone_id, created_at), Brigade(id, name, status: available|dispatched, zone_id), Alert(id, kind, reason, zone_id, shelter_id, status: open|confirmed, created_at).
- config.py: thresholds (REROUTE_OCCUPANCY_PCT=90, ALERT_OCCUPANCY_PCT=95, SOS_CLUSTER_COUNT=4, SOS_CLUSTER_RADIUS_M=500, SOS_CLUSTER_WINDOW_MIN=5).
- seed.py: idempotent seed for Baku: 5 zones (Nasimi, Sabail, Yasamal, Narimanov, Khatai), 10 shelters with realistic coordinates and capacities, 6 brigades, a small road graph (about 25 nodes, 45 edges) connecting the zones. Seed runs on startup if DB is empty.
- All routers registered with stub endpoints matching the contract, returning 501 or empty lists, except GET /api/health -> {"status":"ok"} and GET /api/shelters (list all, working).
- frontend placeholders: citizen/index.html and dispatcher/index.html (title + link to each other), shared/api.js (fetch wrapper), shared/i18n.js (az/en dictionaries + t() helper), shared/style.css. Mount at / (citizen) and /dispatcher.
- AI_LOG.md with a header ("AI Usage Declaration: tools: Claude Code (Opus 5.5 / Fable 5.2), Claude project chat as architect/reviewer") and a table: Time | Task | Request | AI output | Verification | Human review.
- README.md with a short run section only.

CONSTRAINTS
- macOS/zsh. No Docker yet. No extra frameworks. Keep files small.

ACCEPTANCE
- `uvicorn backend.app.main:app` starts; `curl localhost:8000/api/health` returns ok.
- `curl localhost:8000/api/shelters` returns 10 seeded shelters.
- http://localhost:8000/ and /dispatcher load.
- AI_LOG.md has the T0 entry; one commit exists; nothing pushed."
Summary: Scaffolded the FastAPI + SQLite backend (models, config thresholds, idempotent Baku seed with 5 zones, 10 shelters, 6 brigades, 25-node/45-edge road graph), stub routers matching the API contract, static citizen/dispatcher placeholders with az/en i18n, CLAUDE.md, README and the AI log. Verified with `pytest -q` (7 passed), uvicorn start (also with --reload), curl of /api/health, /api/shelters (10), / and /dispatcher (200), the WebSocket hello, and a restart confirming the seed is idempotent.
Files changed: CLAUDE.md, README.md, AI_LOG.md, .gitignore, requirements.txt, pytest.ini, docs/.gitkeep, backend/__init__.py, backend/app/__init__.py, backend/app/main.py, backend/app/config.py, backend/app/db.py, backend/app/models.py, backend/app/schemas.py, backend/app/seed.py, backend/app/routers/__init__.py, backend/app/routers/shelters.py, backend/app/routers/routing.py, backend/app/routers/sos.py, backend/app/routers/dispatch.py, backend/app/routers/auth.py, backend/app/services/__init__.py, backend/app/services/geo.py, backend/app/services/routing_provider.py, backend/app/services/crisis.py, backend/app/services/ws.py, frontend/citizen/index.html, frontend/dispatcher/index.html, frontend/shared/api.js, frontend/shared/i18n.js, frontend/shared/style.css, tests/conftest.py, tests/test_smoke.py

2026-11-15 11:58
Tool: Claude Code
Prompt: "Use plan mode briefly, then implement. Follow CLAUDE.md (AI_LOG entry + one commit, no push).

GOAL
Task B1+B2: implement nearest shelters, SOS submission and "I am safe" status.

FILES
@backend/app/routers/shelters.py @backend/app/routers/sos.py @backend/app/services/geo.py
@backend/app/models.py @backend/app/schemas.py @backend/app/seed.py @backend/app/config.py @tests/

FIXES FIRST
1. Seed: move Baku Olympic Stadium to the Narimanov zone. Make sure the seed stays idempotent (delete crisis.db locally to reseed).
2. Time handling: add `utcnow()` helper in services/geo.py or a new services/clock.py that returns naive UTC datetime; use it for every created_at default and every time comparison, so SQLite naive datetimes never get compared with aware ones.
3. Pin dependencies: `pip freeze > requirements.txt`.

B1: GET /api/shelters/nearest?lat=&lon=&district=&limit=5
- geo.py: `haversine_m(lat1, lon1, lat2, lon2)` and `nearest_zone(lat, lon)`.
- Either lat+lon or district is required (422 otherwise). With district only, use the zone centre as origin and list that zone's shelters first.
- Only open shelters. Response items: id, name, type, lat, lon, capacity, current, occupancy_pct (1 decimal), distance_m (int), is_full (occupancy_pct >= REROUTE_OCCUPANCY_PCT from config), zone name. Sorted by distance.
- POST /api/shelters/{id}/occupancy {current}: dispatcher role, clamps to 0..capacity, returns the shelter.

B2: SOS
- POST /api/sos {lat, lon, hazard_type, citizen_id}: validate hazard_type in fire|collapse|flood|medical and lat/lon ranges with pydantic; assign zone_id via nearest_zone; status "active"; return 201 with the SOS.
- If the same citizen_id already has an active SOS, update that record (location, hazard_type, created_at) instead of creating a duplicate. This is what "distinct SOS" means for the alert rule later.
- POST /api/sos/{id}/safe: status -> "safe", 404 if missing.
- GET /api/sos?status=&zone_id=: list, newest first.
- Leave a clearly marked hook `on_sos_created(db, sos)` in services/crisis.py (no-op for now) and call it from the router; B4 will fill it.

CONSTRAINTS
- Routers stay thin, logic in services. Do not touch frontend/. Do not implement routing or alerts yet.

ACCEPTANCE (add pytest tests for each)
- nearest with lat/lon returns shelters sorted by distance with occupancy_pct and is_full.
- nearest with district=Narimanov includes the Olympic Stadium.
- missing params -> 422; invalid hazard_type -> 422.
- same citizen sending SOS twice -> one active record.
- /safe changes status; unknown id -> 404.
- occupancy endpoint returns 403 without X-Role: dispatcher.
- `pytest -q` green.

VERIFY
curl "localhost:8000/api/shelters/nearest?lat=40.3777&lon=49.8920&limit=3"
curl -X POST localhost:8000/api/sos -H 'Content-Type: application/json' -d '{"lat":40.3777,"lon":49.8920,"hazard_type":"fire","citizen_id":"c1"}'"
Summary: Moved Baku Olympic Stadium to Narimanov, added a naive-UTC clock helper used for all timestamps, and pinned dependencies. Implemented nearest shelters (lat/lon or district, open only, distance-sorted, occupancy_pct and is_full), dispatcher-only occupancy update with clamping, SOS submit with one active record per citizen (enforced by a partial unique index), mark-safe, an SOS list, and the no-op on_sos_created hook. Verified with `pytest -q` (22 passed) on a freshly reseeded DB and the task's curls (Khatai District Shelter first; a repeat SOS from c1 returns the same id).
Files changed: AI_LOG.md, requirements.txt, backend/app/main.py, backend/app/models.py, backend/app/schemas.py, backend/app/seed.py, backend/app/routers/shelters.py, backend/app/routers/sos.py, backend/app/services/clock.py, backend/app/services/geo.py, backend/app/services/crisis.py, backend/app/services/shelters.py, backend/app/services/sos.py, tests/test_shelters.py, tests/test_sos.py, tests/test_smoke.py

2026-11-15 12:00
Tool: Claude Code
Prompt: "Small housekeeping task. No plan mode needed.

GOAL
Switch the AI usage log to a new format that keeps every prompt verbatim.

STEPS
1. `git mv AI_LOG.md AI_DECLARATION.md`. Update every reference to AI_LOG.md (CLAUDE.md, README.md, anything else).
2. Rewrite AI_DECLARATION.md: keep a short header (project name, team: Xizri Saxrayev, Anar Hümmətli, Ülvi Mustafayev; tools used: Claude Code in VS Code with Opus 5.5 / Fable 5.2 as executor, Claude project chat as architect and reviewer; rule: every AI change is reviewed by a human before push). Then one entry per prompt, oldest first, in exactly this format, separated by a blank line:

2026-11-15 HH:MM
Tool: Claude Code
Prompt: "<the full prompt exactly as the user sent it, verbatim, not shortened or paraphrased>"
Summary: <2-3 sentences: what was built or changed and how it was verified>
Files changed: <comma-separated paths>

3. Backfill entries for every prompt already sent in this session (the scaffold prompt, the shelters+SOS prompt if done, and this one), with the full original prompt text from this conversation and the real times. Do not invent or shorten anything.
4. In CLAUDE.md, replace step 2 of "MANDATORY after every task" with:
   "2. Append an entry to AI_DECLARATION.md in the existing format: date and time (YYYY-MM-DD HH:MM, local time), Tool, Prompt (the user's full prompt verbatim, in quotes, never summarized), Summary, Files changed. One entry per user prompt, including small fix prompts."
5. Commit: "docs: switch AI log to verbatim-prompt AI_DECLARATION.md". No push.

ACCEPTANCE
- AI_LOG.md no longer exists; `grep -r "AI_LOG" . --exclude-dir=.venv --exclude-dir=.git` returns nothing.
- AI_DECLARATION.md contains the full text of each earlier prompt.
- `pytest -q` still green."
Summary: Renamed AI_LOG.md to AI_DECLARATION.md with git mv, rewrote it in the verbatim-prompt format with backfilled entries for all three prompts in this session, and updated CLAUDE.md (layout line and mandatory step 2). Verified that AI_LOG.md is gone, that the only remaining "AI_LOG" matches are inside the quoted verbatim prompts, and that `pytest -q` is still green.
Files changed: AI_LOG.md -> AI_DECLARATION.md, CLAUDE.md
