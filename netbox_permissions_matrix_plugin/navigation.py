import logging

from django.utils.translation import gettext_lazy as _
from netbox.plugins import PluginMenuItem

from .conf import get_setting

LINK = "plugins:netbox_permissions_matrix_plugin:matrix"
LABEL = _("Permissions Matrix")
PERMISSIONS = ["users.view_objectpermission"]
ANCHOR = "users:objectpermission_list"

logger = logging.getLogger("netbox_permissions_matrix_plugin")


def add_to_admin_menu(menu=None) -> bool:
    """Insert the matrix right after "Permissions" in NetBox's Admin menu.

    Plugins have no API for core menus, so this edits ADMIN_MENU (plain dataclasses in NetBox 4.7), before NetBox
    builds and caches its menus on the first request. Returns False when the menu looks different, and the caller
    falls back to the Plugins menu.
    """
    try:
        from netbox.navigation import MenuItem
        from netbox.navigation.menu import ADMIN_MENU
    except ImportError:
        return False
    menu = ADMIN_MENU if menu is None else menu
    groups = getattr(menu, "groups", ())
    if any(getattr(item, "link", None) == LINK for group in groups for item in group.items):
        return True
    for group in groups:
        links = [getattr(item, "link", None) for item in group.items]
        if ANCHOR in links:
            at = links.index(ANCHOR) + 1
            entry = MenuItem(link=LINK, link_text=LABEL, permissions=PERMISSIONS)
            group.items = (*group.items[:at], entry, *group.items[at:])
            return True
    return False


def build_menu_items(placement, menu=None) -> tuple:
    """The plugin's Plugins-menu items: none when the item went into the Admin menu instead."""
    if placement == "admin":
        if add_to_admin_menu(menu):
            return ()
        logger.warning(
            "Could not find Permissions in the Admin menu; Permissions Matrix is in the Plugins menu instead."
        )
    return (PluginMenuItem(link=LINK, link_text=LABEL, permissions=PERMISSIONS),)


menu_items = build_menu_items(get_setting("menu_placement"))
