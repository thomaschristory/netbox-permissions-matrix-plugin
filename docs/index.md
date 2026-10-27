# netbox-permissions-matrix-plugin

A NetBox plugin that shows NetBox's object permissions as a matrix: object types down the side, groups (and
optionally users) across the top, and in each cell one lettered chip per action (V for view, A add, C change, D
delete, and custom actions). Clicking chips edits NetBox's own permissions, with a review of every change before it
is written.

!!! warning "Pre-release"
    The plugin is below 1.0. Read the review dialog before applying changes, and keep a database backup, as you
    would for any tool that edits permissions in bulk.

## What it does

- Reads every NetBox permission and shows, for each group, object type and action, whether it is granted, granted
  only under constraints, or granted only by a disabled permission.
- Shows every action on one page, with toggles per row, column and app for one action or all of them. Tabs with
  one action each can be switched on in the [configuration](configuration.md).
- Names the permissions it creates after their actions: `noc_va` holds what NOC may view and add.
- Edits names, descriptions, the enabled flag and [constraints](constraints.md) of a group's permissions from a
  panel on the page.
- Edits NetBox's own permission records. It stores nothing of its own: a change made in the matrix is visible on
  the classic Permissions page, and uninstalling the plugin leaves a normal permission setup.
- Never changes what another group or user can do. Unticking a cell granted by a permission shared with other
  groups splits that permission so the others keep exactly what they had.
- Shows every permission it will create, change or delete before writing anything, and writes everything in one
  transaction.
- Exports the matrix as YAML and imports it back, here or on another NetBox, through the same review.

![The matrix](img/matrix.png)

## Where to start

- [Installation](installation.md)
- [Quick start](quickstart.md)
- [Configuration](configuration.md)
- [Design](DESIGN.md), for how matrix changes map to native permissions

## Compatibility

| Plugin | NetBox | Python |
|--------|--------|--------|
| 0.5 | 4.7.2 to 4.7.x | 3.12 to 3.14 |
| 0.4 | 4.7.0 and later | 3.12 to 3.14 |
| 0.3 | 4.7.0 and later | 3.12 to 3.14 |
| 0.2 | 4.7.0 and later | 3.12 to 3.14 |
| 0.1 | 4.7.0 and later | 3.12 to 3.14 |

## License

Apache-2.0, see [LICENSE](https://github.com/thomaschristory/netbox-permissions-matrix-plugin/blob/main/LICENSE).
