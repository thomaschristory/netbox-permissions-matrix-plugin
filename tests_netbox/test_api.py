import json

from django.urls import reverse
from users.models import Group, ObjectPermission
from utilities.testing import TestCase

from netbox_permissions_matrix_plugin.core.model import HIDDEN_GROUP

from .fixtures import groups, make_perm, perm_state, user

MATRIX = "plugins-api:netbox_permissions_matrix_plugin-api:matrix"
PLAN = "plugins-api:netbox_permissions_matrix_plugin-api:plan"
APPLY = "plugins-api:netbox_permissions_matrix_plugin-api:apply"

VIEW = ("users.view_objectpermission", "users.view_group", "users.view_user")
WRITE = ("users.add_objectpermission", "users.change_objectpermission", "users.delete_objectpermission")


class APITestBase(TestCase):
    def setUp(self):
        super().setUp()
        self.noc, self.ops = groups("NOC", "Ops")
        self.alice = user("alice", self.noc)
        self.shared = make_perm("NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], groups=[self.noc, self.ops])

    def post(self, name, body):
        return self.client.post(reverse(name), data=json.dumps(body), content_type="application/json")

    def change(self, group, ot, action, granted):
        return {"principal": {"type": "group", "id": group.pk}, "object_type": ot, "action": action, "granted": granted}


class MatrixReadTest(APITestBase):
    def test_anonymous_is_refused(self):
        self.client.logout()
        self.assertIn(self.client.get(reverse(MATRIX)).status_code, (401, 403))

    def test_needs_view_objectpermission(self):
        self.add_permissions("users.view_group")
        self.assertEqual(self.client.get(reverse(MATRIX)).status_code, 403)

    def test_needs_unconstrained_view_of_permissions(self):
        self.add_permissions(*VIEW)
        perm = ObjectPermission.objects.get(name="users.view_objectpermission")
        perm.constraints = {"name": "NOC-RW"}
        perm.save()
        response = self.client.get(reverse(MATRIX))
        self.assertEqual(response.status_code, 403)
        self.assertIn("all permissions", response.json()["detail"])

    def test_matrix_shape(self):
        self.add_permissions(*VIEW)
        response = self.client.get(reverse(MATRIX), {"action": "change"})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["action"], "change")
        self.assertFalse(data["can_edit"])
        self.assertEqual([c["name"] for c in data["columns"]], ["NOC", "Ops"])
        self.assertIn("view", [a["name"] for a in data["actions"]])
        cell = data["cells"][f"group:{self.noc.pk}"]["dcim.device"]
        self.assertEqual(cell["state"], "granted")
        self.assertEqual(cell["perms"][0]["name"], "NOC-RW")
        self.assertNotIn("dcim.rack", data["cells"][f"group:{self.noc.pk}"])

    def test_matrix_with_every_action(self):
        self.add_permissions(*VIEW)
        data = self.client.get(reverse(MATRIX), {"action": "*"}).json()
        self.assertEqual(data["action"], "*")
        noc = f"group:{self.noc.pk}"
        self.assertEqual(data["cells"][noc]["dcim.device"]["change"]["state"], "granted")
        self.assertNotIn("delete", data["cells"][noc]["dcim.device"])
        column = next(c for c in data["columns"] if c["key"] == noc)
        self.assertEqual([p["name"] for p in column["perms"]], ["NOC-RW"])
        row = next(r for r in data["rows"] if r["object_type"] == "dcim.device")
        self.assertIn("view", row["enabled_actions"])

    def test_user_columns_show_inherited_access(self):
        self.add_permissions(*VIEW)
        make_perm("alice direct", ["view"], ["dcim.rack"], users=[self.alice])
        data = self.client.get(reverse(MATRIX), {"action": "view", "include_users": "true"}).json()
        names = [c["name"] for c in data["columns"]]
        self.assertIn("alice", names)
        cells = data["cells"][f"user:{self.alice.pk}"]
        self.assertEqual(cells["dcim.rack"]["state"], "granted")
        self.assertEqual(cells["dcim.device"]["state"], "none")
        self.assertEqual(cells["dcim.device"]["inherited"], {"state": "granted", "groups": ["NOC"]})

    def test_hidden_groups_are_not_named(self):
        # The viewer may see NOC but not Ops. alice is in both; NOC-RW is shared by both.
        self.add_permissions(*VIEW)
        ObjectPermission.objects.filter(name="users.view_group").update(constraints={"name": "NOC"})
        self.alice.groups.add(self.ops)
        make_perm("ops racks", ["view"], ["dcim.rack"], groups=[self.ops])
        make_perm("alice direct", ["view"], ["dcim.site"], users=[self.alice])
        for action in ("view", "*"):
            data = self.client.get(reverse(MATRIX), {"action": action, "include_users": "true"}).json()
            # The test user has direct permissions too, so it has a column.
            self.assertEqual([c["name"] for c in data["columns"]], ["NOC", "alice", self.user.username])
            cells = data["cells"][f"user:{self.alice.pk}"]
            device, rack = cells["dcim.device"], cells["dcim.rack"]
            if action == "*":
                device, rack = device["view"], rack["view"]
            self.assertEqual(device["inherited"], {"state": "granted", "groups": ["NOC", HIDDEN_GROUP]})
            self.assertEqual(rack["inherited"], {"state": "granted", "groups": [HIDDEN_GROUP]})
            self.assertNotIn('"Ops"', json.dumps(data))
        principal = reverse("plugins-api:netbox_permissions_matrix_plugin-api:principal")
        data = self.client.get(principal, {"type": "user", "id": self.alice.pk}).json()
        self.assertEqual(data["cells"]["dcim.rack"]["view"]["inherited"]["groups"], [HIDDEN_GROUP])
        self.assertNotIn('"Ops"', json.dumps(data))
        data = self.client.get(principal, {"type": "group", "id": self.noc.pk}).json()
        names = [p["name"] for p in data["cells"]["dcim.device"]["view"]["perms"][0]["principals"]]
        self.assertEqual(sorted(names), sorted(["NOC", HIDDEN_GROUP]))

    def test_group_filter(self):
        self.add_permissions(*VIEW)
        data = self.client.get(reverse(MATRIX), {"group_id": self.ops.pk}).json()
        self.assertEqual([c["name"] for c in data["columns"]], ["Ops"])


