import json

import yaml
from django.urls import reverse
from users.models import ObjectPermission
from utilities.testing import TestCase

from .fixtures import groups, make_perm, perm_state, user

EXPORT = "plugins:netbox_permissions_matrix_plugin:export"
IMPORT = "plugins-api:netbox_permissions_matrix_plugin-api:import"
PLAN = "plugins-api:netbox_permissions_matrix_plugin-api:plan"

VIEW = ("users.view_objectpermission", "users.view_group", "users.view_user")
WRITE = ("users.add_objectpermission", "users.change_objectpermission", "users.delete_objectpermission")


class ExportImportBase(TestCase):
    def setUp(self):
        super().setUp()
        self.noc, self.ops = groups("NOC", "Ops")
        self.alice = user("alice", self.noc)
        self.shared = make_perm("NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], groups=[self.noc, self.ops])
        self.paris = make_perm("paris", ["change"], ["ipam.prefix"], groups=[self.noc], constraints={"vlan__vid": 10})
        self.direct = make_perm("alice direct", ["view"], ["dcim.rack"], users=[self.alice])

    def export(self, **params):
        response = self.client.get(reverse(EXPORT), params)
        self.assertEqual(response.status_code, 200, response.content)
        return yaml.safe_load(response.content)

    def do_import(self, doc):
        text = doc if isinstance(doc, str) else yaml.safe_dump(doc)
        return self.client.post(reverse(IMPORT), data=json.dumps({"yaml": text}), content_type="application/json")


class ExportTest(ExportImportBase):
    def test_needs_view_permission(self):
        self.assertEqual(self.client.get(reverse(EXPORT)).status_code, 403)

    def test_export_is_a_yaml_attachment(self):
        self.add_permissions(*VIEW)
        response = self.client.get(reverse(EXPORT))
        self.assertEqual(response.status_code, 200)
        self.assertIn("yaml", response["Content-Type"])
        self.assertIn("attachment", response["Content-Disposition"])
        self.assertIn(".yaml", response["Content-Disposition"])

    def test_export_covers_every_action_by_name(self):
        self.add_permissions(*VIEW)
        doc = self.export()
        self.assertEqual(doc["version"], 1)
        self.assertEqual(
            doc["scope"]["principals"], [{"type": "group", "name": "NOC"}, {"type": "group", "name": "Ops"}]
        )
        self.assertTrue({"view", "add", "change", "delete"} <= set(doc["scope"]["actions"]))
        self.assertIn("dcim.device", doc["scope"]["object_types"])
        self.assertEqual(doc["grants"]["group:NOC"]["change"], ["dcim.device", "dcim.site"])
        self.assertEqual(doc["constrained"]["group:NOC"]["change"][0]["constraints"], {"vlan__vid": 10})

    def test_export_honours_columns_app_and_search(self):
        self.add_permissions(*VIEW)
        doc = self.export(group_id=self.ops.pk, app="dcim", q="device")
        self.assertEqual(doc["scope"]["principals"], [{"type": "group", "name": "Ops"}])
        types = doc["scope"]["object_types"]
        self.assertIn("dcim.device", types)
        self.assertIn("dcim.devicetype", types)  # the search matches like the page's search box
        self.assertNotIn("dcim.site", types)
        self.assertFalse([t for t in types if not t.startswith("dcim.")])

    def test_export_includes_users_when_shown(self):
        self.add_permissions(*VIEW)
        doc = self.export(users="1")
        self.assertIn({"type": "user", "name": "alice"}, doc["scope"]["principals"])
        self.assertEqual(doc["grants"]["user:alice"]["view"], ["dcim.rack"])
        only_alice = self.export(user_id=self.alice.pk)
        self.assertEqual(only_alice["scope"]["principals"], [{"type": "user", "name": "alice"}])


class ImportTest(ExportImportBase):
    def setUp(self):
        super().setUp()
        self.add_permissions(*VIEW, *WRITE)

    def test_round_trip_changes_nothing(self):
        doc = self.export(users="1")
        response = self.do_import(doc)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(response.json(), {"changes": [], "warnings": [], "errors": []})

    def test_import_stages_grants_and_revokes_within_scope(self):
        doc = self.export(app="dcim")
        doc["grants"]["group:Ops"]["view"] = ["dcim.device"]  # revoke dcim.site
        doc["grants"]["group:Ops"].setdefault("delete", []).append("dcim.rack")  # grant
        data = self.do_import(doc).json()
        changes = {
            (c["principal"]["type"], c["name"], c["object_type"], c["action"], c["granted"]) for c in data["changes"]
        }
        self.assertEqual(
            changes,
            {("group", "Ops", "dcim.site", "view", False), ("group", "Ops", "dcim.rack", "delete", True)},
        )
        self.assertEqual(data["changes"][0]["principal"]["id"], self.ops.pk)
        # IPAM was outside the scope: NOC's constrained prefix permission is left alone.
        self.assertFalse(any(c["object_type"].startswith("ipam.") for c in data["changes"]))
        # Nothing is written by an import: it only stages.
        self.assertEqual(perm_state(self.shared)["groups"], ["NOC", "Ops"])

    def test_import_changes_plan_cleanly(self):
        doc = self.export(app="dcim")
        doc["grants"]["group:Ops"]["view"] = ["dcim.device"]
        changes = self.do_import(doc).json()["changes"]
        body = {"changes": [{k: c[k] for k in ("principal", "object_type", "action", "granted")} for c in changes]}
        response = self.client.post(reverse(PLAN), data=json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)

    def test_import_loads_users_named_in_the_file(self):
        bob = user("bob")
        doc = self.export(user_id=self.alice.pk)
        doc["scope"]["principals"].append({"type": "user", "name": "bob"})
        doc["grants"]["user:bob"] = {"view": ["dcim.site"]}
        data = self.do_import(doc).json()
        self.assertEqual(data["errors"], [])
        self.assertIn(
            {
                "principal": {"type": "user", "id": bob.pk},
                "name": "bob",
                "object_type": "dcim.site",
                "action": "view",
                "granted": True,
            },
            data["changes"],
        )

    def test_unknown_principals_and_object_types_are_errors(self):
        doc = self.export(app="dcim")
        doc["scope"]["principals"].append({"type": "group", "name": "Ghosts"})
        doc["scope"]["object_types"].append("nosuch.thing")
        data = self.do_import(doc).json()
        self.assertTrue(any("Ghosts" in e for e in data["errors"]))
        self.assertTrue(any("nosuch.thing" in e for e in data["errors"]))

    def test_groups_the_user_may_not_see_are_unknown(self):
        ObjectPermission.objects.filter(name="users.view_group").update(constraints={"name": "NOC"})
        # This user cannot export (the matrix needs every group), so the file is written by hand.
        doc = {
            "version": 1,
            "scope": {
                "principals": [{"type": "group", "name": "Ops"}],
                "actions": ["view"],
                "object_types": ["dcim.site"],
            },
            "grants": {},
        }
        data = self.do_import(doc).json()
        self.assertEqual(data["changes"], [])
        self.assertTrue(any("Ops" in e for e in data["errors"]))

    def test_constrained_only_in_file_is_a_warning(self):
        doc = self.export(app="ipam")
        doc["constrained"]["group:Ops"] = {
            "change": [{"object_type": "ipam.prefix", "permission": "x", "constraints": {}}]
        }
        data = self.do_import(doc).json()
        self.assertEqual(data["changes"], [])
        self.assertEqual(len(data["warnings"]), 1)

    def test_invalid_yaml_is_rejected(self):
        for text in ("{not: [valid", "just a string", ""):
            with self.subTest(text=text):
                response = self.do_import(text)
                self.assertEqual(response.status_code, 400 if text != "just a string" else 200)
        self.assertEqual(self.client.post(reverse(IMPORT), data="{}", content_type="application/json").status_code, 400)

    def test_needs_write_rights(self):
        for name in WRITE:
            ObjectPermission.objects.filter(name=name).delete()
        self.assertEqual(self.do_import({"version": 1}).status_code, 403)

    def test_read_only_token_cannot_import(self):
        from rest_framework.test import APIClient
        from users.constants import TOKEN_PREFIX
        from users.models import Token

        token = Token.objects.create(user=self.user, write_enabled=False)
        header = {"HTTP_AUTHORIZATION": f"Bearer {TOKEN_PREFIX}{token.key}.{token.token}"}
        response = APIClient().post(reverse(IMPORT), {"yaml": "version: 1"}, format="json", **header)
        self.assertEqual(response.status_code, 403)
