import copy
import importlib
from unittest import mock

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from netbox.navigation.menu import ADMIN_MENU, get_menus
from netbox.registry import registry

from netbox_permissions_matrix_plugin import navigation
from netbox_permissions_matrix_plugin.conf import get_setting

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


class LoadedMenuTest(SimpleTestCase):
    # The menus NetBox built at start from PLUGINS_CONFIG, as the navigation bar renders them (get_menus). CI runs this
    # module a second time with menu_placement: "admin", so a change in NetBox's Admin menu fails there instead of
    # silently moving the item to the Plugins menu.
    def setUp(self):
        self.menus = {str(menu.label): menu for menu in get_menus()}

    def links(self, label):
        menu = self.menus.get(label)
        return admin_links(menu) if menu else []

    def test_matrix_is_where_menu_placement_puts_it(self):
        if get_setting("menu_placement") == "admin":
            links = admin_links(self.menus["Admin"])
            at = links.index(PERMISSIONS) + 1
            self.assertEqual(links[at : at + 1], [MATRIX], "not right after Permissions in the Admin menu")
            self.assertNotIn(MATRIX, self.links("Plugins"))
            self.assertNotIn(MATRIX, plugin_links())
        else:
            self.assertIn(MATRIX, self.links("Plugins"))
            self.assertIn(MATRIX, plugin_links())
            self.assertNotIn(MATRIX, self.links("Admin"))

    def test_listed_once(self):
        self.assertEqual(sum(self.links(label).count(MATRIX) for label in self.menus), 1)


class AdminSettingTest(SimpleTestCase):
    # What NetBox loads at start: navigation.menu_items, computed from the setting when the module is imported.
    def tearDown(self):
        importlib.reload(navigation)

    def test_admin_setting_moves_the_item_out_of_the_plugins_menu(self):
        menu = copy.deepcopy(ADMIN_MENU)
        config = {**settings.PLUGINS_CONFIG, "netbox_permissions_matrix_plugin": {"menu_placement": "admin"}}
        with override_settings(PLUGINS_CONFIG=config), mock.patch("netbox.navigation.menu.ADMIN_MENU", menu):
            importlib.reload(navigation)
        self.assertEqual(navigation.menu_items, ())
        self.assertEqual(admin_links(menu).count(MATRIX), 1)


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
