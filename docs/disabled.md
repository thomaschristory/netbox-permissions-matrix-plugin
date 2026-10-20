# Disabled permissions

A disabled permission is switched off: it still exists, with its object types, actions, groups and users, but it
grants nothing. This page explains how NetBox treats disabled permissions, how the matrix shows them, and what ticking,
unticking and the gear panel do with them.

## How NetBox treats them

Every NetBox permission has an **Enabled** flag. When it is off, NetBox ignores the permission when it checks access,
as if it were not there. Nothing else changes: the permission keeps its name, object types, actions, constraints and
assignments, and switching it back on restores exactly the access it gave before.

That makes the flag a way to take access away for a while without losing the setup: during an incident, while
someone is away, or before deleting a permission you are not sure about.

Since NetBox ignores a disabled permission, so does the matrix when it decides whether a cell is granted. A cell
covered by a disabled permission and an enabled one takes its state from the enabled one.

## How the matrix shows them

A chip (or box) is **filled grey and faded** when only disabled permissions cover it. The group or user has no access
there: the chip only says that a permission for it exists and is switched off. Hover it to see the permissions; each
disabled one is marked `(disabled)`.

| What covers the cell | State |
|----------------------|-------|
| Nothing | Not granted |
| Only disabled permissions | Disabled |
| Enabled permissions, all with constraints (disabled ones may cover it too) | [Constrained](constraints.md) |
| At least one enabled permission without constraints | Granted |

So disabled is the weakest state. A constrained chip gives access to some objects. A disabled chip gives access to
none.

In a user column, the dot for access through a group follows the same rules: its tooltip reads, for example,
`Also through: NOC (disabled)` when the group's only grant is a disabled permission.

The gear panel marks a disabled permission with a **disabled** badge next to its name.

## Example

NOC had `noc_v`: view on Device and Site. Someone switched it off on NetBox's permission page. In the matrix, the
**V** chips of NOC on Device and Site are grey and faded. Hovering one shows `noc_v (disabled)`.

Clicking **V** on Device stages a grant. The review shows:

| Operation | Permission | Result |
|-----------|------------|--------|
| Create | noc_v 2 | View on Device, group NOC. |

`noc_v` is left as it is, still disabled. The new permission gets a number because `noc_v` holds the name. After
**Apply**, the Device chip is green and the Site chip is still grey.

