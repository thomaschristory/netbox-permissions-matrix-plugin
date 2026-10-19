"""Turn matrix cell changes and gear-panel edits into create, update and delete operations on permissions.

The rules are in docs/DESIGN.md ("How changes map to native permissions"). In short:

- a grant goes into the principal's simple permission for that action, created if needed;
- a revoke removes the cell from every permission covering it, splitting a permission when it also grants other
  cells or is shared with other principals, so nobody else's access changes.
"""

from __future__ import annotations

import dataclasses
from collections import defaultdict
from collections.abc import Iterable

from .model import GROUP, UNSET, CellChange, Operation, Perm, PermEdit, Plan, PrincipalRef, Snapshot

NAME_MAX = 100  # ObjectPermission.name max_length
DESCRIPTION_MAX = 200  # ObjectPermission.description max_length
DEFAULT_NAME_TEMPLATE = "{principal} | {action}"


class _Work:
    """Mutable working copy of the permissions, keyed by "<id>" or "new-N"."""

    def __init__(self, snap: Snapshot):
        self.snap = snap
        self.perms: dict[str, Perm] = {str(pid): p for pid, p in sorted(snap.perms.items())}
        self.names: set[str] = {p.name for p in snap.perms.values()}
        self.reasons: dict[str, list[str]] = defaultdict(list)
        self.warnings: list[str] = []
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


def _revoke(work: _Work, ref: PrincipalRef, cells: set[tuple[str, str]]) -> None:
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

        if exclusive and not ordered:
            work.delete(key, f"Revoke {cells_text} for {pname}: nothing left in {perm.name}")
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


def _grant(work: _Work, change: CellChange, name_template: str) -> None:
    ref, ot, action = change.principal, change.object_type, change.action
    covering = [p for p in work.perms.values() if p.covers(ref, ot, action)]
    if any(p.enabled and not p.constrained for p in covering):
        return
    pname = work.snap.name_of(ref)
    key = work.simple_key(ref, action)
    if key is not None:
        perm = work.perms[key]
        work.replace(
            key, dataclasses.replace(perm, object_types=perm.object_types | {ot}), f"Grant {action} {ot} to {pname}"
        )
        if not perm.enabled:
            work.warnings.append(
                f"{perm.name} is disabled: the grant of {action} {ot} stays inactive until it is enabled."
            )
        return
    work.create(
        Perm(
            id=None,
            name=work.unique_name(name_template.format(principal=pname, action=action)),
            actions=(action,),
            object_types=frozenset({ot}),
            **_assign(ref),
        ),
        f"Grant {action} {ot} to {pname}",
    )


def _edit(work: _Work, edit: PermEdit) -> None:
    pname = work.snap.name_of(edit.principal)
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
    if not after.is_simple_for(edit.principal, edit.action):
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
        _revoke(work, ref, revokes[ref])
    for change in changes:
        if change.granted:
            _grant(work, change, name_template)
    for edit in sorted(edits, key=lambda e: (e.principal, e.action)):
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
