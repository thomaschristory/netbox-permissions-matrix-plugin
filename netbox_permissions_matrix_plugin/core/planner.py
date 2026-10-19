"""Turn matrix cell changes and gear-panel edits into create, update and delete operations on permissions.

The rules are in docs/DESIGN.md ("How changes map to native permissions"). In short:

- a grant goes into the principal's simple permission for the set of actions the object type ends up with, named
  after that set ("netops_vac" for view, add and change), created if needed;
- a revoke removes the cell from every permission covering it, splitting a permission when it also grants other
  cells or is shared with other principals, so nobody else's access changes.
"""

from __future__ import annotations

import dataclasses
import re
from collections import defaultdict
from collections.abc import Iterable

from .model import GROUP, UNSET, CellChange, Operation, Perm, PermEdit, Plan, PrincipalRef, Snapshot

NAME_MAX = 100  # ObjectPermission.name max_length
DESCRIPTION_MAX = 200  # ObjectPermission.description max_length
DEFAULT_NAME_TEMPLATE = "{principal}_{actions}"
ACTION_ORDER = ("view", "add", "change", "delete")
ACTION_LETTERS = {"view": "v", "add": "a", "change": "c", "delete": "d", "render_config": "r", "sync": "s"}


def canonical(actions: Iterable[str]) -> tuple[str, ...]:
    """Reserved actions first, in CRUD order, then custom actions by name."""
    rank = {a: i for i, a in enumerate(ACTION_ORDER)}
    return tuple(sorted(set(actions), key=lambda a: (rank.get(a, len(rank)), a)))


def action_letters(actions: Iterable[str]) -> str:
    return "".join(ACTION_LETTERS.get(a, a[0]) for a in canonical(actions))


def slug(name: str) -> str:
    return re.sub(r"[^0-9a-z]+", "_", name.lower()).strip("_") or "principal"


class _Work:
    """Mutable working copy of the permissions, keyed by "<id>" or "new-N"."""

    def __init__(self, snap: Snapshot):
        self.snap = snap
        self.perms: dict[str, Perm] = {str(pid): p for pid, p in sorted(snap.perms.items())}
        self.names: set[str] = {p.name for p in snap.perms.values()}
        self.reasons: dict[str, list[str]] = defaultdict(list)
        self.warnings: list[str] = []
        self.emptied: set[str] = set()  # keys a revoke left without object types; deleted unless a grant reuses them
        self._new = 0

    def order(self, key: str) -> tuple[int, int]:
        # Existing permissions first, by ID, then the ones this plan creates, in creation order.
        return (1, int(key[4:])) if key.startswith("new-") else (0, int(key))

    def ordered_keys(self) -> list[str]:
        return sorted(self.perms, key=self.order)

    def unique_name(self, base: str) -> str:
        base = base[:NAME_MAX]
        name, n = base, 1
        while name in self.names:
            n += 1
            suffix = f" {n}"
            name = base[: NAME_MAX - len(suffix)] + suffix
        self.names.add(name)
        return name

    def create(self, perm: Perm, reason: str) -> str:
        self._new += 1
        key = f"new-{self._new}"
        self.perms[key] = perm
        self.reasons[key].append(reason)
        return key

    def replace(self, key: str, perm: Perm, reason: str) -> None:
        self.perms[key] = perm
        self.reasons[key].append(reason)

    def delete(self, key: str, reason: str) -> None:
        del self.perms[key]
        self.reasons[key].append(reason)

    def set_key(self, ref: PrincipalRef, actions: Iterable[str]) -> str | None:
        """The principal's simple permission for exactly this set of actions."""
        wanted = set(actions)
        for key in self.ordered_keys():
            perm = self.perms[key]
            if perm.is_simple(ref) and set(perm.actions) == wanted:
                return key
        return None

    def simple_key(self, ref: PrincipalRef, action: str) -> str | None:
        for key in self.ordered_keys():
            if self.perms[key].is_simple_for(ref, action):
                return key
        return None


def _assign(ref: PrincipalRef) -> dict:
    if ref.kind == GROUP:
        return {"groups": frozenset({ref.id}), "users": frozenset()}
    return {"groups": frozenset(), "users": frozenset({ref.id})}


def _without(perm: Perm, ref: PrincipalRef) -> Perm:
    if ref.kind == GROUP:
        return dataclasses.replace(perm, groups=perm.groups - {ref.id})
    return dataclasses.replace(perm, users=perm.users - {ref.id})


