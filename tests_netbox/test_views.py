import shutil
import tempfile
from pathlib import Path
from unittest import mock

from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from utilities.testing import TestCase

from netbox_permissions_matrix_plugin import views
from netbox_permissions_matrix_plugin.core.model import HIDDEN_GROUP

from .fixtures import groups, make_perm

MATRIX = "plugins:netbox_permissions_matrix_plugin:matrix"
VIEW = ("users.view_objectpermission", "users.view_group", "users.view_user")


class MatrixPageTest(TestCase):
    def setUp(self):
        super().setUp()
        (self.noc,) = groups("NOC")
        make_perm("NOC-RW", ["view", "change"], ["dcim.device"], groups=[self.noc])

    def test_anonymous_is_sent_to_login(self):
        self.client.logout()
        response = self.client.get(reverse(MATRIX))
        self.assertEqual(response.status_code, 302)
        self.assertIn("login", response["Location"])

    def test_needs_view_permission(self):
        self.assertEqual(self.client.get(reverse(MATRIX)).status_code, 403)

    def test_action_tabs_are_off_by_default(self):
        self.add_permissions(*VIEW)
        html = self.client.get(reverse(MATRIX), {"action": "change"}).content.decode()
        self.assertIn('data-action="*"', html)
        self.assertNotIn("pm-tabs", html)

    @override_settings(PLUGINS_CONFIG={"netbox_permissions_matrix_plugin": {"show_action_tabs": True}})
    def test_action_tabs_when_enabled(self):
        self.add_permissions(*VIEW)
        html = self.client.get(reverse(MATRIX), {"action": "change"}).content.decode()
        self.assertIn('data-action="change"', html)
        self.assertIn("pm-tabs", html)

    def test_read_only_page(self):
        self.add_permissions(*VIEW)
        response = self.client.get(reverse(MATRIX))
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-can-edit="false"', html)
        self.assertIn(reverse("plugins-api:netbox_permissions_matrix_plugin-api:matrix"), html)
        self.assertIn(f"netbox_permissions_matrix_plugin/matrix.js?v={views.asset_version()}", html)
        self.assertIn("Permissions Matrix", html)

    def test_editable_page(self):
        self.add_permissions(*VIEW, "users.change_objectpermission")
        html = self.client.get(reverse(MATRIX)).content.decode()
        self.assertIn('data-can-edit="true"', html)
        self.assertIn(reverse("plugins-api:netbox_permissions_matrix_plugin-api:apply"), html)
        self.assertIn('class="pm-import"', html)
        self.assertIn(reverse("plugins:netbox_permissions_matrix_plugin:export"), html)
        self.assertIn(reverse("plugins-api:netbox_permissions_matrix_plugin-api:import"), html)

    def test_read_only_page_can_export_but_not_import(self):
        self.add_permissions(*VIEW)
        html = self.client.get(reverse(MATRIX)).content.decode()
        self.assertIn("pm-export", html)
        self.assertNotIn('class="pm-import"', html)

    def test_constrained_view_permission_gets_an_explanation(self):
        self.add_permissions(*VIEW)
        from users.models import ObjectPermission

        perm = ObjectPermission.objects.get(name="users.view_objectpermission")
        perm.constraints = {"name": "NOC-RW"}
        perm.save()
        response = self.client.get(reverse(MATRIX))
        self.assertEqual(response.status_code, 403)


class AssetVersionTest(SimpleTestCase):
    def test_changes_with_the_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            static = Path(tmp)
            for name in views.ASSETS:
                shutil.copy(views.STATIC / name, static / name)
            with mock.patch.object(views, "STATIC", static):
                before = views.asset_version()
                self.assertEqual(views.asset_version(), before)
                with open(static / "matrix.js", "a") as f:
                    f.write("\n// changed\n")
                self.assertNotEqual(views.asset_version(), before)
                (static / "matrix.css").unlink()
                self.assertEqual(views.asset_version(), views.__version__)


