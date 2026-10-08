"""Job lifecycle rules, independent of processes and persistence."""

from ..errors import UserError

TERMINAL_STATES = frozenset({"completed", "failed", "cancelled"})
TRANSITIONS = {
    None: frozenset({"queued"}),
    "queued": frozenset({"running", "failed", "cancelled"}),
    "running": TERMINAL_STATES,
    "completed": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}


def transition(status, target, **details):
    current = status.get("state")
    if target not in TRANSITIONS.get(current, ()):
        raise UserError(f"Invalid job transition: {current} -> {target}")
    return {**status, **details, "state": target}