class PlanApplyTest(APITestBase):
    def setUp(self):
        super().setUp()
        self.add_permissions(*VIEW, *WRITE)
        self.before = perm_state(self.shared)

    def plan(self, changes, edits=()):
        return self.post(PLAN, {"changes": changes, "edits": list(edits)})

    def test_plan_is_a_dry_run(self):
        response = self.plan([self.change(self.noc, "dcim.site", "change", False)])
        self.assertEqual(response.status_code, 200, response.content)
        data = response.json()
        self.assertEqual(sorted(o["op"] for o in data["operations"]), ["create", "create", "update"])
        self.assertEqual(len(data["token"]), 64)
        self.assertEqual(perm_state(self.shared), self.before)
        self.assertEqual(ObjectPermission.objects.filter(name__startswith="NOC-RW").count(), 1)

    def test_apply_writes_the_plan(self):
        changes = [self.change(self.noc, "dcim.site", "change", False)]
        token = self.plan(changes).json()["token"]
        response = self.post(APPLY, {"changes": changes, "edits": [], "token": token})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(perm_state(self.shared)["groups"], ["Ops"])
        split = perm_state(ObjectPermission.objects.get(name="NOC-RW (NOC)"))
        self.assertEqual(split["object_types"], ["dcim.device"])
        self.assertEqual(split["actions"], ["view", "change"])
        self.assertEqual(split["groups"], ["NOC"])
        self.assertEqual(perm_state(ObjectPermission.objects.get(name="NOC-RW (NOC) 2"))["actions"], ["view"])

    def test_apply_with_a_stale_token_writes_nothing(self):
        changes = [self.change(self.noc, "dcim.rack", "view", True)]
        token = self.plan(changes).json()["token"]
        make_perm("NOC | view", ["view"], ["dcim.site"], groups=[self.noc])
        response = self.post(APPLY, {"changes": changes, "edits": [], "token": token})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(perm_state(ObjectPermission.objects.get(name="NOC | view"))["object_types"], ["dcim.site"])

    def test_apply_when_a_group_is_deleted_meanwhile_is_a_conflict(self):
        from unittest import mock

        from netbox_permissions_matrix_plugin import service

        ops_id = self.ops.pk
        changes = [self.change(self.ops, "dcim.rack", "view", True)]
        token = self.plan(changes).json()["token"]
        plan_for = service.plan_for

        def plan_then_delete(*args, **kwargs):
            # The group goes after the apply has planned, so the token still matches and the write hits a missing row.
            planned = plan_for(*args, **kwargs)
            Group.objects.filter(pk=ops_id).delete()
            return planned

        with mock.patch.object(service, "plan_for", plan_then_delete):
            response = self.post(APPLY, {"changes": changes, "edits": [], "token": token})
        self.assertEqual(response.status_code, 409, response.content)
        self.assertIn("Reload and review again", response.json()["detail"])
        self.assertTrue(Group.objects.filter(pk=ops_id).exists())
        self.assertEqual(perm_state(self.shared), self.before)
        self.assertFalse(ObjectPermission.objects.filter(name__startswith="Ops").exists())

    def test_apply_without_add_permission_writes_nothing(self):
        ObjectPermission.objects.filter(name="users.add_objectpermission").delete()
        changes = [self.change(self.noc, "dcim.site", "change", False)]
        token = self.plan(changes).json()["token"]
        response = self.post(APPLY, {"changes": changes, "edits": [], "token": token})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(perm_state(self.shared), self.before)
        self.assertFalse(ObjectPermission.objects.filter(name__startswith="NOC-RW (").exists())

    def test_apply_with_constrained_change_permission_is_checked_per_object(self):
        perm = ObjectPermission.objects.get(name="users.change_objectpermission")
        perm.constraints = {"name": "something else"}
        perm.save()
        changes = [self.change(self.noc, "dcim.site", "change", False)]
        token = self.plan(changes).json()["token"]
        self.assertEqual(self.post(APPLY, {"changes": changes, "edits": [], "token": token}).status_code, 403)
        self.assertEqual(perm_state(self.shared), self.before)

    def test_read_only_token_cannot_plan_or_apply(self):
        from rest_framework.test import APIClient
        from users.constants import TOKEN_PREFIX
        from users.models import Token

        token = Token.objects.create(user=self.user, write_enabled=False)
        client = APIClient()
        header = {"HTTP_AUTHORIZATION": f"Bearer {TOKEN_PREFIX}{token.key}.{token.token}"}
        self.assertEqual(client.get(reverse(MATRIX), **header).status_code, 200)
        body = {"changes": [self.change(self.noc, "dcim.site", "change", False)], "token": "0" * 64}
        for name in (PLAN, APPLY):
            with self.subTest(name=name):
                self.assertEqual(client.post(reverse(name), body, format="json", **header).status_code, 403)
        self.assertEqual(perm_state(self.shared), self.before)

    def test_read_only_user_cannot_plan(self):
        for name in WRITE:
            ObjectPermission.objects.filter(name=name).delete()
        self.assertEqual(self.plan([self.change(self.noc, "dcim.site", "view", False)]).status_code, 403)

    def test_invalid_change_sets_are_rejected(self):
        bad = [
            [
                {
                    "principal": {"type": "group", "id": 999999},
                    "object_type": "dcim.site",
                    "action": "view",
                    "granted": True,
                }
            ],
            [self.change(self.noc, "dcim.nothing", "view", True)],
            [self.change(self.noc, "core.objecttype", "view", True)],
            [self.change(self.noc, "dcim.site", "Bad Action!", True)],
            "not a list",
        ]
        for changes in bad:
            with self.subTest(changes=changes):
                self.assertEqual(self.plan(changes).status_code, 400)

    def test_edit_constraints_are_validated(self):
        make_perm("NOC | view", ["view"], ["dcim.site"], groups=[self.noc])
        edit = {"principal": {"type": "group", "id": self.noc.pk}, "action": "view", "constraints": {"nonsense": 1}}
        response = self.plan([], [edit])
        self.assertEqual(response.status_code, 400)
        self.assertIn("constraints", response.json())

    def test_edit_applies(self):
        make_perm("NOC | view", ["view"], ["dcim.site"], groups=[self.noc])
        edit = {"principal": {"type": "group", "id": self.noc.pk}, "action": "view", "description": "Readers"}
        token = self.plan([], [edit]).json()["token"]
        self.assertEqual(self.post(APPLY, {"changes": [], "edits": [edit], "token": token}).status_code, 200)
        self.assertEqual(ObjectPermission.objects.get(name="NOC | view").description, "Readers")

    def test_grant_creates_a_simple_permission(self):
        changes = [self.change(self.ops, "ipam.prefix", "delete", True)]
        token = self.plan(changes).json()["token"]
        self.post(APPLY, {"changes": changes, "edits": [], "token": token})
        created = perm_state(ObjectPermission.objects.get(name="ops_d"))
        self.assertEqual((created["object_types"], created["groups"]), (["ipam.prefix"], ["Ops"]))

    def test_grants_for_several_actions_go_into_one_permission(self):
        changes = [self.change(self.ops, "ipam.prefix", a, True) for a in ("view", "add")]
        token = self.plan(changes).json()["token"]
        self.assertEqual(self.post(APPLY, {"changes": changes, "edits": [], "token": token}).status_code, 200)
        created = ObjectPermission.objects.get(name="ops_va")
        self.assertEqual(created.actions, ["view", "add"])

    def test_edit_by_permission_id_sets_constraints(self):
        target = make_perm("noc_va", ["view", "add"], ["dcim.site"], groups=[self.noc])
        edit = {"principal": {"type": "group", "id": self.noc.pk}, "perm_id": target.pk, "constraints": {"slug": "x"}}
        response = self.plan([], [edit])
        self.assertEqual(response.status_code, 200, response.content)
        self.assertTrue(any("no longer simple" in w for w in response.json()["warnings"]))
        token = response.json()["token"]
        self.assertEqual(self.post(APPLY, {"changes": [], "edits": [edit], "token": token}).status_code, 200)
        target.refresh_from_db()
        self.assertEqual(target.constraints, {"slug": "x"})

    def test_edit_needs_an_action_or_a_permission_id(self):
        edit = {"principal": {"type": "group", "id": self.noc.pk}, "description": "x"}
        self.assertEqual(self.plan([], [edit]).status_code, 400)
        both = {**edit, "action": "view", "perm_id": self.shared.pk}
        self.assertEqual(self.plan([], [both]).status_code, 400)

    def test_edit_of_an_unknown_permission_is_refused(self):
        edit = {"principal": {"type": "group", "id": self.noc.pk}, "perm_id": 999999, "description": "x"}
        response = self.plan([], [edit])
        self.assertEqual(response.status_code, 400)
        self.assertIn("No such permission", str(response.json()))

    def test_edit_of_a_permission_shared_with_hidden_groups_is_refused(self):
        # The editor may see NOC but not Ops; NOC-RW is assigned to both.
        ObjectPermission.objects.filter(name="users.view_group").update(constraints={"name": "NOC"})
        edit = {"principal": {"type": "group", "id": self.noc.pk}, "perm_id": self.shared.pk, "enabled": False}
        response = self.plan([], [edit])
        self.assertEqual(response.status_code, 400)
        self.assertIn("cannot see", str(response.json()))

    def test_plan_does_not_name_hidden_groups(self):
        ObjectPermission.objects.filter(name="users.view_group").update(constraints={"name": "NOC"})
        response = self.plan([self.change(self.noc, "dcim.site", "view", False)])
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertNotIn('"Ops"', json.dumps(data))
        update = next(op for op in data["operations"] if op["id"] == self.shared.pk)
        self.assertIn(HIDDEN_GROUP, [p["name"] for p in update["before"]["principals"]])
        # Apply checks the plan's token against the real permissions, so it still matches.
        changes = [self.change(self.noc, "dcim.site", "view", False)]
        response = self.post(APPLY, {"changes": changes, "edits": [], "token": data["token"]})
        self.assertEqual(response.status_code, 200, response.content)

    def test_edit_of_a_permission_of_someone_else_is_left_out(self):
        other = make_perm("ops_v", ["view"], ["dcim.site"], groups=[self.ops])
        edit = {"principal": {"type": "group", "id": self.noc.pk}, "perm_id": other.pk, "description": "x"}
        data = self.plan([], [edit]).json()
        self.assertEqual(data["operations"], [])
        self.assertTrue(any("not assigned to NOC" in w for w in data["warnings"]))


class PrincipalAPITest(APITestBase):
    def test_cells_by_object_type_and_action(self):
        self.add_permissions(*VIEW)
        url = reverse("plugins-api:netbox_permissions_matrix_plugin-api:principal")
        data = self.client.get(url, {"type": "group", "id": self.noc.pk}).json()
        self.assertEqual(data["principal"]["name"], "NOC")
        self.assertEqual(data["cells"]["dcim.device"]["change"]["state"], "granted")
        self.assertNotIn("delete", data["cells"]["dcim.device"])
        self.assertIn("view", [a["name"] for a in data["actions"]])
        self.assertEqual(self.client.get(url, {"type": "group", "id": 999999}).status_code, 404)
