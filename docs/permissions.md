# Permissions

The plugin checks NetBox's own permissions. It never lets a user do more through the matrix than they could do on
the classic Permissions pages.

## Viewing the matrix

| Needed | For |
|--------|-----|
| `users.view_objectpermission`, without constraints | The page, the group tab, the who-can page, export, and `GET matrix/`. The menu item appears with this permission. |
| `users.view_group` | Group columns. Only the groups the user may view are shown. |
| `users.view_user` | User columns. Only the users the user may view are shown. |

The matrix shows every permission in NetBox, so the plugin refuses users whose `view` permission on permissions is
limited by constraints: showing them a partial matrix would also make its changes wrong.

## Changing permissions

| Needed | For |
|--------|-----|
| `users.add_objectpermission` | Plans that create permissions (new grants, splits). |
| `users.change_objectpermission` | Plans that change permissions (adding object types, removing a group, edits). |
| `users.delete_objectpermission` | Plans that delete permissions (the last cell of a permission revoked). |

A user with at least one of the three can stage changes, import a file and review them. Apply checks each operation against the
user's permissions, constraints included, both before and after the write, as NetBox's own edit views do. If any
operation is not allowed, the whole plan is rolled back and nothing is written.

Editing a permission from the gear panel also needs to see every group and user it is assigned to: a permission
shared with a group you cannot see is refused at review, because the edit would change that group's access.

A user with none of the three sees the matrix read-only: chips do not toggle, no review.

Superusers bypass all of these checks, as everywhere in NetBox.

## Example: a permissions administrator

A group that manages permissions but nothing else:

| Permission | Actions | Object types |
|------------|---------|--------------|
| Permission admins | view, add, change, delete | Users > Permission |
| Permission admins (directory) | view | Users > Group, Users > User |

!!! warning
    Whoever can change permissions can grant themselves anything. Treat these rights like superuser access.
