import pytest

from netbox_permissions_matrix_plugin.core.model import CellChange, PermEdit
from netbox_permissions_matrix_plugin.core.planner import action_letters, canonical, check_name_template, plan, slug

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
    assert create.after.name == "noc_c"
    assert create.after.actions == ("change",)
    assert create.after.groups == {NOC.id}
    assert create.after.users == frozenset()
    assert create.after.enabled is True


def test_custom_name_template():
    (create,) = plan(
        snapshot(), [grant(ALICE, "dcim.device", "view")], name_template="{actions} for {principal}"
    ).operations
    assert create.after.name == "v for alice"
    assert create.after.users == {ALICE.id}


@pytest.mark.parametrize(
    "template",
    ["{principal}_{actions}", "{actions} for {principal}", "{principal} | {action}", "fixed", "{{x}}_{principal}"],
)
def test_valid_name_templates_pass(template):
    check_name_template(template)


@pytest.mark.parametrize(
    ("template", "message"),
    [
        ("{principal}_{team}", "unknown placeholder {team}"),
        ("{team.name}_{actions}", "unknown placeholder {team}"),
        ("{team[0]}", "unknown placeholder {team}"),
        ("{principal}_{}", "positional placeholder"),
        ("{principal}_{0}", "positional placeholder"),
        ("{principal", "expected '}'"),
        ("{principal:d}", "Unknown format code"),
        ("{principal.nope}", "{principal.nope} is not supported"),
        ("{principal[2]}", "{principal[2]} is not supported"),
        ("{actions[0]}_{principal}", "{actions[0]} is not supported"),
        ("{principal.upper}", "{principal.upper} is not supported"),
        ("", "empty"),
        (None, "must be a string"),
    ],
)
def test_invalid_name_templates_are_rejected(template, message):
    with pytest.raises(ValueError, match="new_permission_name") as excinfo:
        check_name_template(template)
    assert message in str(excinfo.value)


def test_name_clash_appends_a_number():
    snap = snapshot(perm(1, "noc_c", ["change"], ["dcim.site"], NOC, OPS), perm(2, "noc_c 2", ["view"], [], OPS))
    (create,) = plan(snap, [grant(NOC, "dcim.device", "change")]).operations
    assert create.after.name == "noc_c 3"


def test_name_clash_with_names_created_in_the_same_plan():
    snap = snapshot(perm(1, "NOC-RW", ["view", "change"], ["dcim.device", "dcim.site", "ipam.prefix"], NOC, OPS))
    result = plan(snap, [revoke(NOC, "dcim.site", "change"), revoke(NOC, "ipam.prefix", "view")])
    names = [o.after.name for o in ops_by(result, "create")]
    assert len(names) == len(set(names)) == 3


def test_grants_for_one_principal_and_action_share_one_permission():
    result = plan(snapshot(), [grant(NOC, "dcim.device", "view"), grant(NOC, "dcim.site", "view")])
    (create,) = result.operations
    assert create.after.object_types == {"dcim.device", "dcim.site"}


def test_grants_for_several_actions_give_one_permission_for_the_set():
    result = plan(snapshot(), [grant(NOC, "dcim.device", a) for a in ("change", "view", "add")])
    (create,) = result.operations
    assert (create.after.name, create.after.actions) == ("noc_vac", ("view", "add", "change"))


def test_object_types_with_the_same_actions_share_a_permission():
    changes = [grant(NOC, ot, a) for ot in ("dcim.device", "dcim.site") for a in ("view", "add")]
    changes += [grant(NOC, "ipam.prefix", "view")]
    result = plan(snapshot(), changes)
    assert {o.after.name: o.after.object_types for o in result.operations} == {
        "noc_va": {"dcim.device", "dcim.site"},
        "noc_v": {"ipam.prefix"},
    }


def test_grant_moves_the_object_type_to_the_larger_action_set():
    snap = snapshot(perm(1, "noc_va", ["view", "add"], ["dcim.device", "dcim.site"], NOC))
    update, create = plan(snap, [grant(NOC, "dcim.device", "change")]).operations
    assert (update.op, update.key, update.after.object_types) == ("update", "1", {"dcim.site"})
    assert (create.op, create.after.name, create.after.object_types) == ("create", "noc_vac", {"dcim.device"})


