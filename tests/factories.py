"""Small builders for planner tests: snapshots described in a few lines."""

from __future__ import annotations

from netbox_permissions_matrix_plugin.core.model import GROUP, USER, Perm, Principal, PrincipalRef, Snapshot

NOC = PrincipalRef(GROUP, 1)
OPS = PrincipalRef(GROUP, 2)
RO = PrincipalRef(GROUP, 3)
ALICE = PrincipalRef(USER, 10)
DAVE = PrincipalRef(USER, 11)

NAMES = {NOC: "NOC", OPS: "Ops", RO: "Read-only", ALICE: "alice", DAVE: "dave"}


def perm(pid, name, actions, object_types, *principals, enabled=True, constraints=None, description=""):
    return Perm(
        id=pid,
        name=name,
        description=description,
        enabled=enabled,
        actions=tuple(actions),
        object_types=frozenset(object_types),
        groups=frozenset(p.id for p in principals if p.kind == GROUP),
        users=frozenset(p.id for p in principals if p.kind == USER),
        constraints=constraints,
    )


def snapshot(*perms, memberships=None):
    return Snapshot(
        perms={p.id: p for p in perms},
        principals={ref: Principal(ref, name) for ref, name in NAMES.items()},
        memberships=memberships or {ALICE.id: frozenset({NOC.id})},
    )
