from netbox_permissions_matrix_plugin.core.model import CellChange, PermEdit
from netbox_permissions_matrix_plugin.core.planner import plan

from .factories import ALICE, NOC, OPS, perm, snapshot


def grant(ref, ot, action):
    return CellChange(ref, ot, action, True)


def revoke(ref, ot, action):
    return CellChange(ref, ot, action, False)


def ops_by(result, op):
    return [o for o in result.operations if o.op == op]


# Granting


def test_grant_already_covered_is_a_noop():
    snap = snapshot(perm(1, "shared", ["view", "change"], ["dcim.device"], NOC, OPS))
    assert plan(snap, [grant(NOC, "dcim.device", "view")]).empty


def test_grant_constrained_cell_adds_an_unconstrained_grant():
    snap = snapshot(perm(1, "paris", ["view"], ["dcim.device"], NOC, constraints={"site__slug": "paris"}))
    result = plan(snap, [grant(NOC, "dcim.device", "view")])
    (create,) = ops_by(result, "create")
    assert create.after.object_types == {"dcim.device"}
    assert create.after.constraints is None


def test_grant_grows_the_simple_permission():
    snap = snapshot(perm(1, "NOC | change", ["change"], ["dcim.site"], NOC))
    (update,) = plan(snap, [grant(NOC, "dcim.device", "change")]).operations
    assert update.op == "update"
    assert update.after.object_types == {"dcim.site", "dcim.device"}
    assert update.affects == {NOC}


def test_grant_creates_a_simple_permission_named_from_the_template():
    snap = snapshot()
    (create,) = plan(snap, [grant(NOC, "dcim.device", "change")]).operations
    assert create.op == "create"
    assert create.after.name == "NOC | change"
    assert create.after.actions == ("change",)
    assert create.after.groups == {NOC.id}
    assert create.after.users == frozenset()
    assert create.after.enabled is True


def test_custom_name_template():
    (create,) = plan(
        snapshot(), [grant(ALICE, "dcim.device", "view")], name_template="{action} for {principal}"
    ).operations
    assert create.after.name == "view for alice"
    assert create.after.users == {ALICE.id}


def test_name_clash_appends_a_number():
    snap = snapshot(
        perm(1, "NOC | change", ["change"], ["dcim.site"], NOC, OPS), perm(2, "NOC | change 2", ["view"], [], OPS)
    )
    (create,) = plan(snap, [grant(NOC, "dcim.device", "change")]).operations
    assert create.after.name == "NOC | change 3"


def test_name_clash_with_names_created_in_the_same_plan():
    snap = snapshot(perm(1, "NOC-RW", ["view", "change"], ["dcim.device", "dcim.site", "ipam.prefix"], NOC, OPS))
    result = plan(snap, [revoke(NOC, "dcim.site", "change"), revoke(NOC, "ipam.prefix", "view")])
    names = [o.after.name for o in ops_by(result, "create")]
    assert len(names) == len(set(names)) == 3


def test_grants_for_one_principal_and_action_share_one_permission():
    result = plan(snapshot(), [grant(NOC, "dcim.device", "view"), grant(NOC, "dcim.site", "view")])
    (create,) = result.operations
    assert create.after.object_types == {"dcim.device", "dcim.site"}


def test_grants_for_several_actions_give_one_permission_per_action():
    result = plan(snapshot(), [grant(NOC, "dcim.device", a) for a in ("view", "add", "change")])
    assert sorted(o.after.actions for o in result.operations) == [("add",), ("change",), ("view",)]


def test_user_grant_ignores_group_grants():
    snap = snapshot(perm(1, "NOC view", ["view"], ["dcim.device"], NOC))
    (create,) = plan(snap, [grant(ALICE, "dcim.device", "view")]).operations
    assert create.after.users == {ALICE.id}


def test_grant_into_disabled_simple_permission_warns():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.site"], NOC, enabled=False))
    result = plan(snap, [grant(NOC, "dcim.device", "view")])
    assert result.operations[0].op == "update"
    assert any("disabled" in w for w in result.warnings)


