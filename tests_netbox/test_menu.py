import copy

from django.test import SimpleTestCase
from netbox.navigation.menu import ADMIN_MENU
from netbox.registry import registry

from netbox_permissions_matrix_plugin import navigation

MATRIX = "plugins:netbox_permissions_matrix_plugin:matrix"
PERMISSIONS = "users:objectpermission_list"


def admin_links(menu):
    return [item.link for group in menu.groups for item in group.items]


def plugin_links():
    return [item.link for items in registry["plugins"]["menu_items"].values() for item in items]


class BrokenMenu:
    class Group:
        items = ()

    groups = (Group(),)


class DefaultMenuTest(SimpleTestCase):
    def test_matrix_is_in_the_plugins_menu(self):
        self.assertIn(MATRIX, plugin_links())
        self.assertNotIn(MATRIX, admin_links(ADMIN_MENU))

    def test_listed_once(self):
        self.assertEqual((admin_links(ADMIN_MENU) + plugin_links()).count(MATRIX), 1)

    def test_plugins_placement_leaves_the_admin_menu_alone(self):
        menu = copy.deepcopy(ADMIN_MENU)
        before = admin_links(menu)
        (item,) = navigation.build_menu_items("plugins", menu)
        self.assertEqual(item.link, MATRIX)
        self.assertEqual(admin_links(menu), before)


class AdminPlacementTest(SimpleTestCase):
    # Runs on a copy of NetBox's real Admin menu, so it also fails when that menu changes shape.
    def setUp(self):
        self.menu = copy.deepcopy(ADMIN_MENU)

    def test_matrix_follows_permissions_in_admin_authentication(self):
        self.assertEqual(navigation.build_menu_items("admin", self.menu), ())
        group = next(g for g in self.menu.groups if any(i.link == PERMISSIONS for i in g.items))
        links = [item.link for item in group.items]
        item = group.items[links.index(PERMISSIONS) + 1]
        self.assertEqual(item.link, MATRIX)
        self.assertEqual(item.link_text, "Permissions Matrix")
        self.assertEqual(list(item.permissions), ["users.view_objectpermission"])

    def test_insertion_is_idempotent(self):
        self.assertTrue(navigation.add_to_admin_menu(self.menu))
        self.assertTrue(navigation.add_to_admin_menu(self.menu))
        self.assertEqual(admin_links(self.menu).count(MATRIX), 1)

    def test_missing_anchor_falls_back_to_the_plugins_menu_with_a_warning(self):
        with self.assertLogs("netbox_permissions_matrix_plugin", "WARNING") as logs:
            (item,) = navigation.build_menu_items("admin", BrokenMenu())
        self.assertEqual(item.link, MATRIX)
        self.assertIn("Could not find Permissions in the Admin menu", logs.output[0])
