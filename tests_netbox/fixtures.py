"""Helpers for the integration tests: groups, users and permissions in a line each."""

from core.models import ObjectType
from users.models import Group, ObjectPermission, User


def object_type(label):
    app_label, model = label.split(".")
    return ObjectType.objects.get(app_label=app_label, model=model)


def make_perm(name, actions, object_types, groups=(), users=(), constraints=None, enabled=True, description=""):
    perm = ObjectPermission.objects.create(
        name=name, actions=list(actions), constraints=constraints, enabled=enabled, description=description
    )
    perm.object_types.set([object_type(label) for label in object_types])
    perm.groups.set(groups)
    perm.users.set(users)
    return perm


def perm_state(perm):
    """A permission as comparable plain data."""
    perm.refresh_from_db()
    return {
        "name": perm.name,
        "actions": list(perm.actions),
        "object_types": sorted(f"{ot.app_label}.{ot.model}" for ot in perm.object_types.all()),
        "groups": sorted(g.name for g in perm.groups.all()),
        "users": sorted(u.username for u in perm.users.all()),
        "constraints": perm.constraints,
        "enabled": perm.enabled,
    }


def groups(*names):
    return [Group.objects.create(name=name) for name in names]


def user(username, *member_of):
    u = User.objects.create_user(username=username)
    u.groups.set(member_of)
    return u
