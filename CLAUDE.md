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
tests/, docs/, README.md, AI_DECLARATION.md

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
2. Append an entry to AI_DECLARATION.md in the existing format (## date time, Tool, Prompt condensed to key requirements, Summary in 1-2 sentences, Files changed). Keep entries short. One entry per task.
3. `git add -A && git commit -m "<type>: <short summary>"`. One commit per task.
4. Do NOT run `git push`. The human reviews and pushes.
5. End your reply with a 5-line summary: files changed, how to verify, commit hash.
