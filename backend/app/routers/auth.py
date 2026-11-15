"""Roles and authentication. Single extension point: ROLES + require_role(...).

Citizens identify via the X-Role header (citizen | priority_citizen) - no login.
Staff (dispatcher | admin) must send `Authorization: Bearer <jwt>` from POST /api/auth/login;
`X-Role: dispatcher` is ignored (401 on staff endpoints).
"""
from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .. import config
from ..db import get_db
from ..errors import api_error
from ..services import auth as auth_svc
from ..services.rate_limit import limiter

CITIZEN_ROLES = {"citizen", "priority_citizen"}     # accepted from X-Role
STAFF_ROLES = {"dispatcher", "admin"}               # JWT only
ROLES = CITIZEN_ROLES | STAFF_ROLES
DEFAULT_ROLE = "citizen"
# Mobility-impaired / special-care citizens: SOS gets critical priority, routes are accessible-only.
PRIORITY_ROLES = {"priority_citizen"}

router = APIRouter(tags=["auth"])


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def role_from_header(x_role: str | None) -> str:
    """Citizen role from X-Role header; unknown, missing or staff -> DEFAULT_ROLE."""
    return x_role if x_role in CITIZEN_ROLES else DEFAULT_ROLE


async def current_role(x_role: str | None = Header(default=None)) -> str:
    # async: runs on the event loop (no threadpool hop) - matters under an SOS flood
    return role_from_header(x_role)


def bearer_claims(authorization: str | None) -> dict | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return auth_svc.decode_token(authorization[7:].strip())


def require_role(*allowed: str):
    """Staff endpoints: valid Bearer JWT required (401), with one of `allowed` roles (403)."""
    async def dep(authorization: str | None = Header(default=None)) -> dict:  # event loop, no threadpool hop
        claims = bearer_claims(authorization)
        if claims is None:
            raise api_error(401, "auth_required", "Valid Bearer token required")
        if claims.get("role") not in allowed:
            raise api_error(403, "forbidden_role", f"Requires role: {', '.join(allowed)}")
        return claims

    return dep


require_staff = require_role(*sorted(STAFF_ROLES))


class LoginIn(BaseModel):
    username: str
    password: str


@router.post("/auth/login")
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    ok, retry = limiter.hit(f"login:{client_ip(request)}", config.LOGIN_RATE_PER_IP, config.RATE_WINDOW_S)
    if not ok:
        return JSONResponse(status_code=429, headers={"Retry-After": str(retry)}, content={"detail": {
            "code": "rate_limited", "message": "Too many login attempts", "retry_after": retry}})
    user = auth_svc.authenticate(db, body.username, body.password)
    if user is None:
        raise api_error(401, "invalid_credentials", "Invalid username or password")
    return {"access_token": auth_svc.create_token(user.username, user.role), "token_type": "bearer",
            "role": user.role, "expires_in": config.JWT_EXPIRES_S}


@router.get("/auth/me")
def me(x_role: str | None = Header(default=None), authorization: str | None = Header(default=None)):
    claims = bearer_claims(authorization)
    if claims:
        return {"role": claims["role"], "username": claims.get("sub")}
    return {"role": role_from_header(x_role)}
