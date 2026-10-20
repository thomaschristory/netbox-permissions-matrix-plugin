"""Plain data describing NetBox permissions and the changes asked of them."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

GROUP = "group"
USER = "user"
PrincipalKind = Literal["group", "user"]

# What a group or user the viewer may not view is called instead of its name.
HIDDEN_GROUP = "a group you cannot view"
HIDDEN_USER = "a user you cannot view"


class _Unset:
    def __repr__(self):
        return "UNSET"

    def __bool__(self):
        return False


# Marks a PermEdit field that was not given, as opposed to one given as None (constraints: remove them).
UNSET: Any = _Unset()


@dataclass(frozen=True, order=True)
class PrincipalRef:
    """A group or a user, by NetBox ID."""

    kind: PrincipalKind
    id: int

    @property
    def key(self) -> str:
        return f"{self.kind}:{self.id}"

    @classmethod
    def parse(cls, key: str) -> PrincipalRef:
        kind, _, pk = key.partition(":")
        if kind not in (GROUP, USER) or not pk.isdigit():
            raise ValueError(f"not a principal key: {key!r}")
        return cls(kind, int(pk))  # type: ignore[arg-type]


@dataclass(frozen=True)
class Principal:
    ref: PrincipalRef
    name: str
    hidden: bool = False  # the viewer may not view it: name is HIDDEN_GROUP or HIDDEN_USER


def is_constrained(constraints) -> bool:
    """NetBox treats null, {} and [] as "no constraints": the permission matches every object."""
    if not constraints:
        return False
    if isinstance(constraints, list):
        # A list is OR-ed; one empty set in it matches everything.
        return all(bool(c) for c in constraints)
    return True


@dataclass(frozen=True)
class Perm:
    """One NetBox ObjectPermission. object_types are "app_label.model" strings."""

    id: int | None
    name: str
    description: str = ""
    enabled: bool = True
    actions: tuple[str, ...] = ()
    object_types: frozenset[str] = frozenset()
    groups: frozenset[int] = frozenset()
    users: frozenset[int] = frozenset()
    constraints: Any = None

    def principals(self) -> frozenset[PrincipalRef]:
        return frozenset({PrincipalRef(GROUP, g) for g in self.groups} | {PrincipalRef(USER, u) for u in self.users})

    def assigned_to(self, ref: PrincipalRef) -> bool:
        return ref.id in (self.groups if ref.kind == GROUP else self.users)

    @property
    def constrained(self) -> bool:
        return is_constrained(self.constraints)

    def covers(self, ref: PrincipalRef, object_type: str, action: str) -> bool:
        return self.assigned_to(ref) and object_type in self.object_types and action in self.actions

    def is_simple_for(self, ref: PrincipalRef, action: str) -> bool:
        """One principal, one action, no constraints: the only kind of permission the plugin grows."""
        return self.principals() == {ref} and self.actions == (action,) and not self.constrained

    def is_simple(self, ref: PrincipalRef) -> bool:
        """One principal, no constraints, enabled: a permission the plugin may grow or shrink, whatever its actions."""
        return self.principals() == {ref} and self.enabled and not self.constrained


@dataclass
class Snapshot:
    perms: dict[int, Perm]
    principals: dict[PrincipalRef, Principal]
    # user ID -> IDs of the groups the user belongs to
    memberships: dict[int, frozenset[int]] = field(default_factory=dict)
    _index: dict | None = field(default=None, init=False, repr=False, compare=False)

    def covering_ids(self, ref: PrincipalRef, object_type: str, action: str) -> list[int]:
        """IDs of the permissions covering a cell, from an index built on first use (snapshots are not mutated)."""
        if self._index is None:
            index: dict[tuple, list[int]] = {}
            for pid in sorted(self.perms):
                p = self.perms[pid]
                for principal in p.principals():
                    for ot in p.object_types:
                        for a in p.actions:
                            index.setdefault((principal, ot, a), []).append(pid)
            self._index = index
        return self._index.get((ref, object_type, action), [])

    def name_of(self, ref: PrincipalRef) -> str:
        principal = self.principals.get(ref)
        return principal.name if principal else ref.key

    def is_hidden(self, ref: PrincipalRef) -> bool:
        principal = self.principals.get(ref)
        return principal is not None and principal.hidden

    def hiding(self, visible: set[PrincipalRef]) -> Snapshot:
        """A copy for one viewer: the groups and users outside visible keep their permissions but not their names."""
        principals = {
            ref: p
            if ref in visible
            else Principal(ref, HIDDEN_GROUP if ref.kind == GROUP else HIDDEN_USER, hidden=True)
            for ref, p in self.principals.items()
        }
        return Snapshot(self.perms, principals, self.memberships)


@dataclass(frozen=True)
class CellChange:
    principal: PrincipalRef
    object_type: str
    action: str
    granted: bool


@dataclass(frozen=True)
class PermEdit:
    """A gear-panel edit of a principal's simple permission for one action, or of one of its permissions by ID."""

    principal: PrincipalRef
    action: str = ""
    perm_id: int | None = None
    name: Any = UNSET
    description: Any = UNSET
    enabled: Any = UNSET
    constraints: Any = UNSET
    add_actions: tuple[str, ...] = ()
    add_groups: tuple[int, ...] = ()
    add_users: tuple[int, ...] = ()


@dataclass(frozen=True)
class Operation:
    """One write. key is the permission ID as a string, or "new-N" for a permission the plan creates."""

    op: Literal["create", "update", "delete"]
    key: str
    before: Perm | None
    after: Perm | None
    affects: frozenset[PrincipalRef]
    reasons: tuple[str, ...] = ()

    @property
    def perm_id(self) -> int | None:
        return self.before.id if self.before else None


@dataclass
class Plan:
    operations: list[Operation]
    warnings: list[str]

    @property
    def empty(self) -> bool:
        return not self.operations
