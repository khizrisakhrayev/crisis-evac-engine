# Urban Crisis & Crowd Evacuation Engine

## Run
```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn backend.app.main:app --reload   # http://localhost:8000
```
- Citizen view: http://localhost:8000/
- Dispatcher view: http://localhost:8000/dispatcher
- API docs: http://localhost:8000/docs
- Tests: `pytest -q`

The SQLite DB (`crisis.db`) is created and seeded with Baku data on first start. Delete it to reseed.

## Dispatcher login (JWT)
The dispatcher page asks for a login. Demo accounts (change them via env before any real use):

| user | password (default) | env override |
|---|---|---|
| `dispatcher` | `dispatcher123` | `DISPATCHER_PASSWORD` |
| `admin` | `admin123` | `ADMIN_PASSWORD` |

Tokens are HS256 JWTs valid for 8 h, signed with `JWT_SECRET`. If it is unset, a random secret is generated
at each start, so a restart logs everyone out. Every dispatcher or simulator API call needs
`Authorization: Bearer <token>`, and the WebSocket needs `?token=`.

```bash
TOKEN=$(curl -s -X POST localhost:8000/api/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"dispatcher","password":"dispatcher123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl -s localhost:8000/api/dispatch/overview -H "Authorization: Bearer $TOKEN" | head -c 200
```

## SOS flood protection (Challenge Drop 3)
- Limits: 20 SOS per minute per IP and 3 per minute per citizen. Over the limit you get 429 with Retry-After.
- An identical payload within 10 s, or a repeated `Idempotency-Key`, returns the existing SOS.
- More than 5 citizen ids from one IP within 60 s marks further SOS as `suspected_spam`. These never raise a Red
  Alert and stay out of the dispatcher's feed, KPIs and map.
- Load test with 600 concurrent fake SOS: see [docs/load-test-results.md](docs/load-test-results.md).
