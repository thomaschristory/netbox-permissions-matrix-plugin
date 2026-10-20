"""Random snapshots, change sets and gear panel edits: nobody untouched loses or gains anything, every changed cell ends
as asked, and every edit ends as asked."""

from __future__ import annotations

import dataclasses
import json
import random
import re

import pytest

from netbox_permissions_matrix_plugin.core.cells import CellState, cell_state
from netbox_permissions_matrix_plugin.core.model import UNSET, CellChange, Perm, PermEdit, Snapshot
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
                    assert state is CellState.GRANTED, (ref, ot, action, state)
                else:
                    assert cell_state(after, ref, ot, action) is CellState.NONE, (ref, ot, action)

    names = [p.name for p in after.perms.values()]
    assert len(names) == len(set(names)) or len(set(p.name for p in snap.perms.values())) < len(snap.perms)
    assert all(p.object_types and p.actions for p in after.perms.values())


DENSE_TYPES = ["a.x", "a.y", "a.z"]
DENSE_ACTIONS = ["view", "add", "change"]
# Names the planner itself would generate, so reuse, renaming and numbering all come into play.
DENSE_NAMES = ["noc_v", "noc_va", "ops_v", "noc_v 2", "NOC | view"]


@pytest.mark.parametrize("seed", range(3000))
def test_dense_change_sets(seed):
    """Few object types and actions, so revokes, splits, moves between action sets and reuse collide often."""
    rng = random.Random(seed)
    perms = [
        perm(
            pid,
            rng.choice([f"p{pid}", *DENSE_NAMES]),
            rng.sample(DENSE_ACTIONS, rng.randint(1, 2)),
            rng.sample(DENSE_TYPES, rng.randint(1, 2)),
            *rng.sample(PRINCIPALS, rng.randint(1, 2)),
            enabled=rng.random() > 0.2,
            constraints=rng.choice(CONSTRAINTS),
        )
        for pid in range(1, rng.randint(1, 5) + 1)
    ]
    snap = snapshot(*perms)
    changes = [
        CellChange(rng.choice(PRINCIPALS[:2]), rng.choice(DENSE_TYPES), rng.choice(DENSE_ACTIONS), rng.random() > 0.5)
        for _ in range(rng.randint(1, 6))
    ]
    final = {(c.principal, c.object_type, c.action): c.granted for c in changes}
    result = plan(snap, changes)
    after = apply(snap, result)

    for ref in PRINCIPALS:
        for ot in DENSE_TYPES:
            for action in DENSE_ACTIONS:
                wanted = final.get((ref, ot, action))
                if wanted is None:
                    assert access(after.perms, ref, ot, action) == access(snap.perms, ref, ot, action)
                elif wanted:
                    assert cell_state(after, ref, ot, action) is CellState.GRANTED, (ref, ot, action)
                else:
                    assert cell_state(after, ref, ot, action) is CellState.NONE, (ref, ot, action)
    assert all(p.object_types and p.actions for p in after.perms.values())
    assert result.operations == plan(snap, changes).operations


# Gear panel edits: rename, enable or disable, constraints and description.

EDIT_NAMES = ["renamed", "noc_v", "p1", "NOC | view"]
DESCRIPTIONS = ["", "Edited", "x" * 200]


def random_fields(rng: random.Random) -> dict:
    """At least one of the four fields the panel edits, each set to a random value."""
    values = {
        "name": lambda: rng.choice(EDIT_NAMES),
        "description": lambda: rng.choice(DESCRIPTIONS),
        "enabled": lambda: rng.random() > 0.5,
        "constraints": lambda: rng.choice(CONSTRAINTS),
    }
    attrs = rng.sample(sorted(values), rng.randint(1, 4))
    return {attr: values[attr]() for attr in attrs}