def _dedupe(changes: Iterable[CellChange]) -> list[CellChange]:
    """Last change per cell wins; the result is sorted so the plan does not depend on click order."""
    last: dict[tuple, CellChange] = {}
    for change in changes:
        last[(change.principal, change.object_type, change.action)] = change
    return [last[k] for k in sorted(last)]


def _place(work: _Work, ref: PrincipalRef, types: set[str], actions: Iterable[str], reason: str, template: str) -> None:
    """Add object types to the principal's simple permission for this action set, created if needed."""
    actions = canonical(actions)
    key = work.set_key(ref, actions)
    if key is not None:
        perm = work.perms[key]
        work.replace(key, dataclasses.replace(perm, object_types=perm.object_types | types), reason)
        return
    letters = action_letters(actions)
    pname = slug(work.snap.name_of(ref))
    work.create(
        Perm(
            id=None,
            name=work.unique_name(template.format(principal=pname, actions=letters, action=letters)),
            actions=actions,
            object_types=frozenset(types),
            **_assign(ref),
        ),
        reason,
    )


def _revoke(work: _Work, ref: PrincipalRef, cells: set[tuple[str, str]], template: str) -> None:
    pname = work.snap.name_of(ref)
    for key in work.ordered_keys():
        perm = work.perms[key]
        if not perm.assigned_to(ref):
            continue
        removed = {(ot, a) for ot, a in cells if ot in perm.object_types and a in perm.actions}
        if not removed:
            continue
        # What the permission still grants this principal, grouped by the actions each object type keeps.
        groups: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for ot in perm.object_types:
            kept = tuple(a for a in perm.actions if (ot, a) not in removed)
            if kept:
                groups[kept].add(ot)
        # Most object types first, then most actions, then by name, so the plan is deterministic.
        ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), -len(item[0]), item[0]))
        cells_text = ", ".join(f"{a} {ot}" for ot, a in sorted(removed))
        exclusive = perm.principals() == {ref}

        if perm.is_simple(ref):
            # A simple permission keeps the object types that still have its exact actions; the others move to the
            # simple permission for the actions they keep.
            same = set().union(*(types for actions, types in ordered if set(actions) == set(perm.actions)))
            work.replace(
                key, dataclasses.replace(perm, object_types=frozenset(same)), f"Revoke {cells_text} for {pname}"
            )
            if not same:
                work.emptied.add(key)
            for actions, types in ordered:
                if set(actions) != set(perm.actions):
                    _place(
                        work, ref, types, actions, f"Keep {', '.join(actions)} for {pname} after {cells_text}", template
                    )
            continue
        if exclusive and not ordered:
            # Emptied, not deleted yet: a grant in the same change set may reuse it (see _drop_emptied).
            work.replace(key, dataclasses.replace(perm, object_types=frozenset()), f"Revoke {cells_text} for {pname}")
            work.emptied.add(key)
            continue
        if exclusive:
            (actions, types), rest = ordered[0], ordered[1:]
            work.replace(
                key,
                dataclasses.replace(perm, actions=actions, object_types=frozenset(types)),
                f"Revoke {cells_text} for {pname}",
            )
        else:
            rest = ordered
            work.replace(key, _without(perm, ref), f"Remove {pname}, who loses {cells_text}; other assignees unchanged")
        for actions, types in rest:
            description = f"Split from {perm.name}."
            if perm.description:
                description += f" {perm.description}"
            work.create(
                dataclasses.replace(
                    perm,
                    id=None,
                    name=work.unique_name(f"{perm.name} ({pname})"),
                    description=description[:DESCRIPTION_MAX],
                    actions=actions,
                    object_types=frozenset(types),
                    **_assign(ref),
                ),
                f"Keep what {pname} had from {perm.name}, without {cells_text}",
            )


def _drop_emptied(work: _Work) -> None:
    """Delete the permissions revokes emptied and no grant reused."""
    for key in sorted(work.emptied, key=work.order):
        perm = work.perms[key]
        if not perm.object_types:
            work.delete(key, f"Nothing left in {perm.name}")


