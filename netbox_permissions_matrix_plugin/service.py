"""What the page, the group tab, export/import and the REST API share: access checks, the matrix and plans."""

from __future__ import annotations

import json
from dataclasses import dataclass

from django.core.exceptions import FieldError, PermissionDenied, ValidationError
from django.db.models import Q
from django.http import Http404
from users.constants import CONSTRAINT_TOKEN_USER
from users.models import Group, ObjectPermission, User
from utilities.permissions import qs_filter_from_constraints

from . import loader, matrix
from .conf import get_setting
from .core.model import GROUP, USER, Plan, PrincipalRef, Snapshot
from .core.planner import plan as make_plan
from .core.token import version_token

WRITE_PERMISSIONS = ("users.add_objectpermission", "users.change_objectpermission", "users.delete_objectpermission")


def check_view(user) -> None:
    """The matrix shows every permission, so it needs view access to all of them, unconstrained."""
    if not user.is_authenticated or not user.has_perm("users.view_objectpermission"):
        raise PermissionDenied("You need the users.view_objectpermission permission to use the permissions matrix.")
    if user.is_superuser:
        return
    if ObjectPermission.objects.restrict(user, "view").count() != ObjectPermission.objects.count():
        raise PermissionDenied(
            "The permissions matrix needs view access to all permissions; yours is limited by constraints."
        )


def can_edit(user) -> bool:
    return user.is_authenticated and any(user.has_perm(p) for p in WRITE_PERMISSIONS)


def check_edit(user) -> None:
    check_view(user)
    if not can_edit(user):
        raise PermissionDenied("You are not allowed to add, change or delete permissions.")


def visible_groups(user) -> set[int]:
    return set(Group.objects.restrict(user, "view").values_list("pk", flat=True))


def visible_users(user) -> set[int]:
    if not user.has_perm("users.view_user"):
        return set()
    return set(User.objects.restrict(user, "view").values_list("pk", flat=True))


@dataclass
class MatrixQuery:
    action: str = "view"
    include_users: bool = False
    group_ids: tuple[int, ...] = ()
    user_ids: tuple[int, ...] = ()
    app_labels: tuple[str, ...] = ()


def columns_for(snap: Snapshot, user, query: MatrixQuery) -> list[PrincipalRef]:
    groups = visible_groups(user)
    refs = [r for r in snap.principals if r.kind == GROUP and r.id in groups]
    if query.group_ids:
        refs = [r for r in refs if r.id in query.group_ids]
    if query.include_users or query.user_ids:
        users = visible_users(user)
        direct = {uid for p in snap.perms.values() for uid in p.users}
        candidates = set(query.user_ids) if query.user_ids else direct
        refs += [r for r in snap.principals if r.kind == USER and r.id in users & candidates]
    # Groups first, then users, each by name.
    return sorted(refs, key=lambda r: (r.kind != GROUP, snap.name_of(r).lower()))


def matrix_payload(user, query: MatrixQuery) -> dict:
    check_view(user)
    snap = loader.load_snapshot(user_ids=query.user_ids)
    row_list = loader.rows(get_setting("hidden_apps"))
    if query.app_labels:
        row_list = [r for r in row_list if r.app_label in query.app_labels]
    tabs = loader.action_tabs(snap, row_list)
    if query.action == "*":
        return matrix.build_all(snap, row_list, columns_for(snap, user, query), tabs, can_edit(user))
    tab = next((t for t in tabs if t.name == query.action), None) or loader.ActionTab(
        query.action, query.action, freeform=True
    )
    return matrix.build(snap, row_list, columns_for(snap, user, query), tab, tabs, can_edit(user))


class PlanError(ValidationError):
    pass


def validate_constraints(result: Plan) -> None:
    """The same check as NetBox's permission form: run each new set of constraints against each object type."""
    from core.models import ObjectType

    errors = []
    for op in result.operations:
        after, before = op.after, op.before
        if after is None or not after.constrained:
            continue
        if before is not None and before.constraints == after.constraints and before.object_types == after.object_types:
            continue
        constraints = after.constraints if isinstance(after.constraints, list) else [after.constraints]
        if not all(isinstance(c, dict) for c in constraints):
            errors.append(f"{after.name}: constraints must be an object or a list of objects.")
            continue
        for label in sorted(after.object_types):
            app_label, model_name = label.split(".")
            model = ObjectType.objects.get(app_label=app_label, model=model_name).model_class()
            if model is None:
                continue
            try:
                model.objects.filter(qs_filter_from_constraints(constraints, {CONSTRAINT_TOKEN_USER: 0})).exists()
            except (FieldError, ValueError, TypeError) as exc:
                errors.append(f"{after.name}: invalid filter for {label}: {exc}")
    if errors:
        raise PlanError({"constraints": errors})