def test_grant_into_an_existing_set_permission():
    snap = snapshot(
        perm(1, "noc_v", ["view"], ["dcim.device"], NOC), perm(2, "noc_va", ["add", "view"], ["dcim.site"], NOC)
    )
    ops = plan(snap, [grant(NOC, "dcim.device", "add")]).operations
    assert [(o.op, o.key) for o in ops] == [("delete", "1"), ("update", "2")]
    assert ops[1].after.object_types == {"dcim.device", "dcim.site"}


def test_grant_on_every_object_type_renames_the_permission_in_place():
    snap = snapshot(perm(1, "noc_va", ["view", "add"], ["dcim.device", "dcim.site"], NOC, description="kept"))
    (update,) = plan(snap, [grant(NOC, ot, "change") for ot in ("dcim.device", "dcim.site")]).operations
    assert (update.op, update.key, update.after.name) == ("update", "1", "noc_vac")
    assert update.after.actions == ("view", "add", "change")
    assert update.after.object_types == {"dcim.device", "dcim.site"}
    assert update.after.description == "kept"


def test_a_name_set_by_hand_is_kept_when_the_actions_change():
    snap = snapshot(perm(1, "NOC engineers", ["view"], ["dcim.device"], NOC))
    (update,) = plan(snap, [grant(NOC, "dcim.device", "change")]).operations
    assert (update.key, update.after.name, update.after.actions) == ("1", "NOC engineers", ("view", "change"))


def test_action_letters_and_order():
    assert canonical(["sync", "delete", "view", "render_config", "add"]) == (
        "view",
        "add",
        "delete",
        "render_config",
        "sync",
    )
    assert action_letters(["sync", "render_config", "change", "view", "add", "delete"]) == "vacdrs"
    assert action_letters(["view", "run"]) == "vr"
    assert slug("NOC Paris (L2)") == "noc_paris_l2"
    assert slug("!!!") == "principal"


def test_user_grant_ignores_group_grants():
    snap = snapshot(perm(1, "NOC view", ["view"], ["dcim.device"], NOC))
    (create,) = plan(snap, [grant(ALICE, "dcim.device", "view")]).operations
    assert create.after.users == {ALICE.id}


def test_grant_leaves_a_disabled_permission_alone():
    snap = snapshot(perm(1, "noc_v", ["view"], ["dcim.site"], NOC, enabled=False))
    (create,) = plan(snap, [grant(NOC, "dcim.device", "view")]).operations
    assert (create.op, create.after.name, create.after.enabled) == ("create", "noc_v 2", True)


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


def test_moving_the_only_cell_of_a_simple_permission_keeps_the_permission():
    # Revoke site and grant rack in one change set: the same permission, a different object type. Deleting it and
    # creating "NOC | view 2" would lose its ID and anything set on it in the gear panel.
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.site"], NOC, description="kept"))
    (update,) = plan(snap, [revoke(NOC, "dcim.site", "view"), grant(NOC, "dcim.rack", "view")]).operations
    assert update.op == "update" and update.key == "1"
    assert update.after.object_types == {"dcim.rack"}
    assert (update.after.name, update.after.description) == ("NOC | view", "kept")


def test_emptied_permission_is_still_deleted_when_nothing_reuses_it():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.site"], NOC))
    ops = plan(snap, [revoke(NOC, "dcim.site", "view"), grant(NOC, "dcim.rack", "change")]).operations
    assert [(o.op, o.key) for o in ops] == [("delete", "1"), ("create", "new-1")]
    assert any("nothing left" in r.lower() for r in ops[0].reasons)


def test_edit_of_an_emptied_permission_warns():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.site"], NOC))
    result = plan(snap, [revoke(NOC, "dcim.site", "view")], [PermEdit(NOC, "view", description="x")])
    assert [o.op for o in result.operations] == ["delete"]
    assert any("tick a cell first" in w for w in result.warnings)


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


# Action sets on revoke


def test_revoke_moves_the_object_type_to_the_smaller_action_set():
    snap = snapshot(perm(1, "noc_va", ["view", "add"], ["dcim.device", "dcim.site"], NOC))
    update, create = plan(snap, [revoke(NOC, "dcim.device", "add")]).operations
    assert (update.key, update.after.name, update.after.object_types) == ("1", "noc_va", {"dcim.site"})
    assert (create.after.name, create.after.actions, create.after.object_types) == (
        "noc_v",
        ("view",),
        {"dcim.device"},
    )