def test_lowest_id_simple_permission_is_used():
    snap = snapshot(perm(7, "b", ["view"], ["dcim.site"], NOC), perm(3, "a", ["view"], ["dcim.rack"], NOC))
    (update,) = plan(snap, [grant(NOC, "dcim.device", "view")]).operations
    assert update.key == "3"


# Revoking


def test_revoke_last_cell_of_an_exclusive_permission_deletes_it():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.device"], NOC))
    (delete,) = plan(snap, [revoke(NOC, "dcim.device", "view")]).operations
    assert delete.op == "delete"
    assert delete.key == "1"


def test_revoke_from_an_exclusive_multi_type_permission_updates_in_place():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.device", "dcim.site"], NOC))
    (update,) = plan(snap, [revoke(NOC, "dcim.device", "view")]).operations
    assert update.op == "update"
    assert update.after.object_types == {"dcim.site"}
    assert update.after.name == "NOC | view"


def test_revoke_not_granted_cell_is_a_noop():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.site"], NOC))
    assert plan(snap, [revoke(NOC, "dcim.device", "view")]).empty


def test_design_example_noc_rw():
    snap = snapshot(perm(1, "NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], NOC, OPS))
    result = plan(snap, [revoke(NOC, "dcim.site", "change")])
    (update,) = ops_by(result, "update")
    assert update.after.groups == {OPS.id}
    assert update.after.object_types == {"dcim.device", "dcim.site"}
    assert update.after.actions == ("view", "change")
    assert update.affects == {NOC}
    creates = {o.after.name: o.after for o in ops_by(result, "create")}
    assert set(creates) == {"NOC-RW (NOC)", "NOC-RW (NOC) 2"}
    assert creates["NOC-RW (NOC)"].object_types == {"dcim.device"}
    assert creates["NOC-RW (NOC)"].actions == ("view", "change")
    assert creates["NOC-RW (NOC) 2"].object_types == {"dcim.site"}
    assert creates["NOC-RW (NOC) 2"].actions == ("view",)
    assert all(p.groups == {NOC.id} and not p.users for p in creates.values())
    assert all(p.description.startswith("Split from NOC-RW.") for p in creates.values())


def test_shared_permission_with_a_user_keeps_the_user():
    snap = snapshot(perm(1, "mixed", ["view"], ["dcim.device"], NOC, ALICE))
    result = plan(snap, [revoke(NOC, "dcim.device", "view")])
    (update,) = result.operations
    assert update.after.users == {ALICE.id}
    assert update.after.groups == frozenset()


def test_revoke_constrained_and_disabled_grants_too():
    snap = snapshot(
        perm(1, "paris", ["view"], ["dcim.device"], NOC, constraints={"site__slug": "paris"}),
        perm(2, "old", ["view"], ["dcim.device"], NOC, enabled=False),
    )
    result = plan(snap, [revoke(NOC, "dcim.device", "view")])
    assert sorted(o.key for o in ops_by(result, "delete")) == ["1", "2"]


def test_split_keeps_types_that_have_no_row():
    snap = snapshot(perm(1, "wide", ["view"], ["dcim.device", "core.objecttype"], NOC, OPS))
    result = plan(snap, [revoke(NOC, "dcim.device", "view")])
    (create,) = ops_by(result, "create")
    assert create.after.object_types == {"core.objecttype"}


def test_split_copies_constraints_list_and_enabled():
    constraints = [{"site__slug": "a"}, {"tenant": "$user"}]
    snap = snapshot(
        perm(
            1,
            "c",
            ["view", "change"],
            ["dcim.device"],
            NOC,
            OPS,
            constraints=constraints,
            enabled=False,
            description="Old",
        )
    )
    result = plan(snap, [revoke(NOC, "dcim.device", "change")])
    (create,) = ops_by(result, "create")
    assert create.after.constraints == constraints
    assert create.after.enabled is False
    assert create.after.description == "Split from c. Old"


def test_exclusive_split_rewrites_in_place_to_the_largest_group():
    snap = snapshot(perm(1, "NOC all", ["view", "change"], ["dcim.device", "dcim.site", "dcim.rack"], NOC))
    result = plan(snap, [revoke(NOC, "dcim.rack", "change")])
    (update,) = ops_by(result, "update")
    assert update.after.object_types == {"dcim.device", "dcim.site"}
    assert update.after.actions == ("view", "change")
    (create,) = ops_by(result, "create")
    assert create.after.object_types == {"dcim.rack"}
    assert create.after.actions == ("view",)


def test_two_principals_revoking_from_the_same_shared_permission():
    snap = snapshot(perm(1, "shared", ["view"], ["dcim.device", "dcim.site"], NOC, OPS))
    result = plan(snap, [revoke(NOC, "dcim.device", "view"), revoke(OPS, "dcim.site", "view")])
    assert ops_by(result, "delete") == [] or ops_by(result, "delete")[0].key == "1"
    final = {o.after.name: o.after for o in result.operations if o.after}
    owners = {(frozenset(p.groups), frozenset(p.object_types)) for p in final.values()}
    assert (frozenset({NOC.id}), frozenset({"dcim.site"})) in owners
    assert (frozenset({OPS.id}), frozenset({"dcim.device"})) in owners


# Change sets


def test_last_change_for_a_cell_wins():
    snap = snapshot()
    assert plan(snap, [grant(NOC, "dcim.device", "view"), revoke(NOC, "dcim.device", "view")]).empty
    (create,) = plan(snap, [revoke(NOC, "dcim.device", "view"), grant(NOC, "dcim.device", "view")]).operations
    assert create.op == "create"


def test_plan_is_deterministic():
    snap = snapshot(perm(1, "NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], NOC, OPS))
    changes = [revoke(NOC, "dcim.site", "change"), grant(OPS, "ipam.prefix", "view"), grant(NOC, "ipam.vlan", "add")]
    assert plan(snap, changes) == plan(snap, list(reversed(changes)))


def test_plan_does_not_mutate_the_snapshot():
    p = perm(1, "NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], NOC, OPS)
    snap = snapshot(p)
    plan(snap, [revoke(NOC, "dcim.site", "change")])
    assert snap.perms == {1: p}


# Gear panel edits


def test_edit_name_description_enabled_of_the_simple_permission():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.site"], NOC))
    edit = PermEdit(NOC, "view", name="NOC readers", description="Read access", enabled=False)
    result = plan(snap, [], [edit])
    (update,) = result.operations
    assert (update.after.name, update.after.description, update.after.enabled) == ("NOC readers", "Read access", False)
    assert result.warnings == []


def test_edit_adding_constraints_warns_no_longer_simple():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.site"], NOC))
    result = plan(snap, [], [PermEdit(NOC, "view", constraints={"status": "active"})])
    assert result.operations[0].after.constraints == {"status": "active"}
    assert any("no longer simple" in w for w in result.warnings)


def test_edit_adding_groups_users_actions():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.site"], NOC))
    edit = PermEdit(NOC, "view", add_actions=("change",), add_groups=(OPS.id,), add_users=(ALICE.id,))
    result = plan(snap, [], [edit])
    after = result.operations[0].after
    assert after.actions == ("view", "change")
    assert after.groups == {NOC.id, OPS.id}
    assert after.users == {ALICE.id}
    assert result.operations[0].affects == {NOC, OPS, ALICE}


def test_edit_applies_to_permission_created_by_grants_in_the_same_plan():
    result = plan(snapshot(), [grant(NOC, "dcim.site", "view")], [PermEdit(NOC, "view", description="New")])
    (create,) = result.operations
    assert create.after.description == "New"


def test_edit_without_a_simple_permission_warns_and_does_nothing():
    result = plan(snapshot(), [], [PermEdit(NOC, "view", description="x")])
    assert result.empty
    assert result.warnings
