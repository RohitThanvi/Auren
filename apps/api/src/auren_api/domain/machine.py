"""Machine lifecycle states and the allowed transitions between them."""

from enum import StrEnum

from auren_api.domain.errors import ConflictViolationError


class MachineStatus(StrEnum):
    REGISTERED = "registered"
    LISTED = "listed"
    PAUSED = "paused"
    WITHDRAWN = "withdrawn"


_ALLOWED: dict[MachineStatus, frozenset[MachineStatus]] = {
    MachineStatus.REGISTERED: frozenset({MachineStatus.LISTED, MachineStatus.WITHDRAWN}),
    MachineStatus.LISTED: frozenset(
        {MachineStatus.LISTED, MachineStatus.PAUSED, MachineStatus.WITHDRAWN}
    ),
    MachineStatus.PAUSED: frozenset({MachineStatus.LISTED, MachineStatus.WITHDRAWN}),
    MachineStatus.WITHDRAWN: frozenset(),
}


def require_transition(current: MachineStatus, target: MachineStatus) -> None:
    if target not in _ALLOWED[current]:
        raise ConflictViolationError(
            "invalid_state_transition", f"A {current.value} machine cannot become {target.value}."
        )
