# Limitations

The matrix shows and edits NetBox's object permissions. Some access in NetBox comes from elsewhere, and some
permission setups do not fit in a grid of checkboxes. This page lists what to keep in mind.

## Access the matrix does not show

- **Superusers** can do everything, whatever their permissions. The matrix does not draw them; the
  [who can](who-can.md) page lists them separately.
- **`EXEMPT_VIEW_PERMISSIONS`** in NetBox's configuration lets everyone view the listed models without a permission.
  The matrix shows only what permissions grant, so an exempt model can show "not granted" for a group whose members
  can still view it.
- **Anonymous access** with `LOGIN_REQUIRED = False` is not a group and has no column.
- **`DEFAULT_PERMISSIONS`** grants every authenticated user some access (by default, managing their own API tokens)
  without a permission object, so the matrix never shows it.
- **`REMOTE_AUTH_DEFAULT_PERMISSIONS`** works the same way for users created by remote authentication, and
  **`REMOTE_AUTH_DEFAULT_GROUPS`** adds them to groups, whose access the matrix does show.
- **Group membership** is managed on the user and group pages. A user column shows the user's own permissions; access
  through groups is only marked with a dot. Remote authentication (LDAP, SSO) may add users to groups at login, which
  the matrix reflects only once it has happened.
- **Inactive users** still get a column when they have permissions of their own, although NetBox refuses them. The who
  can page leaves them out of effective access.
- **API tokens** can be limited further (write disabled, allowed IPs). The matrix shows the user's permissions, not
  what a given token may do.

## Constraints

- A constrained cell says "some objects". Which ones depends on each object, so the matrix cannot tick or untick
  them partly. Hover the cell to read the constraints.
- Ticking a cell never adds constraints. Constraints are edited per permission in the
  [gear panel](matrix.md#the-gear-panel), or on the classic permission page. A constraint covers every object type
  and action of its permission; the matrix cannot constrain one cell on its own.
- An [import](export-import.md) never creates or changes constraints.

## Actions

- Actions typed into "Additional actions" on the classic form show up as their own chips (and tabs, with `show_action_tabs`). NetBox does not
  say which models they apply to, so every row is enabled for them.
- Custom actions other than render_config and sync use their first letter in names and chips, so two of them can
  share a letter. The chip's tooltip names the action; permission names stay unique by getting a number.
- An action name is at most 30 characters, lower case letters, digits and underscores, as in NetBox.

## Scale

- Every group is a column. With hundreds of groups, use **Columns** to pick the ones you need; the choice is kept in
  the URL so it can be bookmarked.
- The matrix loads every permission at once. That is a few queries whatever the size, but a very large number of
  permissions makes the page slower to draw.

## Who may use it

The matrix shows every permission, so it needs unconstrained view access to permissions. A permissions administrator
limited to some permissions by constraints cannot use it, and should keep using the classic pages. See
[Permissions](permissions.md).

## Changes made elsewhere

The matrix reads permissions when it loads. If, before you apply, someone changes a permission assigned to a group or
user in your staged changes, or creates, renames or deletes any permission (new names could clash with the ones your
plan creates), apply refuses and asks you to review again, so nothing is overwritten. Other changes, such as editing
a permission of an unrelated group, do not block it.
