PLUGIN_NAME = "netbox_permissions_matrix_plugin"

DEFAULTS = {
    # Name of the simple permissions the plugin creates for new grants. {principal} is the group name or username as a
    # slug, {actions} the action letters (v, a, c, d, r for render_config, s for sync). A number is appended when the
    # name is taken.
    "new_permission_name": "{principal}_{actions}",
    # "plugins" uses the Plugins menu. "admin" puts the menu item below Permissions in Admin > Authentication by
    # editing NetBox's core menu (no plugin API for it), and falls back to the Plugins menu when it cannot.
    "menu_placement": "plugins",
    # Whether the matrix page also offers one tab per action (View, Add, ...) next to the all-actions grid.
    "show_action_tabs": False,
    # Whether user columns are shown when the matrix opens.
    "show_users_by_default": False,
    # App labels whose object types get no row in the matrix (their grants are still kept intact).
    "hidden_apps": [],
}

MENU_PLACEMENTS = ("admin", "plugins")


def get_setting(key):
    from netbox.plugins.utils import get_plugin_config

    return get_plugin_config(PLUGIN_NAME, key, DEFAULTS[key])
