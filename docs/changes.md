# How changes map to permissions

The matrix has no storage of its own. Every tick and untick becomes a change to NetBox's own permissions, and the
review dialog shows those changes before anything is written. This page explains the rules, so the review is never a
surprise.

## Words used here

- **Principal**: a group or a user.
- **Cell**: one principal, one object type, one action.
- **Covered**: a permission covers a cell when it is assigned to the principal and lists the object type and the
  action.
- **Simple permission**: a permission assigned to exactly one principal, enabled and without constraints. These are
  the only permissions the plugin grows and shrinks. Each principal ends up with at most one per set of actions,
  named after that set: `noc_va` for view and add, `noc_vacd` for all four standard actions.

## Action letters

Simple permissions created by the plugin are named `<principal>_<letters>`. The principal is the group name or
username in lower case, with anything other than letters and digits turned into `_` (`NOC Paris` becomes
`noc_paris`). The letters list the actions in a fixed order:

| Letter | Action |
|--------|--------|
| `v` | view |
| `a` | add |
| `c` | change |
| `d` | delete |
| `r` | render_config |
| `s` | sync |

Any other custom action uses its first letter, after the six above. The pattern is the `new_permission_name`
setting; see [Configuration](configuration.md).

## Ticking a cell

1. If an enabled permission without constraints already covers the cell, nothing happens.
2. The plugin works out the actions the object type will have in the principal's simple permissions: the ones it
   has now plus the ones you ticked.
3. The object type leaves the simple permission it was in, and goes into the principal's simple permission for the
   new set of actions. If there is none, one is created and named as above. A number is appended if the name is
   taken. The name of a permission the same change set deletes counts as free, as does the name of a split
   permission the same change set empties again.

So ticking **Change** on Device for NOC, when NOC has `noc_va` on Device and Site, moves Device from `noc_va` to
`noc_vac`. Site stays in `noc_va`. Ticking view and add on several object types fills one `noc_va`.

When the object type was the last one in its old permission, and the principal has no simple permission for the
new set yet, the old permission is not deleted. It takes the new actions instead and keeps its ID, description and
other settings. If it still has a name the plugin gave it, it is renamed to match (`noc_va` becomes `noc_vac`); a
name you set yourself is kept. Names from version 0.1.0 (`NOC | view`) count as given by the plugin, so they are
renamed too. When a simple permission for the new set already exists, the object type joins it and the empty one is
deleted.

For a user column, only the user's own permissions count in step 1: a group the user belongs to may already grant
the cell, but ticking it still gives the user a direct grant.

A disabled permission is not simple: ticking a cell leaves it alone and grants through an enabled permission, named
with a number if the disabled one has the name (`noc_v 2`).

## Unticking a cell

Unticking removes the cell from **every** permission that covers it: enabled or disabled, with or without
constraints. For each of those permissions:

- If it is one of the principal's simple permissions, the object types that keep all its actions stay in it. The
  others move to the simple permission for the actions they keep: unticking add on Device moves Device from
  `noc_va` to `noc_v`. When no object type keeps all the actions, the permission takes the new set and is renamed,
  keeping its ID, as when ticking.
- Otherwise, if the permission grants nothing else to this principal, and nobody else has it, it is deleted. It is
  never reused for a grant in the same change set: its constraints or disabled flag would carry over to access
  that was ticked without them. Its name is free, though: a permission created in the same change set may take it,
  without a number.
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
- Add or change constraints, except through the gear panel (see [Constraints](constraints.md)).
- Rename a permission whose name you changed by hand.
- Change group membership or create groups or users.

## Concurrent changes

The review comes with a token covering every permission of the principals involved. If anyone changes one of them
before you click Apply (on the classic pages, through the API, or in another matrix tab), the apply is refused and
nothing is written. Reload the matrix and review again. The same happens if someone takes a name the review gives
a permission, or frees a name it had to avoid: the names would no longer be the ones you reviewed. Creating,
renaming or deleting other permissions does not block the apply. The same happens if a group or user in the change set is
deleted while the apply runs.

## History

NetBox does not record changes to permissions in its change log. The plugin writes every applied plan to the
`netbox_permissions_matrix_plugin` logger at INFO level: who applied it and each permission created, changed or
deleted. See [Troubleshooting](troubleshooting.md#logging) to send it to a file.
