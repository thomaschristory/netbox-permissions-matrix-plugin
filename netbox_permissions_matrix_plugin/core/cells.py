"""What a matrix cell shows, worked out from the permissions that cover it."""

from __future__ import annotations

import enum
from collections.abc import Iterable

from .model import GROUP, Perm, PrincipalRef, Snapshot


class CellState(enum.StrEnum):
    NONE = "none"
    GRANTED = "granted"
    CONSTRAINED = "constrained"
    DISABLED = "disabled"


def covering(snap: Snapshot, ref: PrincipalRef, object_type: str, action: str) -> list[Perm]:
    """Permissions assigned directly to the principal that list the object type and the action, by ID."""
    return [snap.perms[pid] for pid in snap.covering_ids(ref, object_type, action)]


def state_of(perms: Iterable[Perm]) -> CellState:
    perms = list(perms)
    if any(p.enabled and not p.constrained for p in perms):
        return CellState.GRANTED
    if any(p.enabled for p in perms):
        return CellState.CONSTRAINED
    if perms:
        return CellState.DISABLED
    return CellState.NONE


def cell_state(snap: Snapshot, ref: PrincipalRef, object_type: str, action: str) -> CellState:
    """The cell's state from the principal's own permissions. For a user, group grants do not count."""
    return state_of(covering(snap, ref, object_type, action))


def inherited_state(snap: Snapshot, user_id: int, object_type: str, action: str) -> tuple[CellState, list[str]]:
    """What a user gets on this cell through group membership, and from which groups (by name)."""
    perms, names = [], []
    for group_id in sorted(snap.memberships.get(user_id, ())):
        ref = PrincipalRef(GROUP, group_id)
        found = covering(snap, ref, object_type, action)
        if found:
            perms += found
            names.append(snap.name_of(ref))
    return state_of(perms), sorted(names)
