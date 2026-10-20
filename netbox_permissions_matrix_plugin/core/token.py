"""A version token for optimistic concurrency between "Review changes" and "Apply"."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from .model import Perm, Plan, PrincipalRef, Snapshot


def _perm_data(perm: Perm) -> dict:
    return {
        "id": perm.id,
        "name": perm.name,
        "description": perm.description,
        "enabled": perm.enabled,
        "actions": list(perm.actions),
        "object_types": sorted(perm.object_types),
        "groups": sorted(perm.groups),
        "users": sorted(perm.users),
        "constraints": perm.constraints,
    }


def version_token(snap: Snapshot, refs: Iterable[PrincipalRef], plan: Plan) -> str:
    """Hash of everything a plan for these principals depends on.

    That is every permission assigned to any of them (also the ones the plan leaves alone: whether a cell is
    already covered, or which permission is the simple one, depends on them), the principals themselves, and the
    names the plan gives. Apply plans again and compares tokens, so other permissions may be created, renamed or
    deleted meanwhile: only a change to the names the plan would give (a name it uses is taken, or one it had to
    avoid is free again) refuses the apply.
    """
    refs = sorted(set(refs))
    data = {
        "perms": [_perm_data(p) for _, p in sorted(snap.perms.items()) if any(p.assigned_to(r) for r in refs)],
        "names": [[op.key, op.after.name] for op in plan.operations if op.after is not None],
        "principals": [[r.key, snap.name_of(r)] for r in refs],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
