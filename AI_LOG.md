# AI Usage Declaration

Tools: Claude Code (Opus 5.5 / Fable 5.2), Claude project chat as architect/reviewer.

| Time | Task | Request | AI output | Verification | Human review |
|------|------|---------|-----------|--------------|--------------|
| 11:46 | T0 | Scaffold project: FastAPI + SQLite skeleton, stub endpoints per API contract, Baku seed data, static frontend placeholders, CLAUDE.md, AI_LOG.md | CLAUDE.md, README.md, .gitignore, requirements.txt, pytest.ini; backend/app/{main,config,db,models,schemas,seed}.py; routers/{shelters,routing,sos,dispatch,auth}.py; services/{geo,routing_provider,crisis,ws}.py; frontend/{citizen,dispatcher}/index.html, frontend/shared/{api.js,i18n.js,style.css}; tests/{conftest,test_smoke}.py | `pytest -q` 7 passed; uvicorn started; curl /api/health ok, /api/shelters = 10, / and /dispatcher 200, WS /api/ws/dispatch hello; restart keeps 10 shelters (idempotent seed) | pending |
