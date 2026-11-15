# Urban Crisis & Crowd Evacuation Engine
Hackathon prototype (deadline 15:00). Working MVP first, no over-engineering.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2 + SQLite (crisis.db), WebSocket
- Frontend: vanilla JS + Leaflet 1.9.4 vendored in frontend/vendor/leaflet (no CDN), no build step, served by FastAPI StaticFiles
- Tests: pytest (+ httpx TestClient), Locust for load tests
- Run: `source .venv/bin/activate && uvicorn backend.app.main:app --reload` (port 8000)
- Test: `pytest -q`

## Layout
backend/app/: main.py config.py db.py models.py schemas.py seed.py errors.py, data/road_geometry.json (committed)
backend/scripts/snap_roads.py (one-off, manual: python -m backend.scripts.snap_roads [--shelters-only])
backend/app/routers/: shelters.py sos.py routing.py dispatch.py demo.py auth.py
backend/app/services/: geo.py clock.py shelters.py sos.py routing_provider.py circuit_breaker.py roads.py evacuation.py
                       crisis.py dispatch.py demo.py ws.py rate_limit.py spam.py auth.py flood_gate.py
frontend/citizen/ (index.html citizen.js), frontend/dispatcher/ (index.html dispatcher.js),
frontend/shared/ (api.js i18n.js map.js style.css), frontend/vendor/leaflet/
tests/ (tests/helpers.STAFF = JWT headers filled by conftest; tests/load/flood_test.py standalone), docs/, README.md, AI_DECLARATION.md

## API contract (prefix /api)
Roles: citizen (default) / priority_citizen via X-Role header (no login). Staff = dispatcher / admin via
`Authorization: Bearer <jwt>` ONLY (X-Role: dispatcher -> 401; bad/expired token -> 401; wrong role -> 403).
"operator" / "dispatcher" below = staff JWT.
- POST /auth/login {username, password} -> {access_token, role, expires_in} (HS256, JWT_SECRET env, 8 h; 5/min per IP;
                                                         users dispatcher/admin seeded, PBKDF2, DISPATCHER_PASSWORD/ADMIN_PASSWORD env) Errors: {"detail": {"code", "message"}} (codes only, UI translates).
- GET  /health -> {status: ok, routing_mode} (always 200); GET /auth/me -> {role}; GET /shelters -> all shelters incl. closed reserves
                                                         (is_accessible, is_reserve, is_temporary)
- GET  /zones                                        -> [{id, name, center_lat, center_lon}]
- GET  /shelters/nearest?lat=&lon=&district=&limit=&accessible= -> open shelters with distance_m, occupancy_pct, is_full,
                                                         zone, is_accessible (accessible forced for priority_citizen)
- POST /shelters/{id}/occupancy {current}            -> operator; clamps 0..capacity
- GET  /route?from_lat=&from_lon=&shelter_id=&accessible= -> {shelter|null, path:[[lat,lon]], distance_m, eta_min,
                                                         rerouted, reason: shelter_full|road_closed|all_shelters_full|
                                                         shelter_not_accessible|no_accessible_route, original_shelter_id,
                                                         provider: external|local-graph|route-cache|static-matrix, edge_ids,
                                                         accessible, needs_medical_transport, degraded, mode: online|fallback,
                                                         notice_code: offline_backup_routing|null, approach, approach_m}
                                                         path = street geometry first road node -> shelter entrance;
                                                         approach = straight citizen -> first node (draw dashed);
                                                         distance_m/eta_min include approach
- GET  /roads                                        -> edges with from/to coordinates, is_closed, is_accessible, geometry
- POST /roads/{id}/close, POST /roads/{id}/open      -> operator
- GET  /routing/status                               -> {mode, external_mode: up|down_503|slow, external_up,
                                                         breaker: {state: closed|open|half_open, consecutive_failures,
                                                         seconds_until_retry, last_error}, active_provider, cache_size}
                                                         (same object in /dispatch/overview.routing; WS routing_status on change)
- POST /routing/external/{up|down|slow}              -> operator; simulates the external API (down = HTTP 503, slow = >5 s)
- POST /sos {lat, lon, hazard_type: fire|collapse|flood|medical, citizen_id} -> 201 SOS (one active per citizen;
                                                         priority from role, never from body). Flood protection:
                                                         20/min per IP (ASGI gate + route), 3/min per citizen -> 429
                                                         rate_limited + Retry-After; same payload+IP+role within 10 s or
                                                         same Idempotency-Key header -> 200 existing SOS; > 5 citizen ids
                                                         per IP per 60 s -> stored suspected_spam (not for priority)
