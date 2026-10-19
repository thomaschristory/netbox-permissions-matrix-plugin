"""A version token for optimistic concurrency between "Review changes" and "Apply"."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

from .model import Perm, PrincipalRef, Snapshot


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


def version_token(snap: Snapshot, refs: Iterable[PrincipalRef]) -> str:
    """Hash of everything a plan for these principals depends on.

    That is every permission assigned to any of them (also the ones the plan leaves alone: whether a cell is
    already covered, or which permission is the simple one, depends on them), every permission name (for name
    clashes), and the principals themselves.
    """
    refs = sorted(set(refs))
    data = {
        "perms": [_perm_data(p) for _, p in sorted(snap.perms.items()) if any(p.assigned_to(r) for r in refs)],
        "names": sorted(p.name for p in snap.perms.values()),
        "principals": [[r.key, snap.name_of(r)] for r in refs],
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True, default=str).encode()).hexdigest()