def plan_for(user, changes, edits) -> tuple[Snapshot, Plan, str]:
    """Plan a change set for this user. Returns the snapshot, the plan and the version token."""
    check_edit(user)
    refs = {c.principal for c in changes} | {e.principal for e in edits}
    snap = loader.load_snapshot(user_ids=[r.id for r in refs if r.kind == USER])
    groups, users = visible_groups(user), visible_users(user)
    for ref in (
        refs
        | {PrincipalRef(GROUP, g) for e in edits for g in e.add_groups}
        | {PrincipalRef(USER, u) for e in edits for u in e.add_users}
    ):
        if ref.id not in (groups if ref.kind == GROUP else users):
            raise PlanError({"principal": [f"No such {ref.kind}: {ref.id}"]})
    for edit in edits:
        if edit.perm_id is None:
            continue
        target = snap.perms.get(edit.perm_id)
        if target is None:
            raise PlanError({"edits": [f"No such permission: {edit.perm_id}"]})
        # Editing a permission changes everyone it is assigned to: they must all be visible to the editor.
        if any(r.id not in (groups if r.kind == GROUP else users) for r in target.principals()):
            raise PlanError({"edits": [f"{target.name} is also assigned to groups or users you cannot see."]})
    result = make_plan(snap, changes, edits, name_template=get_setting("new_permission_name"))
    validate_constraints(result)
    return snap, result, version_token(snap, refs)


def principal_json(snap: Snapshot, ref: PrincipalRef) -> dict:
    return {"type": ref.kind, "id": ref.id, "name": snap.name_of(ref)}


def plan_json(snap: Snapshot, result: Plan, token: str) -> dict:
    return {
        "token": token,
        "warnings": result.warnings,
        "operations": [
            {
                "op": op.op,
                "key": op.key,
                "id": op.perm_id,
                "before": matrix.perm_summary(op.before, snap) if op.before else None,
                "after": matrix.perm_summary(op.after, snap) if op.after else None,
                "affects": [principal_json(snap, r) for r in sorted(op.affects)],
                "reasons": list(op.reasons),
            }
            for op in result.operations
        ],
    }


def dumps(data) -> str:
    return json.dumps(data, sort_keys=True)


def principal_payload(user, ref: PrincipalRef) -> dict:
    check_view(user)
    visible = visible_groups(user) if ref.kind == GROUP else visible_users(user)
    if ref.id not in visible:
        raise Http404(f"No such {ref.kind}")
    snap = loader.load_snapshot(user_ids=[ref.id] if ref.kind == USER else ())
    row_list = loader.rows(get_setting("hidden_apps"))
    return matrix.build_principal(snap, row_list, ref, loader.action_tabs(snap, row_list), can_edit(user))