def test_revoke_on_every_object_type_renames_the_permission_in_place():
    snap = snapshot(perm(1, "noc_va", ["view", "add"], ["dcim.device", "dcim.site"], NOC))
    (update,) = plan(snap, [revoke(NOC, ot, "add") for ot in ("dcim.device", "dcim.site")]).operations
    assert (update.op, update.key, update.after.name, update.after.actions) == ("update", "1", "noc_v", ("view",))
    assert update.after.object_types == {"dcim.device", "dcim.site"}


def test_revoke_joins_an_existing_set_permission():
    snap = snapshot(
        perm(1, "noc_va", ["view", "add"], ["dcim.device"], NOC), perm(2, "noc_v", ["view"], ["dcim.site"], NOC)
    )
    ops = plan(snap, [revoke(NOC, "dcim.device", "add")]).operations
    assert [(o.op, o.key) for o in ops] == [("delete", "1"), ("update", "2")]
    assert ops[1].after.object_types == {"dcim.device", "dcim.site"}


# Edits by permission ID


def test_edit_by_id_sets_constraints_and_warns():
    snap = snapshot(perm(4, "noc_va", ["view", "add"], ["dcim.device"], NOC))
    result = plan(snap, [], [PermEdit(NOC, perm_id=4, constraints={"tenant__slug": "acme"})])
    (update,) = result.operations
    assert (update.key, update.after.constraints) == ("4", {"tenant__slug": "acme"})
    assert any("no longer simple" in w for w in result.warnings)


def test_edit_by_id_removes_constraints():
    snap = snapshot(perm(4, "paris", ["view"], ["dcim.device"], NOC, constraints={"site__slug": "paris"}))
    (update,) = plan(snap, [], [PermEdit(NOC, perm_id=4, constraints=None)]).operations
    assert update.after.constraints is None


def test_edit_by_id_of_a_shared_permission_is_allowed():
    snap = snapshot(perm(4, "shared", ["view"], ["dcim.device"], NOC, OPS))
    (update,) = plan(snap, [], [PermEdit(NOC, perm_id=4, enabled=False)]).operations
    assert update.affects == {NOC, OPS}


def test_edit_by_id_of_someone_elses_permission_is_left_out():
    snap = snapshot(perm(4, "ops_v", ["view"], ["dcim.device"], OPS))
    result = plan(snap, [], [PermEdit(NOC, perm_id=4, description="x")])
    assert result.empty
    assert any("not assigned to NOC" in w for w in result.warnings)


# Emptied permissions that must not take over a grant


def test_emptied_constrained_permission_does_not_take_over_a_grant():
    snap = snapshot(perm(5, "noc-paris", ["view"], ["dcim.device"], NOC, constraints={"name__startswith": "p"}))
    ops = plan(snap, [revoke(NOC, "dcim.device", "view"), grant(NOC, "dcim.site", "view")]).operations
    assert [(o.op, o.key) for o in ops] == [("delete", "5"), ("create", "new-1")]
    assert ops[1].after.constraints is None
    assert ops[1].after.object_types == {"dcim.site"}


def test_emptied_disabled_permission_does_not_take_over_a_grant():
    snap = snapshot(perm(5, "noc_v", ["view"], ["dcim.device"], NOC, enabled=False))
    ops = plan(snap, [revoke(NOC, "dcim.device", "view"), grant(NOC, "dcim.site", "view")]).operations
    assert [o.op for o in ops] == ["delete", "create"]
    assert ops[1].after.enabled is True


def test_a_name_from_0_1_0_is_renamed_when_the_actions_change():
    snap = snapshot(perm(1, "NOC | view", ["view"], ["dcim.device"], NOC))
    (update,) = plan(snap, [grant(NOC, "dcim.device", "add")]).operations
    assert (update.key, update.after.name, update.after.actions) == ("1", "noc_va", ("view", "add"))


def test_disabling_a_simple_permission_warns():
    snap = snapshot(perm(4, "noc_va", ["view", "add"], ["dcim.device"], NOC))
    result = plan(snap, [], [PermEdit(NOC, perm_id=4, enabled=False)])
    assert any(w.startswith("Once disabled, noc_va is no longer simple") for w in result.warnings)


def test_a_name_typed_in_the_panel_is_kept_even_if_it_looks_generated():
    snap = snapshot(perm(5, "custom", ["view"], ["dcim.device"], NOC))
    result = plan(snap, [grant(NOC, "dcim.device", "add")], [PermEdit(NOC, perm_id=5, name="noc_v")])
    (update,) = result.operations
    assert (update.key, update.after.name, update.after.actions) == ("5", "noc_v", ("view", "add"))


