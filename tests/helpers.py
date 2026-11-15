"""Shared test headers. STAFF is filled once per session by conftest's `auth_headers` fixture (real login)."""
STAFF: dict[str, str] = {}
