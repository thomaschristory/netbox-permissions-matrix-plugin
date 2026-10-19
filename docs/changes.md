# How changes map to permissions

The matrix has no storage of its own. Every tick and untick becomes a change to NetBox's own permissions, and the
review dialog shows those changes before anything is written. This page explains the rules, so the review is never a
surprise.

## Words used here

- **Principal**: a group or a user.
- **Cell**: one principal, one object type, one action.
- **Covered**: a permission covers a cell when it is assigned to the principal and lists the object type and the
  action.
- **Simple permission**: a permission assigned to exactly one principal, with exactly one action and no constraints.
  These are the only permissions the plugin grows. Each principal ends up with at most one per action, for example
  `NOC | change`.

## Ticking a cell

1. If an enabled permission without constraints already covers the cell, nothing happens.
2. If the principal has a simple permission for the action, the object type is added to it.
3. Otherwise the plugin creates a simple permission for the principal and the action, named from the
   `new_permission_name` setting (default `NOC | change`). A number is appended if the name is taken.

Ticking several cells for the same principal and action fills one simple permission. Ticking cells for several
actions gives one simple permission per action; the plugin never builds a permission with several actions.

For a user column, only the user's own permissions count in step 1: a group the user belongs to may already grant
the cell, but ticking it still gives the user a direct grant.

If the simple permission is disabled, the object type is still added, and the review warns that the grant stays
inactive until the permission is enabled.

## Unticking a cell

Unticking removes the cell from **every** permission that covers it: enabled or disabled, with or without
constraints. For each of those permissions:

- If the permission grants nothing else to this principal, and nobody else has it, it is deleted.
- If it grants other cells but belongs to this principal only, it is rewritten in place to keep the other cells.
  When the cells left cannot be expressed as one permission (because object types keep different actions), the
  plugin creates one more permission per extra combination.
- If it is shared with other groups or users, the principal is removed from it, so the others keep exactly what
  they had, and the principal gets new permissions for whatever it should keep.

Permissions created by a split copy the original's constraints, enabled flag and description (prefixed with
"Split from ..."), and are named after it: `NOC-RW (NOC)`, `NOC-RW (NOC) 2`.

## Example

`NOC-RW` grants **view** and **change** on Device and Site to the groups NOC and Ops. You untick "change Site" for
NOC. The review shows:

| Operation | Permission | Result |
|-----------|------------|--------|
| Change | NOC-RW | Group NOC removed. Ops keeps view and change on Device and Site. |
| Create | NOC-RW (NOC) | View and change on Device, group NOC. |
| Create | NOC-RW (NOC) 2 | View on Site, group NOC. |

NOC ends with exactly what it had minus "change Site". Ops does not change at all.

## What the plugin never does

- Change a permission you did not touch through a cell or the gear panel.
- Merge or tidy existing permissions.
- Add or change constraints, except through the gear panel.
- Change group membership or create groups or users.

## Concurrent changes

The review comes with a token covering every permission of the principals involved. If anyone changes one of them
before you click Apply (on the classic pages, through the API, or in another matrix tab), the apply is refused and
nothing is written. Reload the matrix and review again.

## History

NetBox does not record changes to permissions in its change log. The plugin writes every applied plan to the
`netbox_permissions_matrix_plugin` logger at INFO level: who applied it and each permission created, changed or
deleted. See [Troubleshooting](troubleshooting.md#logging) to send it to a file.