- GET  /sos?status=&zone_id=&priority=&include_spam= -> SOS list (suspected_spam excluded by default), priority asc then newest first;
                                                         items have priority, priority_label (critical|normal), is_priority_citizen
- POST /sos/{id}/safe                                -> marks citizen safe
- GET  /dispatch/overview                            -> dispatcher; cached 1 s; {sos (active, non-spam, priority first,
                                                         max 100), sos_total, sos_priority_total,
                                                         spam_blocked: {rate_limited, duplicates, suspected}, shelters, brigades,
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
- WS   /ws/dispatch?token=<jwt>                       -> staff only (closed 4401 otherwise); {type, data}; queued and
                                                         coalesced to <= 5 msg/s: several events -> {type: "batch",
                                                         data: [{type, data}, ...]}; types: hello, sos_created, sos_updated, shelter_updated,
                                                         road_updated, alert_created, alert_updated, alert_confirmed,
                                                         brigade_updated, routing_status, demo_reset

## Domain rules
- Reroute citizen when a road on the path is closed OR the shelter is >= 90% full.
- Red Alert (services/crisis.py, pure rule functions + DB wrappers):
  sos_cluster: active SOS from the last 5 min that are in the new SOS's zone OR within 500 m of it, >= 4 distinct
  citizens -> one open alert per zone (later SOS grow it; no re-alert while a confirmed one is younger than the window).
  shelter_overflow: occupancy_pct > 95 when crossing upward -> one open alert per shelter.
- Live events: routers call services.ws.publish(type, data) after commit; it never raises or blocks (queue drained
  by a lifespan task); any event except sos_created invalidates the overview cache.
- Flood (Drop 3): suspected_spam SOS never count for Red Alerts, never publish live events, are hidden from the
  feed/KPIs/map. Cluster query is SQL (window + not spam + same zone OR bbox) on indexes (status, created_at),
  (zone_id, created_at). Limiter/spam/idempotency state is in memory (single process); demo reset clears it.
  Tests: conftest lifts SOS limits / spam rule / overview TTL; flood tests restore them (DROP3_DEFAULTS).
- External routing outage (Drop 2): every external call runs with a hard timeout (EXTERNAL_TIMEOUT_S=5) behind a
  circuit breaker (BREAKER_FAILURE_THRESHOLD=2 consecutive 503/timeouts -> open; BREAKER_COOLDOWN_S=30 -> half_open,
  one trial call). Fallback chain: local-graph (SQLite Dijkstra) -> route-cache (last good route per origin node +
  shelter + accessible; rejected if a road on it is closed) -> static-matrix (DistanceMatrix zone->shelter, built at
  startup; haversine x STATIC_MATRIX_DETOUR_FACTOR if unknown). Priority citizens never get static-matrix.
  Any non-external answer is degraded=true and the citizen UI shows notice.offline_backup_routing.
  The map works offline: vendored Leaflet + roads drawn as vectors when OSM tiles fail (shared/map.js).
- Priority citizens (auth.PRIORITY_ROLES): SOS priority 1 (critical), a repeat SOS never downgrades it.
  Routes are accessible-only (accessible edges + accessible shelters), never straight-line; if nothing is reachable
  return reason "no_accessible_route" with needs_medical_transport=true. Other roles may opt in with ?accessible=true.
- Street geometry (P1): data/road_geometry.json was generated once from OSM (routing.openstreetmap.de foot profile,
  (c) OpenStreetMap contributors) - never called at runtime. Seed loads snapped node coords, edge geometry + real
  length_m, and per shelter 3 access paths (from its 3 nearest nodes); routing picks the cheapest street walk + access.
  Roads whose real walk > MAX_EDGE_DETOUR_RATIO (2.5) x straight are dropped (Sabail C-W); a node left without an
  accessible road gets its shortest road re-linked as accessible (Sabail S-W). All providers incl. fallbacks return
  street geometry; static-matrix stays a straight line.
- Thresholds live in config.py, never hard-coded elsewhere.

## Design for change (jury will add surprise requirements)
- Roles: routers/auth.py has a single `require_role(...)` (JWT) dependency + `require_staff`; citizens via X-Role.
- Languages: all UI strings in frontend/shared/i18n.js dictionaries (az, en). No hard-coded UI text.
  HTML uses data-i18n / data-i18n-placeholder / data-i18n-aria; JS uses t(key, params) and re-renders on the
  "langchange" event. Frontend calls go through api(path, {method, body, role}) (shared/api.js), which throws ApiError{code};
  the dispatcher page logs in (token in sessionStorage, sent as Bearer by api() and as ?token= by apiSocket()),
  401 -> back to the login form; it never touches the citizen's saved role.
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