def random_edits(rng: random.Random, snap: Snapshot, principals, actions) -> list[PermEdit]:
    """Edits by permission ID (sometimes of a permission not assigned to the principal) and by action, at most one per
    permission and one per principal and action, as the panel sends them."""
    edits = []
    for pid in rng.sample(sorted(snap.perms), rng.randint(0, min(2, len(snap.perms)))):
        assigned = sorted(snap.perms[pid].principals())
        ref = rng.choice(assigned) if assigned and rng.random() > 0.1 else rng.choice(principals)
        edits.append(PermEdit(ref, perm_id=pid, **random_fields(rng)))
    cells = sorted({(rng.choice(principals), rng.choice(actions)) for _ in range(rng.randint(0, 2))})
    edits += [PermEdit(ref, action, **random_fields(rng)) for ref, action in cells]
    rng.shuffle(edits)
    return edits


def apply_keyed(snap: Snapshot, result) -> dict[str, Perm]:
    """The permissions after the plan, keyed as the plan keys them ("<id>" or "new-N")."""
    perms = {str(pid): p for pid, p in snap.perms.items()}
    for op in result.operations:
        if op.op == "delete":
            del perms[op.key]
        else:
            perms[op.key] = op.after
    return perms


def as_snapshot(snap: Snapshot, perms: dict[str, Perm]) -> Snapshot:
    return Snapshot({i: p for i, p in enumerate(perms.values())}, snap.principals, snap.memberships)


def edited(perm: Perm, edit: PermEdit) -> Perm:
    """The permission with the edit's fields, as asked (a taken name may come back with a number)."""
    fields = {attr: getattr(edit, attr) for attr in ("name", "description", "enabled", "constraints")}
    return dataclasses.replace(perm, **{attr: value for attr, value in fields.items() if value is not UNSET})


def same_but_name(a: Perm, b: Perm) -> bool:
    return dataclasses.replace(a, name="") == dataclasses.replace(b, name="")


def name_as_asked(name: str, asked: str) -> bool:
    return re.fullmatch(rf"{re.escape(asked)}( \d+)?", name) is not None


def order(key: str) -> tuple[int, int]:
    return (1, int(key[4:])) if key.startswith("new-") else (0, int(key))


