# Troubleshooting

## The menu item is missing

- Check **Admin > System > Plugins** lists Permissions Matrix. If not, check `PLUGINS` in `configuration.py` and
  restart NetBox.
- If `PLUGINS` is right, look for `Unable to load plugin netbox_permissions_matrix_plugin` in NetBox's start log:
  NetBox skips a plugin that does not support its version. See the supported range in
  [Installation](installation.md#requirements).
- The item needs `users.view_objectpermission`. Superusers always see it.
- By default the item is in the **Plugins** menu. Releases up to 0.4 put it below **Permissions** in
  **Admin > Authentication**, and `menu_placement: "admin"` still does.
- With `menu_placement: "admin"`, if NetBox changes its Admin menu so the item cannot be placed, the plugin logs a
  warning at start and puts it in the **Plugins** menu instead. See [Configuration](configuration.md).

## The page is unstyled or does not react

The page needs its static files. Run `python manage.py collectstatic --no-input` after installing or upgrading the
plugin. The page asks for them by a hash of their contents, so browsers fetch new versions by themselves.

## NetBox does not start: "PLUGINS_CONFIG new_permission_name ..."

The `new_permission_name` setting cannot name a permission. The error says why, for example
`unknown placeholder {team}`. Only `{principal}`, `{actions}` and `{action}` are known, used as they are: `{principal[0]}` or
`{principal.upper}` is refused. Write a literal brace as
`{{` or `}}`. Fix the setting and start NetBox again; see [Configuration](configuration.md).

## "The permissions matrix needs view access to all permissions"

Your view permission on permissions has constraints. The matrix shows and plans against every permission, so it
needs unconstrained view access. See [Permissions](permissions.md).

## "The permissions changed since this plan was made"

Someone (or another tab) changed a permission of a group or user in your change set between **Review changes** and
**Apply**, or took a name the review gives a permission (or freed one it had to avoid). Nothing was written. Reload the page; your staged changes are lost, so stage them again and review.

## "A group or user in this plan was deleted while it was applied"

Someone deleted a group or user in your change set while the apply was writing it. Nothing was written. Reload the
page, stage your changes again and review.

## "You are not allowed to add, change or delete the permission ..."

One operation of the plan needs a right you do not have, for example creating a permission during a split when you
may only change permissions. Nothing was written. Ask for the missing permission or have someone else apply it.

## Logging

Applied plans are logged by the `netbox_permissions_matrix_plugin` logger at INFO level. To keep them in a file, add
to `configuration.py`:

```python
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {
        "matrix_file": {
            "class": "logging.handlers.WatchedFileHandler",
            "filename": "/var/log/netbox/permissions-matrix.log",
        },
    },
    "loggers": {
        "netbox_permissions_matrix_plugin": {"handlers": ["matrix_file"], "level": "INFO"},
    },
}
```

A line looks like:

```text
admin applied a permissions matrix plan: update 'NOC-RW' (#4); create 'NOC-RW (NOC)' (#12); create 'NOC-RW (NOC) 2' (#13)
```
