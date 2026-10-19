import dataclasses

from netbox_permissions_matrix_plugin.core.token import version_token

from .factories import NOC, OPS, RO, perm, snapshot

BASE = [
    perm(1, "NOC | view", ["view"], ["dcim.site"], NOC),
    perm(2, "Ops | view", ["view"], ["dcim.site"], OPS),
]


def test_token_is_stable_and_order_independent():
    a = version_token(snapshot(*BASE), [NOC, OPS])
    b = version_token(snapshot(*reversed(BASE)), [OPS, NOC])
    assert a == b
    assert len(a) == 64


def test_token_changes_when_a_permission_of_the_principal_changes():
    changed = dataclasses.replace(BASE[0], object_types=frozenset({"dcim.device"}))
    assert version_token(snapshot(*BASE), [NOC]) != version_token(snapshot(changed, BASE[1]), [NOC])


def test_token_ignores_permissions_of_other_principals_except_names():
    changed = dataclasses.replace(BASE[1], object_types=frozenset({"dcim.device"}))
    assert version_token(snapshot(*BASE), [NOC]) == version_token(snapshot(BASE[0], changed), [NOC])


def test_token_changes_when_a_name_is_taken():
    extra = perm(3, "NOC | change", ["view"], ["dcim.rack"], RO)
    assert version_token(snapshot(*BASE), [NOC]) != version_token(snapshot(*BASE, extra), [NOC])


def test_token_changes_when_a_new_permission_is_assigned_to_the_principal():
    extra = perm(3, "x", ["change"], ["dcim.rack"], NOC)
    assert version_token(snapshot(*BASE), [NOC]) != version_token(snapshot(*BASE, extra), [NOC])
