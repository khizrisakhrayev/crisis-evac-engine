"""Role handling. Single extension point: ROLES + require_role(...). Role comes from X-Role header for now.

Adding a role = one line in ROLES (plus PRIORITY_ROLES if it needs critical SOS / accessible-only routes).
"""
from fastapi import APIRouter, Header

from ..errors import api_error

ROLES = {"citizen", "priority_citizen", "dispatcher", "simulator"}
DEFAULT_ROLE = "citizen"
# Mobility-impaired / special-care citizens: SOS gets critical priority, routes are accessible-only.
PRIORITY_ROLES = {"priority_citizen"}

router = APIRouter(tags=["auth"])


def current_role(x_role: str | None = Header(default=None)) -> str:
    """Role from X-Role header; unknown or missing -> DEFAULT_ROLE."""
    return x_role if x_role in ROLES else DEFAULT_ROLE


def require_role(*allowed: str):
    def dep(x_role: str | None = Header(default=None)) -> str:
        if x_role not in allowed:
            raise api_error(403, "forbidden_role", f"Requires role: {', '.join(allowed)}")
        return x_role

    return dep


@router.get("/auth/me")
def me(x_role: str | None = Header(default=None)):
    return {"role": current_role(x_role)}
