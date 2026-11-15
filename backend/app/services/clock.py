"""Single source of 'now'. Naive UTC everywhere, because SQLite drops tzinfo on read.

Use clock.utcnow() for every created_at default and every time-window comparison.
"""
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)
