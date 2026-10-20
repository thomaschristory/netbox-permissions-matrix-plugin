"""Write a plan to NetBox in one transaction, checking the user's own permissions on every object it touches."""

from __future__ import annotations

import logging

from core.models import ObjectType
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from users.models import ObjectPermission

from .core.model import Operation, Perm, Plan

logger = logging.getLogger("netbox_permissions_matrix_plugin")


def _object_types(plan: Plan) -> dict[str, ObjectType]:
    labels = {ot for op in plan.operations if op.after for ot in op.after.object_types}
    found = {}
    for ot in ObjectType.objects.filter(app_label__in={label.split(".")[0] for label in labels}):
        found[f"{ot.app_label}.{ot.model}"] = ot
    missing = labels - set(found)
    if missing:
        raise ValueError(f"Unknown object types: {', '.join(sorted(missing))}")
    return found


def _write(obj: ObjectPermission, perm: Perm, object_types: dict[str, ObjectType]) -> None:
    obj.name = perm.name
    obj.description = perm.description
    obj.enabled = perm.enabled
    obj.actions = list(perm.actions)
    obj.constraints = perm.constraints
    obj.full_clean()
    obj.save()
    obj.object_types.set([object_types[label] for label in perm.object_types])
    obj.groups.set(perm.groups)
    obj.users.set(perm.users)


def _denied(op: Operation, action: str) -> PermissionDenied:
    name = (op.before or op.after).name
    return PermissionDenied(f"You are not allowed to {action} the permission {name!r}; nothing was written.")


def apply_plan(plan: Plan, user) -> list[dict]:
    """Apply every operation or none. Returns what was written: [{"op", "id", "name"}]."""
    object_types = _object_types(plan)
    written = []
    with transaction.atomic():
        for op in plan.operations:
            if op.op == "delete":
                obj = ObjectPermission.objects.restrict(user, "delete").filter(pk=op.perm_id).first()
                if obj is None:
                    raise _denied(op, "delete")
                obj.delete()
                written.append({"op": "delete", "id": op.perm_id, "name": op.before.name})
                continue
            if op.op == "update":
                obj = ObjectPermission.objects.restrict(user, "change").filter(pk=op.perm_id).first()
                if obj is None:
                    raise _denied(op, "change")
                action = "change"
            else:
                obj = ObjectPermission()
                action = "add"
            _write(obj, op.after, object_types)
            # Like NetBox's own edit views: the saved object must still be within what the user may add or change,
            # so a constrained permission cannot be used to write an object outside its constraints.
            if not ObjectPermission.objects.restrict(user, action).filter(pk=obj.pk).exists():
                raise _denied(op, action)
            written.append({"op": op.op, "id": obj.pk, "name": obj.name})
        # Foreign keys are checked at commit. Check them now, so a group or user deleted meanwhile raises
        # IntegrityError here, inside the transaction, rather than after the caller thinks the plan is written.
        connection.check_constraints()
    logger.info(
        "%s applied a permissions matrix plan: %s",
        user.username,
        "; ".join(f"{w['op']} {w['name']!r} (#{w['id']})" for w in written) or "nothing to do",
    )
    return written