def _grant(work: _Work, ref: PrincipalRef, ot: str, actions: set[str], template: str) -> None:
    needed = {
        a
        for a in actions
        if not any(p.enabled and not p.constrained and p.covers(ref, ot, a) for p in work.perms.values())
    }
    if not needed:
        return
    pname = work.snap.name_of(ref)
    text = ", ".join(canonical(needed))
    have: set[str] = set()
    source = next(
        (k for k in work.ordered_keys() if work.perms[k].is_simple(ref) and ot in work.perms[k].object_types), None
    )
    if source is not None:
        # The object type moves to the permission for its new, larger action set.
        perm = work.perms[source]
        have = set(perm.actions)
        work.replace(
            source,
            dataclasses.replace(perm, object_types=perm.object_types - {ot}),
            f"Move {ot} for {pname} to the permission with {text} added",
        )
        if not work.perms[source].object_types:
            work.emptied.add(source)
    _place(work, ref, {ot}, have | needed, f"Grant {text} on {ot} to {pname}", template)


def _edit(work: _Work, edit: PermEdit) -> None:
    pname = work.snap.name_of(edit.principal)
    if edit.perm_id is not None:
        key = str(edit.perm_id)
        if key not in work.perms or not work.perms[key].assigned_to(edit.principal):
            work.warnings.append(f"Permission {edit.perm_id} is not assigned to {pname}; edit left out.")
            return
    else:
        key = work.simple_key(edit.principal, edit.action)
    if key is None:
        work.warnings.append(f"{pname} has no permission of its own for {edit.action} to edit; tick a cell first.")
        return
    perm = work.perms[key]
    fields = {}
    for attr in ("name", "description", "enabled", "constraints"):
        value = getattr(edit, attr)
        if value is not UNSET:
            fields[attr] = value
    if "name" in fields and fields["name"] != perm.name:
        work.names.discard(perm.name)
        fields["name"] = work.unique_name(fields["name"])
    if edit.add_actions:
        fields["actions"] = perm.actions + tuple(a for a in edit.add_actions if a not in perm.actions)
    if edit.add_groups:
        fields["groups"] = perm.groups | set(edit.add_groups)
    if edit.add_users:
        fields["users"] = perm.users | set(edit.add_users)
    after = dataclasses.replace(perm, **fields)
    if after == perm:
        return
    if edit.perm_id is not None:
        if perm.is_simple(edit.principal) and not after.is_simple(edit.principal):
            work.warnings.append(
                f"With constraints or other assignees {after.name} is no longer simple: new grants of "
                f"{', '.join(after.actions)} for {pname} will go into a new permission."
            )
    elif not after.is_simple_for(edit.principal, edit.action):
        work.warnings.append(
            f"After this change {after.name} is no longer simple (one principal, one action, no constraints): new "
            f"grants of {edit.action} for {pname} will go into a new permission."
        )
    work.replace(key, after, f"Edit {perm.name} from the gear panel")


def _grants(perm: Perm | None, ref: PrincipalRef) -> frozenset:
    if perm is None or not perm.assigned_to(ref):
        return frozenset()
    return frozenset((ot, a) for ot in perm.object_types for a in perm.actions)


def _affects(before: Perm | None, after: Perm | None) -> frozenset[PrincipalRef]:
    refs = (before.principals() if before else frozenset()) | (after.principals() if after else frozenset())
    if before and after and (before.enabled, before.constraints) != (after.enabled, after.constraints):
        return refs
    return frozenset(r for r in refs if _grants(before, r) != _grants(after, r))


def plan(
    snap: Snapshot,
    changes: Iterable[CellChange],
    edits: Iterable[PermEdit] = (),
    name_template: str = DEFAULT_NAME_TEMPLATE,
) -> Plan:
    work = _Work(snap)
    changes = _dedupe(changes)

    revokes: dict[PrincipalRef, set[tuple[str, str]]] = defaultdict(set)
    for change in changes:
        if not change.granted:
            revokes[change.principal].add((change.object_type, change.action))
    for ref in sorted(revokes):
        _revoke(work, ref, revokes[ref], name_template)
    grants: dict[tuple[PrincipalRef, str], set[str]] = defaultdict(set)
    for change in changes:
        if change.granted:
            grants[(change.principal, change.object_type)].add(change.action)
    for ref, ot in sorted(grants):
        _grant(work, ref, ot, grants[(ref, ot)], name_template)
    _drop_emptied(work)
    for edit in sorted(edits, key=lambda e: (e.principal, e.action, e.perm_id or 0)):
        _edit(work, edit)

    operations = []
    for key in sorted(set(work.perms) | {str(pid) for pid in snap.perms}, key=work.order):
        before = None if key.startswith("new-") else snap.perms[int(key)]
        after = work.perms.get(key)
        if before == after:
            continue
        op = "create" if before is None else "delete" if after is None else "update"
        operations.append(Operation(op, key, before, after, _affects(before, after), tuple(work.reasons[key])))
    return Plan(operations, work.warnings)
