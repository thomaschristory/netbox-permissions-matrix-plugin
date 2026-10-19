"""The matrix as JSON for the page and the REST API."""

from __future__ import annotations

from django.urls import reverse

from .core.cells import CellState, cell_state, covering, inherited_state
from .core.model import USER, Perm, PrincipalRef, Snapshot
from .loader import ActionTab, Row


def perm_summary(perm: Perm, snap: Snapshot) -> dict:
    return {
        "id": perm.id,
        "name": perm.name,
        "description": perm.description,
        "enabled": perm.enabled,
        "actions": list(perm.actions),
        "object_types": sorted(perm.object_types),
        "constraints": perm.constraints,
        "constrained": perm.constrained,
        "principals": [{"type": r.kind, "id": r.id, "name": snap.name_of(r)} for r in sorted(perm.principals())],
        "url": reverse("users:objectpermission", args=[perm.id]) if perm.id else None,
    }


def row_enabled(row: Row, tab: ActionTab) -> bool:
    return not tab.custom or tab.name in row.custom_actions


def column(snap: Snapshot, ref: PrincipalRef, action: str) -> dict:
    perms = sorted((p for p in snap.perms.values() if p.assigned_to(ref) and action in p.actions), key=lambda p: p.id)
    simple = next((p for p in perms if p.is_simple_for(ref, action)), None)
    return {
        "type": ref.kind,
        "id": ref.id,
        "key": ref.key,
        "name": snap.name_of(ref),
        "simple": perm_summary(simple, snap) if simple else None,
        "others": [perm_summary(p, snap) for p in perms if p is not simple],
    }


def build(
    snap: Snapshot,
    row_list: list[Row],
    columns: list[PrincipalRef],
    tab: ActionTab,
    tabs: list[ActionTab],
    can_edit: bool,
) -> dict:
    action = tab.name
    cells: dict[str, dict] = {}
    for ref in columns:
        col = cells[ref.key] = {}
        for row in row_list:
            perms = covering(snap, ref, row.object_type, action)
            entry = {}
            if perms:
                entry["state"] = str(cell_state(snap, ref, row.object_type, action))
                entry["perms"] = [perm_summary(p, snap) for p in perms]
            if ref.kind == USER:
                state, groups = inherited_state(snap, ref.id, row.object_type, action)
                if state is not CellState.NONE:
                    entry.setdefault("state", str(CellState.NONE))
                    entry.setdefault("perms", [])
                    entry["inherited"] = {"state": str(state), "groups": groups}
            if entry:
                col[row.object_type] = entry
    return {
        "action": action,
        "can_edit": can_edit,
        "actions": [
            {"name": t.name, "label": t.label, "custom": t.custom, "freeform": t.freeform, "help_text": t.help_text}
            for t in tabs
        ],
        "rows": [
            {
                "object_type": r.object_type,
                "app_label": r.app_label,
                "app_name": r.app_name,
                "label": r.label,
                "enabled": row_enabled(r, tab),
            }
            for r in row_list
        ],
        "columns": [column(snap, ref, action) for ref in columns],
        "cells": cells,
    }


def build_principal(snap: Snapshot, row_list: list[Row], ref: PrincipalRef, tabs: list[ActionTab], can_edit: bool):
    """One principal's matrix turned around: object types down the side, actions across the top."""
    cells: dict[str, dict] = {}
    for row in row_list:
        for tab in tabs:
            perms = covering(snap, ref, row.object_type, tab.name)
            entry = {}
            if perms:
                entry = {
                    "state": str(cell_state(snap, ref, row.object_type, tab.name)),
                    "perms": [perm_summary(p, snap) for p in perms],
                }
            if ref.kind == USER:
                state, groups = inherited_state(snap, ref.id, row.object_type, tab.name)
                if state is not CellState.NONE:
                    entry = {"state": str(CellState.NONE), "perms": [], **entry}
                    entry["inherited"] = {"state": str(state), "groups": groups}
            if entry:
                cells.setdefault(row.object_type, {})[tab.name] = entry
    return {
        "principal": {"type": ref.kind, "id": ref.id, "key": ref.key, "name": snap.name_of(ref)},
        "can_edit": can_edit,
        "actions": [
            {"name": t.name, "label": t.label, "custom": t.custom, "freeform": t.freeform, "help_text": t.help_text}
            for t in tabs
        ],
        "rows": [
            {
                "object_type": r.object_type,
                "app_label": r.app_label,
                "app_name": r.app_name,
                "label": r.label,
                "enabled_actions": [t.name for t in tabs if row_enabled(r, t)],
            }
            for r in row_list
        ],
        "columns": {t.name: column(snap, ref, t.name) for t in tabs},
        "cells": cells,
    }