To give NOC its old access back instead, switch `noc_v` on in the gear panel (see
[Enabling and disabling](#enabling-and-disabling)). Both chips turn green, and no permission is created.

## Clicking a disabled chip

A click toggles a chip between granted and not granted, as for any chip. A disabled chip counts as not granted:

- **The first click grants it.** The grant goes into an enabled permission without constraints, as described in
  [How changes map to permissions](changes.md#ticking-a-cell). The disabled permission never receives it and is not
  switched on: a new simple permission is created, or an existing one grows. If the disabled permission holds the
  name the new one would get, the new one takes a number (`noc_v 2`).
- **The second click revokes it completely.** The chip is staged as not granted, which removes the cell from every
  permission that covers it, the disabled one included.

No third click puts a disabled chip back as it was. To drop the staged change, click **Revert last** right after
(or press Ctrl+Z), or **Discard**, which forgets every staged change.

## Revoking a disabled cell

A disabled cell is revoked by the second click on its chip, by the second press of a row, column or app toggle, or by
an import that does not list the cell. The revoke removes the cell from every permission that covers it, enabled or
not. For a disabled permission:

- **Assigned to this group or user alone, and the cell is all it covers**: the permission is deleted. It is never
  reused for a grant in the same change set, because its disabled flag would carry over to access that was ticked
  without it. Its name is free, though: a permission created in the same change set may take it without a number.
- **Assigned to this group or user alone, with other cells**: the permission is rewritten in place to keep the other
  cells. When they cannot fit in one permission, the extra parts become new permissions, named after it. They are
  disabled too.
- **Shared with other groups or users**: this group or user is removed from it. The others keep it exactly as it was,
  and this group or user gets new permissions, disabled as well, for what it keeps.

Nobody gains access: what was disabled stays disabled.

## Toggles for rows, columns and apps

The **all** and letter toggles on rows, columns and app sections treat a disabled chip as not granted, as they do a
constrained one. The first press grants everything on the line through enabled permissions, the disabled ones left
alone. A second press revokes everything on the line, the disabled permissions' cells included. To keep a disabled
permission as it is, do not use the line toggles: click the other chips one by one and leave the disabled ones alone.

## Enabling and disabling

The **Enabled** switch is in the [gear panel](matrix.md#the-gear-panel):

1. Click the gear in the column header. On the group tab, use the header of an action the permission grants. A
   single-action tab lists only the permissions that grant its action; the all-actions grid lists them all.
2. Open the permission. Check the summary line: it says which actions it has and how many object types it covers.
   The switch applies to all of them.
3. Turn **Enabled** on or off.
4. Click **Stage changes**, then **Review changes**. The review shows `Enabled` before and after, and lists every
   group and user the permission is assigned to as affected.
5. Click **Apply**.

!!! warning "Shared permissions"
    A permission assigned to several groups or users says so at the top of its form. Disabling it takes the access
    away from all of them, not only from the column you opened the panel from.

### Disabling a simple permission

The matrix grows and shrinks only **simple** permissions: one group or user, enabled, no constraints (see
[How changes map to permissions](changes.md)). Disabling one, such as `noc_va`, takes it out of that pool. The review
warns: `Once disabled, noc_va is no longer simple: new grants of view, add for NOC will go into a new permission.`

- The next time you tick view and add for NOC, a new `noc_va 2` is created for it.
- Panel edits are applied before the cell changes of the same review. So if you disable `noc_va` and tick view and
  add on another object type in one go, the new grant goes into `noc_va 2`, not into the disabled permission.

### Enabling a permission again

A disabled permission assigned to one group or user, without constraints, becomes a simple permission again once
enabled. The matrix then grows and shrinks it like any other. If two simple permissions then have the same actions,
for example `noc_v` and `noc_v 2`, new grants go into the one with the lowest ID.

## Who can

The [who can](who-can.md) page shows disabled cells with the same grey state. In **Effective access**, a user whose
only access to an action comes from disabled permissions is still listed, with the disabled state, and the source
says where it comes from. NetBox gives that user nothing for that action.

## Export and import

An [export](export-import.md) lists cells covered only by disabled permissions under `disabled`, with the name of
each permission:

```yaml
disabled:
  group:NOC:
    view:
    - object_type: dcim.site
      permission: noc_v
```

An import never enables or disables a permission, and never adds a grant to a disabled one:

- a cell listed under `disabled` keeps whatever covers it on the target today. The review warns when nothing grants
  it there, or when it is granted there without constraints. If the target covers the cell with an enabled
  constrained permission, it keeps that access and the review does not warn;
- a cell listed under `grants` that is disabled on the target is granted through an enabled permission, as a click
  would;
- a cell in the file's scope that is not listed anywhere is revoked, also from disabled permissions. That can split
  a disabled permission, and the parts it keeps stay disabled (see
  [Revoking a disabled cell](#revoking-a-disabled-cell)).

## REST API

In `GET matrix/` and `GET principal/`, a cell covered only by disabled permissions has `"state": "disabled"`, and
each permission object carries `"enabled": false`. An edit in `plan/` and `apply/` takes `"enabled": true` or
`"enabled": false` to switch a permission on or off, as the gear panel does. See the [REST API](api.md).

## What the matrix never does with disabled permissions

- Ticking a chip never enables a permission, and never adds the grant to a disabled one.
- Unticking never enables a permission. The parts it keeps stay disabled.
- Only the **Enabled** switch in the gear panel, or an `enabled` edit in the API, changes the flag.
