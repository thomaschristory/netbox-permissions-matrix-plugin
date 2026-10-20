# Configuration

The plugin works without any settings. To change the defaults, add a `netbox_permissions_matrix_plugin` entry to
`PLUGINS_CONFIG` in NetBox's `configuration.py` (or `plugins.py` with netbox-docker) and restart NetBox.

```python
PLUGINS_CONFIG = {
    "netbox_permissions_matrix_plugin": {
        "new_permission_name": "{principal}_{actions}",
        "menu_placement": "admin",
        "show_action_tabs": False,
        "show_users_by_default": False,
        "hidden_apps": [],
    },
}
```

## Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| `new_permission_name` | `"{principal}_{actions}"` | Name of the permissions the plugin creates for new grants. `{principal}` is the group name or username in lower case, with other characters turned into `_`; `{actions}` is the action letters, such as `vac` (see [Action letters](changes.md#action-letters)). `{action}` is accepted as another name for `{actions}`. A number is appended when the name is already taken. |
| `menu_placement` | `"admin"` | `"admin"` puts "Permissions Matrix" right below "Permissions" in Admin > Authentication. `"plugins"` puts it in the Plugins menu instead. |
| `show_action_tabs` | `False` | Whether the matrix page also has one tab per action (View, Add, Change, Delete, custom actions) next to All actions. Off, the page only shows the all-actions grid and ignores `?action=` in the URL. The group tab and the REST API are not affected. |
| `show_users_by_default` | `False` | Whether the matrix opens with every user column shown. The **Users** picker on the page changes it per visit. |
| `hidden_apps` | `[]` | App labels (for example `["wireless", "vpn"]`) whose object types get no row in the matrix. Grants on those types are still kept intact when the plugin rewrites a permission. |

!!! note
    The menu placement is read once, when NetBox starts. Restart NetBox after changing it.
