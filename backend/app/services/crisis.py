"""Crisis domain logic (rerouting decisions, Red Alert detection). Thresholds come from config.py.

Use services.clock.utcnow() for any time-window comparison (naive UTC).
"""


# ---------------------------------------------------------------------------
# HOOK: called by routers/sos.py after every SOS create/refresh.
# B4 fills this: evaluate SOS clustering -> raise Red Alert -> broadcast on WS.
# ---------------------------------------------------------------------------
def on_sos_created(db, sos) -> None:
    return None


def needs_reroute(db, shelter, path_edge_ids) -> tuple[bool, str | None]:
    raise NotImplementedError


def evaluate_alerts(db) -> list:
    raise NotImplementedError
