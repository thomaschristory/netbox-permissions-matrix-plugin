"""The matrix as a portable document (written as YAML by the Django layer), and its import as cell changes.

Principals are named by group name or username and object types by "app_label.model", never by ID, so a file can
move between NetBox instances. The file records its scope; an import changes cells inside that scope only.
"""

from __future__ import annotations

import re

from .cells import CellState, cell_state, covering
from .model import GROUP, USER, CellChange, PrincipalRef, Snapshot

FORMAT_VERSION = 1
ACTION = re.compile(r"^[a-z_][a-z0-9_]{0,29}$")


def principal_label(snap: Snapshot, ref: PrincipalRef) -> str:
    return f"{ref.kind}:{snap.name_of(ref)}"


def export_doc(snap: Snapshot, object_types: list[str], principals: list[PrincipalRef], actions: list[str]) -> dict:
    grants: dict[str, dict] = {}
    constrained: dict[str, dict] = {}
    disabled: dict[str, dict] = {}
    for ref in principals:
        label = principal_label(snap, ref)
        for action in actions:
            for ot in object_types:
                state = cell_state(snap, ref, ot, action)
                if state is CellState.GRANTED:
                    grants.setdefault(label, {}).setdefault(action, []).append(ot)
                elif state is CellState.CONSTRAINED:
                    for p in covering(snap, ref, ot, action):
                        if p.enabled:
                            entry = {"object_type": ot, "permission": p.name, "constraints": p.constraints}
                            constrained.setdefault(label, {}).setdefault(action, []).append(entry)
                elif state is CellState.DISABLED:
                    for p in covering(snap, ref, ot, action):
                        disabled.setdefault(label, {}).setdefault(action, []).append(
                            {"object_type": ot, "permission": p.name}
                        )
    return {
        "version": FORMAT_VERSION,
        "scope": {
            "principals": [{"type": r.kind, "name": snap.name_of(r)} for r in principals],
            "actions": list(actions),
            "object_types": list(object_types),
        },
        "grants": grants,
        "constrained": constrained,
        "disabled": disabled,
    }


def _scope(doc) -> tuple[list, list, list] | str:
    if not isinstance(doc, dict):
        return "The file is not a permissions matrix export."
    if doc.get("version") != FORMAT_VERSION:
        return f"Unsupported format version {doc.get('version')!r}; this plugin reads version {FORMAT_VERSION}."
    scope = doc.get("scope")
    if not isinstance(scope, dict):
        return "The file has no scope."
    principals, actions, object_types = scope.get("principals"), scope.get("actions"), scope.get("object_types")
    if not all(isinstance(x, list) for x in (principals, actions, object_types)):
        return "The scope needs lists of principals, actions and object types."
    if not all(isinstance(a, str) and ACTION.match(a) for a in actions):
        return "The scope lists an invalid action name."
    if not all(
        isinstance(p, dict) and p.get("type") in (GROUP, USER) and isinstance(p.get("name"), str) for p in principals
    ):
        return "Each principal in the scope needs a type (group or user) and a name."
    if not all(isinstance(ot, str) for ot in object_types):
        return "Object types in the scope must be strings like dcim.device."
    return principals, actions, object_types


def _listed(section, label: str, action: str) -> set[str]:
    """Object types listed for a principal and action in grants (strings) or constrained/disabled (entries)."""
    if not isinstance(section, dict):
        return set()
    items = (section.get(label) or {}).get(action) or []
    if not isinstance(items, list):
        return set()
    return {i if isinstance(i, str) else i.get("object_type") for i in items if isinstance(i, str | dict)}


def import_changes(snap: Snapshot, doc, valid_object_types: set[str]) -> tuple[list[CellChange], list[str], list[str]]:
    """Cell changes that make the scope of the document true. Returns (changes, warnings, errors)."""
    scope = _scope(doc)
    if isinstance(scope, str):
        return [], [], [scope]
    principals, actions, object_types = scope
    errors, warnings, changes = [], [], []

    by_name = {(r.kind, p.name): r for r, p in snap.principals.items()}
    refs = []
    for entry in principals:
        ref = by_name.get((entry["type"], entry["name"]))
        if ref is None:
            errors.append(f"Unknown {entry['type']} {entry['name']!r}: its entries are skipped.")
        else:
            refs.append(ref)
    types = []
    for ot in object_types:
        if ot in valid_object_types:
            types.append(ot)
        else:
            errors.append(f"Unknown object type {ot}: its entries are skipped.")
    for section in ("grants", "constrained", "disabled"):
        for per_action in (doc.get(section) or {}).values():
            for listed in (per_action or {}).values() if isinstance(per_action, dict) else ():
                for item in listed or []:
                    ot = item if isinstance(item, str) else (item or {}).get("object_type")
                    if (
                        ot not in valid_object_types
                        and f"Unknown object type {ot}: its entries are skipped." not in errors
                    ):
                        errors.append(f"Unknown object type {ot}: its entries are skipped.")

    for ref in refs:
        label = f"{ref.kind}:{snap.name_of(ref)}"
        for action in actions:
            granted = _listed(doc.get("grants"), label, action)
            kept = _listed(doc.get("constrained"), label, action) | _listed(doc.get("disabled"), label, action)
            for ot in types:
                state = cell_state(snap, ref, ot, action)
                if ot in granted:
                    if state is not CellState.GRANTED:
                        changes.append(CellChange(ref, ot, action, True))
                elif ot in kept:
                    if state is CellState.NONE:
                        warnings.append(
                            f"{label} {action} {ot} is constrained or disabled in the file but not granted here; "
                            "left unchanged (the import never creates constraints)."
                        )
                elif state is not CellState.NONE:
                    changes.append(CellChange(ref, ot, action, False))
    return changes, warnings, errors
