# Configuration

The plugin works without any settings. To change the defaults, add a `netbox_permissions_matrix_plugin` entry to
`PLUGINS_CONFIG` in NetBox's `configuration.py` (or `plugins.py` with netbox-docker) and restart NetBox.

```python
PLUGINS_CONFIG = {
    "netbox_permissions_matrix_plugin": {
        "new_permission_name": "{principal} | {action}",
        "menu_placement": "admin",
        "show_users_by_default": False,
        "hidden_apps": [],
    },
}
```

## Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| `new_permission_name` | `"{principal} \| {action}"` | Name of the permissions the plugin creates for new grants. `{principal}` is the group name or username, `{action}` the action. A number is appended when the name is already taken. |
| `menu_placement` | `"admin"` | `"admin"` puts "Permissions Matrix" right below "Permissions" in Admin > Authentication. `"plugins"` puts it in the Plugins menu instead. |
| `show_users_by_default` | `False` | Whether the matrix shows user columns when it opens. The switch on the page changes it per visit. |
| `hidden_apps` | `[]` | App labels (for example `["wireless", "vpn"]`) whose object types get no row in the matrix. Grants on those types are still kept intact when the plugin rewrites a permission. |

!!! note
    The menu placement is read once, when NetBox starts. Restart NetBox after changing it.
