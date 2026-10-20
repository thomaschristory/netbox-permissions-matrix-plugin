# Troubleshooting

## The menu item is missing

- Check **Admin > System > Plugins** lists Permissions Matrix. If not, check `PLUGINS` in `configuration.py` and
  restart NetBox.
- The item needs `users.view_objectpermission`. Superusers always see it.
- The plugin puts the item below **Permissions** in **Admin > Authentication**. If a future NetBox changes that
  menu so the item cannot be placed, the plugin logs a warning at start and puts it in the **Plugins** menu instead.
  `menu_placement: "plugins"` does that on purpose; see [Configuration](configuration.md).

## The page is unstyled or does not react

The page needs its static files. Run `python manage.py collectstatic --no-input` after installing or upgrading the
plugin. The page asks for them by a hash of their contents, so browsers fetch new versions by themselves.

## "The permissions matrix needs view access to all permissions"

Your view permission on permissions has constraints. The matrix shows and plans against every permission, so it
needs unconstrained view access. See [Permissions](permissions.md).

## "The permissions changed since this plan was made"

Someone (or another tab) changed a permission of a group or user in your change set between **Review changes** and
**Apply**. Nothing was written. Reload the page; your staged changes are lost, so stage them again and review.

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
