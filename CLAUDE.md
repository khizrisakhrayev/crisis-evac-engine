# Urban Crisis & Crowd Evacuation Engine
Hackathon prototype (deadline 15:00). Working MVP first, no over-engineering.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 + SQLite (crisis.db), WebSocket
- Frontend: vanilla JS + Leaflet (CDN), no build step, served by FastAPI StaticFiles
- Tests: pytest (+ httpx TestClient), Locust for load tests
- Run: `source .venv/bin/activate && uvicorn backend.app.main:app --reload` (port 8000)
- Test: `pytest -q`

## Layout
backend/app/: main.py config.py db.py models.py schemas.py seed.py errors.py
backend/app/routers/: shelters.py sos.py routing.py dispatch.py demo.py auth.py
backend/app/services/: geo.py clock.py shelters.py sos.py routing_provider.py roads.py evacuation.py crisis.py
                       dispatch.py demo.py ws.py
frontend/citizen/ (index.html citizen.js), frontend/dispatcher/, frontend/shared/ (api.js i18n.js style.css)
tests/, docs/, README.md, AI_DECLARATION.md

## API contract (prefix /api)
Roles via X-Role header (auth.ROLES): citizen (default), priority_citizen, dispatcher, simulator.
"operator" below = dispatcher or simulator. Errors: {"detail": {"code", "message"}} (codes only, UI translates).
- GET  /health, GET /auth/me, GET /shelters          -> ok; {role}; all shelters incl. closed reserves
                                                         (is_accessible, is_reserve, is_temporary)
- GET  /zones                                        -> [{id, name, center_lat, center_lon}]
- GET  /shelters/nearest?lat=&lon=&district=&limit=&accessible= -> open shelters with distance_m, occupancy_pct, is_full,
                                                         zone, is_accessible (accessible forced for priority_citizen)
- POST /shelters/{id}/occupancy {current}            -> operator; clamps 0..capacity
- GET  /route?from_lat=&from_lon=&shelter_id=&accessible= -> {shelter|null, path:[[lat,lon]], distance_m, eta_min,
                                                         rerouted, reason: shelter_full|road_closed|all_shelters_full|
                                                         shelter_not_accessible|no_accessible_route, original_shelter_id,
                                                         provider, edge_ids, accessible, needs_medical_transport}
- GET  /roads                                        -> edges with from/to coordinates, is_closed, is_accessible
- POST /roads/{id}/close, POST /roads/{id}/open      -> operator
- GET  /routing/status                               -> {external_up, active_provider}
- POST /routing/external/{up|down}                   -> operator; simulates external routing API outage
- POST /sos {lat, lon, hazard_type: fire|collapse|flood|medical, citizen_id} -> 201 SOS (one active per citizen;
                                                         priority from role, never from body)
- GET  /sos?status=&zone_id=&priority=               -> SOS list, priority asc then newest first;
                                                         items have priority, priority_label (critical|normal), is_priority_citizen
- POST /sos/{id}/safe                                -> marks citizen safe
- GET  /dispatch/overview                            -> dispatcher; {sos (active, priority first), shelters, brigades,
                                                         alerts (open first, then last 20 confirmed),
                                                         zones:[{id,name,active_sos,priority_sos}], routing}
- GET  /dispatch/alerts?status=open|confirmed         -> dispatcher; Alert: {id, kind: sos_cluster|shelter_overflow,
                                                         severity: red, zone_id, shelter_id, lat, lon, sos_count, sos_ids,
                                                         has_priority_sos, status: open|confirmed, action_code,
                                                         created_at, confirmed_at, brigade_id, new_shelter_id, brigade_shortage}
- POST /dispatch/alerts/{id}/confirm                 -> dispatcher; one transaction: nearest available brigade dispatched,
                                                         nearest closed reserve opened (else temporary assembly_point at
                                                         zone centre); returns {alert, brigade|null, shelter}; 409 if twice
- POST /dispatch/brigades/{id}/release               -> dispatcher; brigade back to available
- POST /demo/sos-burst {lat, lon, count=4, hazard_type} -> operator; distinct citizens within 240 m (fires an alert)
- POST /demo/reset                                   -> operator; clear SOS/alerts, free brigades, close reserves, reset roads
- WS   /ws/dispatch                                  -> {type, data}; types: hello, sos_created, sos_updated, shelter_updated,
                                                         road_updated, alert_created, alert_updated, alert_confirmed,
                                                         brigade_updated, routing_status, demo_reset

## Domain rules
- Reroute citizen when a road on the path is closed OR the shelter is >= 90% full.
- Red Alert (services/crisis.py, pure rule functions + DB wrappers):
  sos_cluster: active SOS from the last 5 min that are in the new SOS's zone OR within 500 m of it, >= 4 distinct
  citizens -> one open alert per zone (later SOS grow it; no re-alert while a confirmed one is younger than the window).
  shelter_overflow: occupancy_pct > 95 when crossing upward -> one open alert per shelter.
- Live events: routers call services.ws.publish(type, data) after commit; it never raises.
- Priority citizens (auth.PRIORITY_ROLES): SOS priority 1 (critical), a repeat SOS never downgrades it.
  Routes are accessible-only (accessible edges + accessible shelters), never straight-line; if nothing is reachable
  return reason "no_accessible_route" with needs_medical_transport=true. Other roles may opt in with ?accessible=true.
- Thresholds live in config.py, never hard-coded elsewhere.

## Design for change (jury will add surprise requirements)
- Roles: auth.py has a single `require_role(...)` dependency; role comes from X-Role header for now.
- Languages: all UI strings in frontend/shared/i18n.js dictionaries (az, en). No hard-coded UI text.
  HTML uses data-i18n / data-i18n-placeholder / data-i18n-aria; JS uses t(key, params) and re-renders on the
  "langchange" event. Frontend calls go through api(path, {method, body}) (shared/api.js), which throws ApiError{code}.
  The API returns codes only (status, hazard_type, priority_label, reason, type, error code); raise errors with
  errors.api_error(status, code, message). Names of shelters/zones/brigades are data, not translated.
- External routing sits behind services/routing_provider.py with a local-graph fallback.
- Keep routers thin; logic goes in services/.

## MANDATORY after every task (do this without being asked)
1. Run `pytest -q` (if tests exist) and make sure the server starts.
2. Append an entry to AI_DECLARATION.md in the existing format (## date time, Tool, Prompt condensed to key requirements, Summary in 1-2 sentences, Files changed). Keep entries short. One entry per task.
3. `git add -A && git commit -m "<type>: <short summary>"`. One commit per task.
4. Do NOT run `git push`. The human reviews and pushes.
5. End your reply with a 5-line summary: files changed, how to verify, commit hash.