class WhoCanPageTest(TestCase):
    def setUp(self):
        super().setUp()
        self.add_permissions(*VIEW)
        self.noc, self.ops = groups("NOC", "Ops")
        from .fixtures import user

        self.alice = user("alice", self.noc)
        self.bob = user("bob", self.ops)
        self.dave = user("dave")
        self.root = user("root")
        self.root.is_superuser = True
        self.root.save()
        make_perm("NOC-RW", ["view", "change"], ["ipam.prefix"], groups=[self.noc])
        make_perm("Ops paris", ["view"], ["ipam.prefix"], groups=[self.ops], constraints={"site__slug": "paris"})
        make_perm("dave direct", ["delete"], ["ipam.prefix"], users=[self.dave])
        make_perm("unrelated", ["view"], ["dcim.site"], groups=[self.ops])

    def get(self, ot="ipam.prefix"):
        return self.client.get(reverse("plugins:netbox_permissions_matrix_plugin:who_can", args=[ot]))

    def test_principals_and_effective_users(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        ctx = response.context
        self.assertEqual([p["name"] for p in ctx["principals"]], ["NOC", "Ops", "dave"])
        noc = ctx["principals"][0]
        self.assertEqual(noc["cells"]["change"]["state"], "granted")
        self.assertEqual(ctx["principals"][1]["cells"]["view"]["state"], "constrained")
        effective = {row["username"]: row for row in ctx["effective"]}
        self.assertEqual(set(effective), {"alice", "bob", "dave"})
        self.assertEqual(effective["alice"]["actions"]["change"]["sources"], ["NOC"])
        self.assertEqual(effective["dave"]["actions"]["delete"]["sources"], ["direct"])
        self.assertIn("root", [u.username for u in ctx["superusers"]])

    def test_unknown_object_type_is_404(self):
        self.assertEqual(self.get("dcim.nothing").status_code, 404)
        self.assertEqual(self.get("core.objecttype").status_code, 404)

    def test_superusers_and_users_hidden_without_view_user(self):
        from users.models import ObjectPermission

        ObjectPermission.objects.filter(name="users.view_user").delete()
        ctx = self.get().context
        self.assertEqual(list(ctx["superusers"]), [])
        self.assertEqual(ctx["effective"], [])
        self.assertEqual([p["name"] for p in ctx["principals"]], ["NOC", "Ops"])

    def test_hidden_groups_are_not_named(self):
        from users.models import ObjectPermission

        # The viewer may see NOC but not Ops: bob gets access only through Ops, alice through both.
        ObjectPermission.objects.filter(name="users.view_group").update(constraints={"name": "NOC"})
        self.alice.groups.add(self.ops)
        response = self.get()
        ctx = response.context
        self.assertEqual([p["name"] for p in ctx["principals"]], ["NOC", "dave"])
        effective = {row["username"]: row for row in ctx["effective"]}
        self.assertEqual(set(effective), {"alice", "bob", "dave"})
        self.assertEqual(effective["alice"]["actions"]["view"]["sources"], ["NOC", HIDDEN_GROUP])
        self.assertEqual(effective["bob"]["actions"]["view"]["sources"], [HIDDEN_GROUP])
        self.assertEqual(effective["bob"]["actions"]["view"]["state"], "constrained")
        self.assertTrue(ctx["hidden_groups"])
        self.assertFalse(ctx["hidden_users"])
        html = response.content.decode()
        self.assertNotIn(">Ops<", html)
        self.assertNotIn("Ops,", html)
        self.assertIn("Some groups with permissions are not listed", html)
        self.assertIn("Some access comes through groups you cannot view", html)

    def test_nothing_hidden_says_nothing(self):
        response = self.get()
        self.assertFalse(response.context["hidden_groups"])
        self.assertFalse(response.context["hidden_users"])
        self.assertNotIn("pm-who-hidden", response.content.decode())

    def test_hidden_users_are_mentioned(self):
        from users.models import ObjectPermission

        ObjectPermission.objects.filter(name="users.view_user").update(constraints={"username": "alice"})
        response = self.get()
        ctx = response.context
        self.assertEqual([row["username"] for row in ctx["effective"]], ["alice"])
        self.assertEqual([p["name"] for p in ctx["principals"]], ["NOC", "Ops"])
        self.assertTrue(ctx["hidden_users"])
        self.assertFalse(ctx["hidden_groups"])
        self.assertIn("Users you cannot view are left out", response.content.decode())


class GroupTabTest(TestCase):
    def setUp(self):
        super().setUp()
        (self.noc,) = groups("NOC")

    def url(self):
        return reverse("users:group_permissions_matrix", args=[self.noc.pk])

    def test_tab_renders_for_viewers(self):
        self.add_permissions(*VIEW)
        response = self.client.get(self.url())
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('data-mode="principal"', html)
        self.assertIn(f'data-principal="group:{self.noc.pk}"', html)

    def test_tab_needs_permission_view(self):
        self.add_permissions("users.view_group")
        self.assertEqual(self.client.get(self.url()).status_code, 403)