def who_can(user, label: str) -> dict:
    """Everyone holding any action on one object type, directly and through groups."""
    from core.models import ObjectType

    from .core.cells import covering, state_of

    check_view(user)
    row = next((r for r in loader.rows() if r.object_type == label), None)
    if row is None:
        raise Http404(f"{label} is not an object type permissions can be assigned to")
    snap = loader.load_snapshot()
    tabs = loader.action_tabs(snap, [row])
    custom = [t for t in tabs if not t.custom or t.name in row.custom_actions]
    used = {a for p in snap.perms.values() if label in p.object_types for a in p.actions}
    actions = [t for t in custom if not t.freeform or t.name in used]

    groups, users = visible_groups(user), visible_users(user)
    principals = []
    for ref in sorted(snap.principals, key=lambda r: (r.kind != GROUP, snap.name_of(r).lower())):
        if ref.id not in (groups if ref.kind == GROUP else users):
            continue
        cells = {}
        for tab in actions:
            perms = covering(snap, ref, label, tab.name)
            if perms:
                cells[tab.name] = {
                    "state": str(state_of(perms)),
                    "perms": [matrix.perm_summary(p, snap) for p in perms],
                }
        if cells:
            principals.append({"ref": ref, "type": ref.kind, "id": ref.id, "name": snap.name_of(ref), "cells": cells})

    # Effective access: members of the groups above plus users with direct grants, active ones only.
    group_ids = [p["id"] for p in principals if p["type"] == GROUP]
    direct_ids = [p["id"] for p in principals if p["type"] == USER]
    candidates = User.objects.filter(is_active=True).filter(Q(groups__in=group_ids) | Q(pk__in=direct_ids))
    candidates = candidates.distinct().prefetch_related("groups").order_by("username")
    effective = []
    for member in candidates:
        if member.pk not in users:
            continue
        sources = [(PrincipalRef(USER, member.pk), "direct")]
        sources += [(PrincipalRef(GROUP, g.pk), g.name) for g in member.groups.all()]
        row_actions = {}
        for tab in actions:
            found, names = [], []
            for ref, source in sources:
                perms = covering(snap, ref, label, tab.name)
                if perms:
                    found += perms
                    names.append(source)
            if found:
                row_actions[tab.name] = {
                    "state": str(state_of(found)),
                    "sources": names,
                    "constraints": [p.constraints for p in found if p.enabled and p.constrained],
                }
        if row_actions:
            effective.append({"user": member, "username": member.username, "actions": row_actions})

    return {
        "row": row,
        "object_type": ObjectType.objects.get(app_label=row.app_label, model=label.split(".")[1]),
        "actions": actions,
        "principals": principals,
        "effective": effective,
        "superusers": User.objects.filter(pk__in=users, is_superuser=True, is_active=True).order_by("username"),
    }


def search_rows(row_list, needle: str):
    """The page's search box: a case-insensitive match on the label, the object type or the app name."""
    needle = needle.strip().lower()
    if not needle:
        return row_list
    return [r for r in row_list if needle in f"{r.label} {r.object_type} {r.app_name}".lower()]


def export_payload(user, query: MatrixQuery, search: str = "") -> dict:
    """The matrix as a portable document: every action, for the columns and rows the page shows."""
    from .core.yaml_io import export_doc

    check_view(user)
    snap = loader.load_snapshot(user_ids=query.user_ids)
    row_list = loader.rows(get_setting("hidden_apps"))
    if query.app_labels:
        row_list = [r for r in row_list if r.app_label in query.app_labels]
    row_list = search_rows(row_list, search)
    principals = columns_for(snap, user, query)
    if query.group_ids or query.user_ids:
        # Columns picked on the page: exactly those, whether groups, users or both.
        picked = {PrincipalRef(GROUP, g) for g in query.group_ids} | {PrincipalRef(USER, u) for u in query.user_ids}
        principals = [r for r in principals if r in picked]
    actions = [t.name for t in loader.action_tabs(snap, row_list)]
    return export_doc(snap, [r.object_type for r in row_list], principals, actions)


def import_for(user, doc) -> dict:
    """Cell changes that make a document's scope true here. Nothing is written: the page stages them for review."""
    from .core.yaml_io import import_changes

    check_edit(user)
    named = []
    scope = doc.get("scope") if isinstance(doc, dict) else None
    if isinstance(scope, dict) and isinstance(scope.get("principals"), list):
        named = [p.get("name") for p in scope["principals"] if isinstance(p, dict) and p.get("type") == USER]
    usernames = [n for n in named if isinstance(n, str)]
    snap = loader.load_snapshot(user_ids=list(User.objects.filter(username__in=usernames).values_list("pk", flat=True)))
    groups, users = visible_groups(user), visible_users(user)
    visible = {r for r in snap.principals if r.id in (groups if r.kind == GROUP else users)}
    changes, warnings, errors = import_changes(snap, doc, {r.object_type for r in loader.rows()}, visible)
    return {
        "changes": [
            {
                "principal": {"type": c.principal.kind, "id": c.principal.id},
                "name": snap.name_of(c.principal),
                "object_type": c.object_type,
                "action": c.action,
                "granted": c.granted,
            }
            for c in changes
        ],
        "warnings": warnings,
        "errors": errors,
    }
