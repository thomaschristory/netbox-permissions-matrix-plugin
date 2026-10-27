import json
import os

import yaml
from django.core.management import call_command
from django.urls import include, path, reverse
from drf_spectacular.generators import SchemaGenerator
from rest_framework import serializers
from rest_framework.test import APIClient
from users.constants import TOKEN_PREFIX
from users.models import Token
from utilities.testing import TestCase

from netbox_permissions_matrix_plugin.api import serializers as api

from .fixtures import groups, make_perm, user

API = "plugins-api:netbox_permissions_matrix_plugin-api"
VIEW = ("users.view_objectpermission", "users.view_group", "users.view_user")
WRITE = ("users.add_objectpermission", "users.change_objectpermission", "users.delete_objectpermission")
ENDPOINTS = ("matrix", "principal", "plan", "apply", "import")


class APIRootTest(TestCase):
    def test_root_lists_every_endpoint(self):
        data = self.client.get(reverse(f"{API}:api-root")).json()
        self.assertEqual(sorted(data), sorted(ENDPOINTS))
        for name in ENDPOINTS:
            self.assertTrue(data[name].endswith(reverse(f"{API}:{name}")), data[name])

    def test_listed_under_plugins(self):
        data = self.client.get(reverse("plugins-api:api-root")).json()
        self.assertTrue(data["permissions-matrix"].endswith(reverse(f"{API}:api-root")))


