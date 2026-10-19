from django.test import SimpleTestCase
from netbox.navigation.menu import ADMIN_MENU
from netbox.registry import registry

from netbox_permissions_matrix_plugin import navigation

MATRIX = "plugins:netbox_permissions_matrix_plugin:matrix"


class MenuTest(SimpleTestCase):
    def test_matrix_follows_permissions_in_admin_authentication(self):
        group = next(g for g in ADMIN_MENU.groups if any(i.link == "users:objectpermission_list" for i in g.items))
        links = [item.link for item in group.items]
        at = links.index("users:objectpermission_list")
        self.assertEqual(links[at + 1], MATRIX)
        item = group.items[at + 1]
        self.assertEqual(item.link_text, "Permissions Matrix")
        self.assertEqual(list(item.permissions), ["users.view_objectpermission"])

    def test_listed_once(self):
        admin_links = [item.link for group in ADMIN_MENU.groups for item in group.items]
        plugin_links = [item.link for items in registry["plugins"]["menu_items"].values() for item in items]
        self.assertEqual((admin_links + plugin_links).count(MATRIX), 1)

    def test_insertion_is_idempotent_and_reports_a_missing_anchor(self):
        self.assertTrue(navigation.add_to_admin_menu())
        admin_links = [item.link for group in ADMIN_MENU.groups for item in group.items]
        self.assertEqual(admin_links.count(MATRIX), 1)

        class Group:
            items = ()

        class Menu:
            groups = (Group(),)

        self.assertFalse(navigation.add_to_admin_menu(Menu()))
