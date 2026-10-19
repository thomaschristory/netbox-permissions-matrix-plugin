"""Read NetBox's permissions, groups, users and object types into the plain data the core works on."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from django.apps import apps
from netbox.registry import registry
from users.constants import OBJECTPERMISSION_OBJECT_TYPES, RESERVED_ACTIONS
from users.models import Group, ObjectPermission, User
from utilities.string import title

from .core.model import GROUP, USER, Perm, Principal, PrincipalRef, Snapshot

# Permissions, their object types, groups and users (prefetches), all groups, users with direct permissions or
# requested columns, and their group memberships. Fixed, whatever the number of permissions.
SNAPSHOT_QUERIES = 7


def ot_label(object_type) -> str:
    return f"{object_type.app_label}.{object_type.model}"


def load_snapshot(user_ids=()) -> Snapshot:
    """Every permission, every group, and the users that have direct permissions (plus user_ids)."""
    perms = {}
    for p in ObjectPermission.objects.prefetch_related("object_types", "groups", "users").order_by("pk"):
        perms[p.pk] = Perm(
            id=p.pk,
            name=p.name,
            description=p.description,
            enabled=p.enabled,
            actions=tuple(p.actions),
            object_types=frozenset(ot_label(ot) for ot in p.object_types.all()),
            groups=frozenset(g.pk for g in p.groups.all()),
            users=frozenset(u.pk for u in p.users.all()),
            constraints=p.constraints,
        )
    principals = {
        PrincipalRef(GROUP, g.pk): Principal(PrincipalRef(GROUP, g.pk), g.name)
        for g in Group.objects.only("pk", "name").order_by("name")
    }
    direct = {uid for p in perms.values() for uid in p.users} | set(user_ids)
    users = list(User.objects.filter(pk__in=direct).only("pk", "username").order_by("username"))
    for u in users:
        principals[PrincipalRef(USER, u.pk)] = Principal(PrincipalRef(USER, u.pk), u.username)
    memberships = defaultdict(set)
    for user_id, group_id in User.groups.through.objects.filter(user_id__in=direct).values_list("user_id", "group_id"):
        memberships[user_id].add(group_id)
    return Snapshot(perms, principals, {uid: frozenset(gids) for uid, gids in memberships.items()})


@dataclass(frozen=True)
class Row:
    object_type: str  # "app_label.model"
    app_label: str
    app_name: str
    label: str
    custom_actions: frozenset[str]


def registered_actions() -> dict[str, frozenset[str]]:
    """Custom actions models registered (NetBox 4.6+), by "app_label.model"."""
    return {label: frozenset(a.name for a in actions) for label, actions in registry["model_actions"].items()}


def rows(hidden_apps=()) -> list[Row]:
    """The object types NetBox offers in the permission form, by app label then model."""
    from core.models import ObjectType

    app_names = {app.label: str(app.verbose_name) for app in apps.get_app_configs()}
    custom = registered_actions()
    result = []
    for ot in ObjectType.objects.filter(OBJECTPERMISSION_OBJECT_TYPES).exclude(app_label__in=hidden_apps):
        model = ot.model_class()
        label = ot_label(ot)
        result.append(
            Row(
                object_type=label,
                app_label=ot.app_label,
                app_name=app_names.get(ot.app_label, ot.app_label),
                label=title(model._meta.verbose_name) if model else ot.model,
                custom_actions=custom.get(label, frozenset()),
            )
        )
    return sorted(result, key=lambda r: (r.app_label, r.object_type))


@dataclass(frozen=True)
class ActionTab:
    name: str
    label: str
    custom: bool = False  # registered by a model: only rows of those models are enabled
    freeform: bool = False  # only found in existing permissions: enabled on every row
    help_text: str = ""


def action_tabs(snap: Snapshot, row_list: list[Row]) -> list[ActionTab]:
    tabs = [ActionTab(a, a.capitalize()) for a in RESERVED_ACTIONS]
    help_texts = {}
    for actions in registry["model_actions"].values():
        for action in actions:
            help_texts.setdefault(action.name, action.help_text)
    registered = sorted(set().union(*(r.custom_actions for r in row_list)) if row_list else set())
    tabs += [ActionTab(a, title(a.replace("_", " ")), custom=True, help_text=help_texts.get(a, "")) for a in registered]
    known = set(RESERVED_ACTIONS) | set(help_texts)
    freeform = sorted({a for p in snap.perms.values() for a in p.actions} - known)
    tabs += [ActionTab(a, a, freeform=True) for a in freeform]
    return tabs


def lock_permissions() -> None:
    """Block other writers to permissions until the current transaction ends (reads still go through)."""
    from django.db import connection

    with connection.cursor() as cursor:
        cursor.execute(f"LOCK TABLE {ObjectPermission._meta.db_table} IN SHARE ROW EXCLUSIVE MODE")
