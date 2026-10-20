import dataclasses

from netbox_permissions_matrix_plugin.core.model import CellChange, PermEdit
from netbox_permissions_matrix_plugin.core.planner import plan
from netbox_permissions_matrix_plugin.core.token import version_token

from .factories import NOC, OPS, RO, perm, snapshot

BASE = [
    perm(1, "NOC | view", ["view"], ["dcim.site"], NOC),
    perm(2, "Ops | view", ["view"], ["dcim.site"], OPS),
]
# Grants change on racks to NOC: the plan creates a permission named noc_c.
CHANGES = [CellChange(NOC, "dcim.rack", "change", True)]


def token(*perms, refs=(NOC,), changes=CHANGES, edits=()):
    snap = snapshot(*perms)
    return version_token(snap, refs, plan(snap, changes, edits))


def test_token_is_stable_and_order_independent():
    a = token(*BASE, refs=[NOC, OPS])
    b = token(*reversed(BASE), refs=[OPS, NOC])
    assert a == b
    assert len(a) == 64


def test_token_changes_when_a_permission_of_the_principal_changes():
    changed = dataclasses.replace(BASE[0], object_types=frozenset({"dcim.device"}))
    assert token(*BASE) != token(changed, BASE[1])


def test_token_ignores_permissions_of_other_principals():
    changed = dataclasses.replace(BASE[1], object_types=frozenset({"dcim.device"}))
    assert token(*BASE) == token(BASE[0], changed)


def test_token_ignores_permissions_created_renamed_or_deleted_elsewhere():
    assert token(*BASE) == token(*BASE, perm(3, "RO | change", ["change"], ["dcim.rack"], RO))
    assert token(*BASE) == token(BASE[0], dataclasses.replace(BASE[1], name="Ops can view sites"))
    assert token(*BASE) == token(BASE[0])


def test_token_changes_when_a_name_the_plan_gives_is_taken():
    assert plan(snapshot(*BASE), CHANGES).operations[0].after.name == "noc_c"
    taken = perm(3, "noc_c", ["change"], ["dcim.rack"], RO)
    assert token(*BASE) != token(*BASE, taken)


def test_token_changes_when_a_name_that_was_taken_is_freed():
    # With noc_c taken the plan names the new permission noc_c 2; once noc_c is free again, it would be noc_c.
    taken = perm(3, "noc_c", ["change"], ["dcim.rack"], RO)
    assert token(*BASE, taken) != token(*BASE, dataclasses.replace(taken, name="ro_c"))


def test_token_changes_when_a_name_typed_in_the_gear_panel_is_taken():
    edits = [PermEdit(NOC, "view", perm_id=1, name="NOC sites")]
    clash = perm(3, "NOC sites", ["change"], ["dcim.rack"], RO)
    assert token(*BASE, changes=[], edits=edits) != token(*BASE, clash, changes=[], edits=edits)


def test_token_changes_when_a_new_permission_is_assigned_to_the_principal():
    extra = perm(3, "x", ["change"], ["dcim.rack"], NOC)
    assert token(*BASE) != token(*BASE, extra)
