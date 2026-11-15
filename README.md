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