class SchemaTest(TestCase):
    def test_every_endpoint_is_documented(self):
        patterns = [path("api/plugins/permissions-matrix/", include("netbox_permissions_matrix_plugin.api.urls"))]
        schema = SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
        operations = {p.rstrip("/").rsplit("/", 1)[-1]: ops for p, ops in schema["paths"].items()}
        self.assertEqual(sorted(operations), sorted(ENDPOINTS))
        for name, ops in operations.items():
            with self.subTest(name=name):
                (method,) = ops
                op = ops[method]
                ok = op["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
                self.assertIn("/PermissionsMatrix", ok)
                if method == "post":
                    body = op["requestBody"]["content"]["application/json"]["schema"]["$ref"]
                    self.assertIn("/PermissionsMatrix", body)

    def test_get_parameters_are_the_ones_the_views_read(self):
        # NetBox's schema class adds fields/omit/brief to every GET; these APIViews do not honour them.
        patterns = [path("api/plugins/permissions-matrix/", include("netbox_permissions_matrix_plugin.api.urls"))]
        schema = SchemaGenerator(patterns=patterns).get_schema(request=None, public=True)
        expected = {
            "matrix": {"action", "include_users", "group_id", "user_id", "app_label"},
            "principal": {"type", "id"},
        }
        for p, ops in schema["paths"].items():
            name = p.rstrip("/").rsplit("/", 1)[-1]
            if name in expected:
                with self.subTest(name=name):
                    self.assertEqual({param["name"] for param in ops["get"]["parameters"]}, expected[name])

    def test_netbox_schema_validates(self):
        # NetBox's whole schema with the plugin loaded, as `manage.py spectacular` builds it. NetBox's viewsets query
        # the database while the schema is generated, hence a test (migrated database) rather than a bare CI command.
        call_command("spectacular", "--validate", "--fail-on-warn", "--file", os.devnull)


def change(group, object_type, action, granted):
    principal = {"type": "group", "id": group.pk}
    return {"principal": principal, "object_type": object_type, "action": action, "granted": granted}


def documented(test, serializer, data, where="body"):
    """Fail when data has a key the serializer does not document, or lacks a required one."""
    fields = serializer.fields
    test.assertLessEqual(set(data), set(fields), f"undocumented keys in {where}")
    for name, field in fields.items():
        if name not in data:
            test.assertFalse(field.required, f"{where}.{name} is missing")
            continue
        value, at = data[name], f"{where}.{name}"
        if value is None:
            test.assertTrue(field.allow_null, f"{at} is null")
        elif isinstance(field, serializers.ListSerializer):
            for i, item in enumerate(value):
                documented(test, field.child, item, f"{at}[{i}]")
        elif isinstance(field, serializers.Serializer):
            documented(test, field, value, at)
        elif isinstance(field, serializers.DictField) and isinstance(field.child, serializers.Serializer):
            for key, item in value.items():
                documented(test, field.child, item, f"{at}[{key}]")


def cells_documented(test, cells, depth):
    """Cells are free-form in the schema (their nesting depends on the endpoint); check the entries at the bottom."""
    if depth:
        for inner in cells.values():
            cells_documented(test, inner, depth - 1)
        return
    test.assertLessEqual(set(cells), {"state", "perms", "inherited"})
    test.assertIn(cells["state"], ("granted", "constrained", "disabled", "none"))
    for perm in cells["perms"]:
        documented(test, api.PermissionSummarySerializer(), perm, "cell.perms")
    if "inherited" in cells:
        test.assertEqual(set(cells["inherited"]), {"state", "groups"})


class ResponsesMatchSchemaTest(TestCase):
    """The response serializers only document the payloads; this keeps them from drifting apart."""

    def setUp(self):
        super().setUp()
        self.add_permissions(*VIEW, *WRITE)
        self.noc, self.ops = groups("NOC", "Ops")
        self.alice = user("alice", self.noc)
        make_perm("NOC-RW", ["view", "change"], ["dcim.device", "dcim.site"], groups=[self.noc, self.ops])
        make_perm("paris", ["change"], ["ipam.prefix"], groups=[self.noc], constraints={"vlan__vid": 10})
        make_perm("alice direct", ["view"], ["dcim.rack"], users=[self.alice])
        self.body = {"changes": [change(self.noc, "dcim.site", "change", False)]}

    def get(self, name, **params):
        response = self.client.get(reverse(f"{API}:{name}"), params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def post(self, name, body):
        response = self.client.post(reverse(f"{API}:{name}"), json.dumps(body), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def test_matrix(self):
        for action, depth in (("change", 2), ("*", 3)):
            with self.subTest(action=action):
                data = self.get("matrix", action=action, include_users="true")
                documented(self, api.MatrixResponseSerializer(), data)
                cells_documented(self, data["cells"], depth)
                self.assertTrue(data["columns"] and data["rows"])
                # alice's column shows what she has through NOC.
                self.assertIn("inherited", json.dumps(data["cells"][f"user:{self.alice.pk}"]))

    def test_principal(self):
        for kind, pk in (("group", self.noc.pk), ("user", self.alice.pk)):
            with self.subTest(kind=kind):
                data = self.get("principal", type=kind, id=pk)
                documented(self, api.PrincipalResponseSerializer(), data)
                cells_documented(self, data["cells"], 2)

    def test_plan_and_apply(self):
        plan = self.post("plan", self.body)
        documented(self, api.PlanResponseSerializer(), plan)
        self.assertTrue(plan["operations"])
        applied = self.post("apply", {**self.body, "token": plan["token"]})
        documented(self, api.ApplyResponseSerializer(), applied)
        self.assertTrue(applied["written"])

    def test_import(self):
        doc = yaml.safe_load(self.client.get(reverse("plugins:netbox_permissions_matrix_plugin:export")).content)
        doc["grants"]["group:Ops"]["view"] = ["dcim.device"]  # revoke dcim.site
        doc["scope"]["principals"].append({"type": "group", "name": "Ghosts"})
        data = self.post("import", {"yaml": yaml.safe_dump(doc)})
        documented(self, api.ImportResponseSerializer(), data)
        self.assertTrue(data["changes"] and data["errors"], data)


class WriteEnabledTest(TestCase):
    def setUp(self):
        super().setUp()
        self.add_permissions(*VIEW, *WRITE)
        (self.noc,) = groups("NOC")
        self.body = {"changes": [change(self.noc, "dcim.site", "view", True)]}

    def token_client(self, write_enabled):
        token = Token.objects.create(user=self.user, write_enabled=write_enabled)
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {TOKEN_PREFIX}{token.key}.{token.token}")
        return client

    def test_write_enabled_token_can_plan(self):
        response = self.token_client(True).post(reverse(f"{API}:plan"), self.body, format="json")
        self.assertEqual(response.status_code, 200, response.content)

    def test_read_only_token_cannot_plan(self):
        response = self.token_client(False).post(reverse(f"{API}:plan"), self.body, format="json")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["detail"], "This API token is not write-enabled.")

    def test_session_can_plan(self):
        # The matrix page uses the session; NetBox's TokenWritePermission alone would refuse it.
        response = self.client.post(reverse(f"{API}:plan"), json.dumps(self.body), content_type="application/json")
        self.assertEqual(response.status_code, 200, response.content)