def test_renaming_to_a_name_in_use_warns_with_the_name_used():
    snap = snapshot(perm(1, "noc_v", ["view"], ["dcim.site"], NOC), perm(2, "NOC | view", ["view"], [], OPS))
    result = plan(snap, [], [PermEdit(NOC, perm_id=1, name="NOC | view")])
    (update,) = result.operations
    assert update.after.name == "NOC | view 2"
    assert result.warnings == ["The name NOC | view is already taken: noc_v will be renamed NOC | view 2 instead."]


def test_renaming_to_a_free_name_does_not_warn():
    snap = snapshot(perm(1, "noc_v", ["view"], ["dcim.site"], NOC))
    result = plan(snap, [], [PermEdit(NOC, perm_id=1, name="NOC readers")])
    assert result.warnings == []


# A permission the change set deletes frees its name for the permissions the same change set creates


def test_an_emptied_constrained_permission_releases_its_name():
    snap = snapshot(perm(5, "noc_v", ["view"], ["dcim.device"], NOC, constraints={"name__startswith": "p"}))
    ops = plan(snap, [revoke(NOC, "dcim.device", "view"), grant(NOC, "dcim.site", "view")]).operations
    assert [(o.op, o.key) for o in ops] == [("delete", "5"), ("create", "new-1")]
    assert ops[1].after.name == "noc_v"


def test_an_emptied_disabled_permission_releases_its_name():
    snap = snapshot(perm(5, "noc_v", ["view"], ["dcim.device"], NOC, enabled=False))
    ops = plan(snap, [revoke(NOC, "dcim.device", "view"), grant(NOC, "dcim.site", "view")]).operations
    assert [o.op for o in ops] == ["delete", "create"]
    assert ops[1].after.name == "noc_v"


def test_an_emptied_simple_permission_releases_its_name():
    # Named by hand, with actions that neither contain nor are contained in the new ones: it is deleted, not reused.
    snap = snapshot(perm(5, "noc_c", ["view", "add"], ["dcim.device"], NOC))
    changes = [revoke(NOC, "dcim.device", "view"), revoke(NOC, "dcim.device", "add"), grant(NOC, "dcim.site", "change")]
    ops = plan(snap, changes).operations
    assert [(o.op, o.key) for o in ops] == [("delete", "5"), ("create", "new-1")]
    assert ops[1].after.name == "noc_c"


def test_a_released_name_typed_in_the_panel_is_kept_without_a_number():
    snap = snapshot(
        perm(5, "noc_v", ["view"], ["dcim.device"], NOC, enabled=False),
        perm(6, "custom", ["change"], ["dcim.site"], NOC),
    )
    result = plan(snap, [revoke(NOC, "dcim.device", "view")], [PermEdit(NOC, perm_id=6, name="noc_v")])
    assert [(o.op, o.key, o.after and o.after.name) for o in result.operations] == [
        ("delete", "5", None),
        ("update", "6", "noc_v"),
    ]


def test_a_name_another_kept_permission_has_is_not_released():
    snap = snapshot(
        perm(5, "noc_v", ["view"], ["dcim.device"], NOC, enabled=False),
        perm(6, "noc_v", ["view"], ["dcim.rack"], OPS),
    )
    ops = plan(snap, [revoke(NOC, "dcim.device", "view"), grant(NOC, "dcim.site", "view")]).operations
    assert [o.op for o in ops] == ["delete", "create"]
    assert ops[1].after.name == "noc_v 2"


def test_a_split_emptied_in_the_same_change_set_releases_its_name():
    # The revokes split "shared (NOC)" (change on device and rack) and "shared (NOC) 2" (add on site) off for NOC; the
    # view grants then move device and rack to noc_vc, so the first split is dropped and its name is free.
    snap = snapshot(
        perm(1, "shared", ["add", "change"], ["dcim.device", "dcim.rack", "dcim.site"], NOC, OPS),
        perm(2, "noc_vc", ["view", "change"], ["ipam.prefix"], NOC),
    )
    changes = [
        revoke(NOC, "dcim.device", "add"),
        revoke(NOC, "dcim.rack", "add"),
        revoke(NOC, "dcim.site", "change"),
        grant(NOC, "dcim.device", "view"),
        grant(NOC, "dcim.rack", "view"),
    ]
    ops = plan(snap, changes).operations
    assert [(o.op, o.key) for o in ops] == [("update", "1"), ("update", "2"), ("create", "new-2")]
    assert (ops[2].after.name, ops[2].after.actions) == ("shared (NOC)", ("add",))
