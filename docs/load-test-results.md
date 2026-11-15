# Load test: SOS flood (Challenge Drop 3)

Real output, 2026-11-15 14:11 local, MacBook (Apple Silicon), one uvicorn worker, SQLite, fresh DB.

## Command

```bash
rm -f crisis.db crisis.db-shm crisis.db-wal
source .venv/bin/activate
uvicorn backend.app.main:app --port 8000 --log-level warning &   # no --reload
python tests/load/flood_test.py --base http://127.0.0.1:8000 --n 600
```

Scenario: 5 warm-up SOS, then 600 fake SOS from 600 random citizen ids (every 12th is a replay of a warm-up
payload), fired at the same instant from 6 client processes on one IP. Meanwhile a logged-in dispatcher (JWT)
polls `/api/dispatch/overview` every 100 ms, triggers one legitimate demo burst (4 citizens) and confirms the
Red Alert it raises.

## Result (final)

```
Flood: 600 fake SOS (+5 warm-up) from 6 client processes on one IP, all fired at once; flood phase 0.28 s
SOS status codes: {200: 40, 201: 15, 429: 545}  connection errors: 0
  accepted (201): 15  of which suspected_spam: 15
  rate limited (429): 545  duplicates (200): 40
Server counters (overview.spam_blocked): {'rate_limited': 545, 'duplicates': 40, 'suspected': 15}
Dispatcher overview polls: 3  codes: {200: 3}  sos_total shown: 9
Legit burst: HTTP 200, alerts raised: 1  (54.7 ms)
Confirm alert: HTTP 200 (4.2 ms)
Cluster alerts after flood: 1 (fake SOS raised none: True)
POST /api/sos          n= 600  mean=  116.8 ms  p95=  212.1 ms  max=  278.5 ms
GET overview           n=   3  mean=   10.5 ms  p95=   25.8 ms  max=   25.8 ms
ALL requests           n= 605  mean=  116.0 ms  p95=  211.1 ms  max=  278.5 ms
Mean < 300 ms: YES (116.0 ms)
```

- 20 SOS were accepted from the flooding IP (`SOS_RATE_PER_IP` = 20/min): the 5 warm-ups plus 15 fakes. After the
  5th distinct citizen id, all 15 fakes were stored as `suspected_spam`. None of them reached the dispatcher feed,
  the KPIs or the map, and none raised a Red Alert.
- The rest got 429 with Retry-After, or 200 with the existing SOS when the payload was a duplicate.
- The legitimate burst still raised exactly one Red Alert, and the dispatcher confirmed it during the flood.

## How we got there (earlier runs, same scenario)

| Run | Change | Mean | p95 |
|---|---|---|---|
| 1 | first version: sync route, rate limit inside the route | 1791 ms | 3917 ms |
| 2 | flood checks moved onto the event loop (async route and deps), DB work only for accepted SOS, cached overview served without the thread pool | 722 ms | 1394 ms |
| 3 | plus a raw ASGI gate: an IP over its limit gets 429 before routing and parsing | 733 ms | 1443 ms |
| 4 | same server, flood fired from 6 client processes instead of 1 | **116 ms** | **211 ms** |

Cause of run 1: every rejected request went through the 40-thread pool (a sync route plus sync
dependencies), so 600 requests queued behind each other. Runs 2 and 3 were limited by the client. One Python
httpx client needed about 0.8 s just to issue 600 concurrent requests, while the server answers in about 0.5 ms
each (measured sequentially over keep-alive). With all requests sent at once, the mean latency is about half the
time it takes to send them all, so a single client was measuring itself. Run 4 removes that client bottleneck.