def check_with_edits(snap: Snapshot, changes, edits, principals, types, actions):
    by_id = [e for e in edits if e.perm_id is not None]
    by_action = [e for e in edits if e.perm_id is None]
    final = {(c.principal, c.object_type, c.action): c.granted for c in changes}

    # What the panel asked of the permissions edited by ID, on the permissions as it showed them.
    asked = dict(snap.perms)
    for e in by_id:
        if snap.perms[e.perm_id].assigned_to(e.principal):
            asked[e.perm_id] = edited(snap.perms[e.perm_id], e)

    # Edits by ID and cell changes: the cell invariants hold against the edited permissions.
    first = plan(snap, changes, by_id)
    middle = apply_keyed(snap, first)
    middle_snap = as_snapshot(snap, middle)
    for ref in principals:
        for ot in types:
            for action in actions:
                cell = (ref, ot, action)
                wanted = final.get(cell)
                if wanted is None:
                    assert access(middle_snap.perms, *cell) == access(asked, *cell), cell
                elif wanted:
                    assert cell_state(middle_snap, *cell) is CellState.GRANTED, cell
                else:
                    assert cell_state(middle_snap, *cell) is CellState.NONE, cell
    for e in by_id:
        key = str(e.perm_id)
        if key not in middle:
            # Emptied and deleted by the cell changes: the review says the edit is lost.
            if snap.perms[e.perm_id].assigned_to(e.principal):
                assert any("its edit is lost" in w for w in first.warnings), (e, first.warnings)
            continue
        perm = middle[key]
        if not snap.perms[e.perm_id].assigned_to(e.principal):
            assert any(f"Permission {e.perm_id} is not assigned" in w for w in first.warnings)
            continue
        for attr in ("description", "enabled", "constraints"):
            if getattr(e, attr) is not UNSET:
                assert getattr(perm, attr) == getattr(e, attr), (e, perm)
        if e.name is not UNSET and e.name != snap.perms[e.perm_id].name:
            assert name_as_asked(perm.name, e.name), (e, perm)
    # Edits by ID of a permission not assigned to the principal are left out entirely.
    assigned = [e for e in by_id if snap.perms[e.perm_id].assigned_to(e.principal)]
    assert first.operations == plan(snap, changes, assigned).operations
    # Cell changes never touch the description, enabled or constraints of an existing permission, and rename it only
    # when they reshape it: every permission keeps those fields as the panel asked, or as they were when not edited.
    for pid, was in asked.items():
        now = middle.get(str(pid))
        if now is None:
            continue
        assert (now.description, now.enabled, now.constraints) == (was.description, was.enabled, was.constraints), (
            pid,
            now,
            was,
        )
        reshaped = (now.actions, now.object_types) != (was.actions, was.object_types)
        if not reshaped:
            assert name_as_asked(now.name, was.name) if was.name != snap.perms[pid].name else now.name == was.name, (
                pid,
                now,
                was,
            )

    # Edits by action then change only the principal's own permission for that one action, and only as asked.
    result = plan(snap, changes, edits)
    after = apply_keyed(snap, result)
    expected, targets = dict(middle), set()
    for e in by_action:
        key = next((k for k in sorted(middle, key=order) if middle[k].is_simple_for(e.principal, e.action)), None)
        if key is None:
            assert any(f"no permission of its own for {e.action}" in w for w in result.warnings), (e, result.warnings)
            continue
        expected[key] = edited(middle[key], e)
        targets.add(key)
        if e.name is not UNSET and e.name != middle[key].name:
            assert name_as_asked(after[key].name, e.name), (e, after[key])
        else:
            assert after[key].name == middle[key].name, (e, after[key])
    assert sorted(after) == sorted(expected)
    for key in after:
        assert same_but_name(after[key], expected[key]), (key, after[key], expected[key])
        if key not in targets:
            assert after[key].name == middle[key].name, key

    names = [p.name for p in after.values()]
    assert len(names) == len(set(names)) or len(set(p.name for p in snap.perms.values())) < len(snap.perms)
    assert all(p.object_types and p.actions for p in after.values())
    assert result.operations == plan(snap, changes, list(reversed(edits))).operations


@pytest.mark.parametrize("seed", range(500))
def test_random_change_sets_with_edits(seed):
    rng = random.Random(seed)
    snap = random_snapshot(rng)
    changes = [
        CellChange(rng.choice(PRINCIPALS), rng.choice(TYPES), rng.choice(ACTIONS), rng.random() > 0.5)
        for _ in range(rng.randint(0, 6))
    ]
    edits = random_edits(rng, snap, PRINCIPALS, ACTIONS)
    check_with_edits(snap, changes, edits, PRINCIPALS, TYPES, ACTIONS)


@pytest.mark.parametrize("seed", range(3000))
def test_dense_change_sets_with_edits(seed):
    """Edits of the permissions the cell changes also touch, and names that collide with generated ones."""
    rng = random.Random(seed)
    perms = [
        perm(
            pid,
            rng.choice([f"p{pid}", *DENSE_NAMES]),
            rng.sample(DENSE_ACTIONS, rng.randint(1, 2)),
            rng.sample(DENSE_TYPES, rng.randint(1, 2)),
            *rng.sample(PRINCIPALS, rng.randint(1, 2)),
            enabled=rng.random() > 0.2,
            constraints=rng.choice(CONSTRAINTS),
        )
        for pid in range(1, rng.randint(1, 5) + 1)
    ]
    snap = snapshot(*perms)
    changes = [
        CellChange(rng.choice(PRINCIPALS[:2]), rng.choice(DENSE_TYPES), rng.choice(DENSE_ACTIONS), rng.random() > 0.5)
        for _ in range(rng.randint(0, 6))
    ]
    edits = random_edits(rng, snap, PRINCIPALS[:2], DENSE_ACTIONS)
    check_with_edits(snap, changes, edits, PRINCIPALS, DENSE_TYPES, DENSE_ACTIONS)
