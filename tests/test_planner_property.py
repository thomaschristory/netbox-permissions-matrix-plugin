"""Random snapshots and change sets: nobody untouched loses or gains anything, every changed cell ends as asked."""

from __future__ import annotations

import json
import random

import pytest

from netbox_permissions_matrix_plugin.core.cells import CellState, cell_state
from netbox_permissions_matrix_plugin.core.model import CellChange, Perm, Snapshot
from netbox_permissions_matrix_plugin.core.planner import plan

from .factories import ALICE, DAVE, NOC, OPS, RO, perm, snapshot

PRINCIPALS = [NOC, OPS, RO, ALICE, DAVE]
TYPES = ["dcim.device", "dcim.site", "dcim.rack", "ipam.prefix", "core.objecttype"]
ACTIONS = ["view", "add", "change", "delete", "sync"]
CONSTRAINTS = [None, None, None, {"site__slug": "paris"}, [{"status": "active"}, {"tenant": "$user"}]]


def random_snapshot(rng: random.Random) -> Snapshot:
    perms = []
    for pid in range(1, rng.randint(0, 7) + 1):
        perms.append(
            perm(
                pid,
                f"p{pid}",
                rng.sample(ACTIONS, rng.randint(1, 3)),
                rng.sample(TYPES, rng.randint(1, 4)),
                *rng.sample(PRINCIPALS, rng.randint(0, 3)),
                enabled=rng.random() > 0.15,
                constraints=rng.choice(CONSTRAINTS),
            )
        )
    return snapshot(*perms)


def apply(snap: Snapshot, result) -> Snapshot:
    perms = {str(pid): p for pid, p in snap.perms.items()}
    for op in result.operations:
        if op.op == "delete":
            del perms[op.key]
        else:
            perms[op.key] = op.after
    return Snapshot({i: p for i, p in enumerate(perms.values())}, snap.principals, snap.memberships)


def access(perms: dict[int, Perm], ref, ot, action) -> frozenset:
    """What a cell really grants: the set of (enabled, constraints) of the permissions covering it."""
    return frozenset(
        (p.enabled, json.dumps(p.constraints, sort_keys=True)) for p in perms.values() if p.covers(ref, ot, action)
    )


@pytest.mark.parametrize("seed", range(500))
def test_random_change_sets(seed):
    rng = random.Random(seed)
    snap = random_snapshot(rng)
    changes = [
        CellChange(rng.choice(PRINCIPALS), rng.choice(TYPES), rng.choice(ACTIONS), rng.random() > 0.5)
        for _ in range(rng.randint(1, 6))
    ]
    final = {(c.principal, c.object_type, c.action): c.granted for c in changes}
    result = plan(snap, changes)
    after = apply(snap, result)

    for ref in PRINCIPALS:
        for ot in TYPES:
            for action in ACTIONS:
                wanted = final.get((ref, ot, action))
                if wanted is None:
                    assert access(after.perms, ref, ot, action) == access(snap.perms, ref, ot, action), (
                        ref,
                        ot,
                        action,
                    )
                elif wanted:
                    state = cell_state(after, ref, ot, action)
                    assert state in (CellState.GRANTED, CellState.DISABLED), (ref, ot, action, state)
                    if state is CellState.DISABLED:
                        assert result.warnings
                else:
                    assert cell_state(after, ref, ot, action) is CellState.NONE, (ref, ot, action)

    names = [p.name for p in after.perms.values()]
    assert len(names) == len(set(names)) or len(set(p.name for p in snap.perms.values())) < len(snap.perms)
    assert all(p.object_types and p.actions for p in after.perms.values())
