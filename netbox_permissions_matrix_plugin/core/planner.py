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

    def replace(self, key: str, perm: Perm, *reasons: str) -> None:
        self.perms[key] = perm
        self.reasons[key].extend(reasons)

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


def _generated_name(work: _Work, ref: PrincipalRef, actions: Iterable[str], template: str) -> str:
    letters = action_letters(actions)
    return template.format(principal=slug(work.snap.name_of(ref)), actions=letters, action=letters)


LEGACY_NAME_TEMPLATE = "{principal} | {action}"  # the default up to 0.1.0, one action per permission


def _has_generated_name(work: _Work, ref: PrincipalRef, perm: Perm, template: str) -> bool:
    """Whether the permission still has a name the plugin gave it, with or without a number: then it may be renamed."""
    names = [_generated_name(work, ref, perm.actions, template)]
    if len(perm.actions) == 1:
        names.append(LEGACY_NAME_TEMPLATE.format(principal=work.snap.name_of(ref), action=perm.actions[0]))
    return any(re.fullmatch(rf"{re.escape(n)}( \d+)?", perm.name) for n in names)


def _place(
    work: _Work,
    ref: PrincipalRef,
    types: set[str],
    actions: Iterable[str],
    reason: str,
    template: str,
    reuse: str | None = None,
) -> str | None:
    """Add object types to the principal's simple permission for this action set.

    Without one, reuse (a simple permission this change emptied) is turned into it, keeping its ID; otherwise one is
    created. Returns reuse if it was not used.
    """
    actions = canonical(actions)
    key = work.set_key(ref, actions)
    if key is not None:
        perm = work.perms[key]
        work.replace(key, dataclasses.replace(perm, object_types=perm.object_types | types), reason)
        return reuse
    if reuse is not None:
        perm = work.perms[reuse]
        name = perm.name
        if _has_generated_name(work, ref, perm, template):
            # Still the name the plugin gave it: rename it after its new actions.
            work.names.discard(name)
            name = work.unique_name(_generated_name(work, ref, actions, template))
        work.replace(
            reuse, dataclasses.replace(perm, name=name, actions=actions, object_types=frozenset(types)), reason
        )
        return None
    work.create(
        Perm(
            id=None,
            name=work.unique_name(_generated_name(work, ref, actions, template)),
            actions=actions,
            object_types=frozenset(types),
            **_assign(ref),
        ),
        reason,
    )
    return reuse


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
            reuse = None
            if not same:
                work.emptied.add(key)
                reuse = key
            for actions, types in ordered:
                if set(actions) != set(perm.actions):
                    reason = f"Keep {', '.join(actions)} for {pname} after revoking {cells_text}"
                    reuse = _place(work, ref, types, actions, reason, template, reuse)
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


def _drop_emptied(work: _Work, template: str) -> None:
    """Delete the permissions this plan emptied and nothing reused.

    An emptied simple permission first takes over a permission the plan created for the same principal when one's
    actions contain the other's (view, add emptied while view, add, change was created): it keeps its ID instead.
    """
    for key in sorted(work.emptied, key=work.order):
        perm = work.perms.get(key)
        if perm is None or perm.object_types:
            # Gone already (taken over by an earlier emptied permission), or filled again by a grant.
            continue
        refs = perm.principals()
        ref = next(iter(refs)) if len(refs) == 1 else None
        # Only a simple permission may take over a grant: a constrained or disabled one would pass its constraints or
        # its disabled flag on to access that was ticked without them.
        simple = ref is not None and perm.is_simple(ref)
        created = next(
            (
                k
                for k in work.ordered_keys()
                if simple
                and k != key
                and k.startswith("new-")
                and work.perms[k].object_types
                and work.perms[k].is_simple(ref)
                and (set(work.perms[k].actions) <= set(perm.actions) or set(work.perms[k].actions) >= set(perm.actions))
            ),
            None,
        )
        if created is None:
            work.delete(key, f"Nothing left in {perm.name}")
            continue
        new = work.perms.pop(created)
        name = perm.name
        if _has_generated_name(work, ref, perm, template):
            name = new.name
        work.replace(
            key,
            dataclasses.replace(perm, name=name, actions=new.actions, object_types=new.object_types),
            *work.reasons.pop(created, [f"Becomes {new.name}"]),
        )


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
    reuse = None
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
            reuse = source
    _place(work, ref, {ot}, have | needed, f"Grant {text} on {ot} to {pname}", template, reuse)


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
            why = "constrained" if after.constrained else "disabled" if not after.enabled else "shared"
            work.warnings.append(
                f"Once {why}, {after.name} is no longer simple: new grants of {', '.join(after.actions)} for {pname} "
                "will go into a new permission."
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
    edits = sorted(edits, key=lambda e: (e.principal, e.action, e.perm_id or 0))

    # Edits of a permission by ID come first, on the permission as the panel showed it: a permission disabled or
    # constrained here is then no longer simple, so grants in the same change set go elsewhere.
    for edit in edits:
        if edit.perm_id is not None:
            _edit(work, edit)

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
    _drop_emptied(work, name_template)
    # Edits by action target the simple permission the grants above may have created.
    for edit in edits:
        if edit.perm_id is None:
            _edit(work, edit)
    for edit in edits:
        if edit.perm_id is not None and edit.perm_id in snap.perms and str(edit.perm_id) not in work.perms:
            work.warnings.append(
                f"{snap.perms[edit.perm_id].name} is deleted by the cell changes in this change set; its edit is lost."
            )

    operations = []
    for key in sorted(set(work.perms) | {str(pid) for pid in snap.perms}, key=work.order):
        before = None if key.startswith("new-") else snap.perms[int(key)]
        after = work.perms.get(key)
        if before == after:
            continue
        op = "create" if before is None else "delete" if after is None else "update"
        operations.append(Operation(op, key, before, after, _affects(before, after), tuple(work.reasons[key])))
    return Plan(operations, work.warnings)
