"""Language-neutral errors: the API returns a machine code plus an English fallback message.

The UI translates by `code`; `message` is only for logs/debugging.
"""
from fastapi import HTTPException


def api_error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})
