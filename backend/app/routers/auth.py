"""Role handling. Single extension point: require_role(...). Role comes from X-Role header for now."""
from fastapi import APIRouter, Header, HTTPException

ROLES = {"citizen", "dispatcher", "simulator"}

router = APIRouter(tags=["auth"])


def require_role(*allowed: str):
    def dep(x_role: str | None = Header(default=None)) -> str:
        if x_role not in allowed:
            raise HTTPException(status_code=403, detail=f"Requires role: {', '.join(allowed)}")
        return x_role

    return dep


@router.get("/auth/me")
def me(x_role: str | None = Header(default=None)):
    return {"role": x_role if x_role in ROLES else "citizen"}
