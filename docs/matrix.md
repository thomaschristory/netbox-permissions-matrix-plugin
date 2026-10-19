# The matrix

Open **Admin > Authentication > Permissions Matrix**.

![The matrix on the Change tab, with user columns and only rows with grants](img/matrix.png)

```
[View] [Add] [Change] [Delete] [Sync] ...        [search] [apps] [ ] Only rows with grants  [ ] Users  [Columns]

                          | NOC  ⚙ [all] | Ops  ⚙ [all] | Read-only ⚙ [all] |
  DCIM            [all]   |              |              |                   |
    Device        [all]   |     [x]      |     [ ]      |       [x]         |
    Site          [all]   |     [x]      |     [~]      |       [x]         |
  IPAM            [all]   |              |              |                   |
    Prefix        [all]   |     [ ]      |     [x]      |       [x]         |

                                            3 changes staged   [Discard] [Review changes]
```

## Actions

The tabs at the top switch the whole matrix between actions:

- **View, Add, Change, Delete**: NetBox's four standard actions.
- **Custom actions** registered by models, such as Sync on data sources or Render Config on devices. On these tabs,
  rows whose model does not have the action are greyed out.
- **Other actions** found in existing permissions (typed into "Additional actions" on the classic form). NetBox
  cannot tell which models they apply to, so every row is enabled.

The active tab is kept in the URL (`?action=change`), so a tab can be bookmarked.

## Rows and columns

Rows are the object types NetBox lets you put in a permission, grouped by app. Click an app name to collapse it.

- **Search** filters rows by model or app name.
- **Apps** limits the apps shown.
- **Only rows with grants** hides rows where no visible column has the action.

Columns are groups, by name. Switch on **Users** to add a column for every user who has a permission assigned
directly. **Columns** picks which groups and users are shown; the choice is kept in the URL.

The header row and the object type column stay in place while you scroll.

Click an object type to open its [who can](who-can.md) page.

## Cell states

| Box | State | Meaning |
|-----|-------|---------|
| empty | Not granted | No permission covers the cell. |
| ticked | Granted | At least one enabled permission without constraints covers the cell. |
| half filled | Constrained | Only permissions with constraints cover the cell: access to some objects, not all. |
| ticked, dimmed | Disabled | Only disabled permissions cover the cell. NetBox ignores them. |
| coloured outline | Staged | Changed on the page, not applied yet. |

Hover a cell to see every permission that covers it, with its constraints and a link to it.

In a user column, a small dot marks access the user also has through a group; the tooltip names the group. The dot
is only information: the user column changes the user's own permissions, never the group's.

## Changing cells

Click a cell to toggle it between granted and not granted. A constrained or disabled cell becomes granted on the first
click; the second click revokes it completely.

Each column header, app section and row has an **all** toggle: it ticks every visible, enabled cell in that line, or
unticks them all if they are already ticked.

Changes are only staged in your browser. The bar at the bottom counts them; **Discard** forgets them. Leaving the
page with staged changes asks for confirmation.

## Review and apply

**Review changes** asks NetBox to plan the staged changes, without writing anything, and shows every permission it
would create, change or delete, field by field, with the groups and users each change affects and any warnings.
[How changes map to permissions](changes.md) explains the rules.

**Apply** writes the plan in one transaction. If someone changed one of the permissions involved since the review,
nothing is written and the page asks you to reload.

## The gear panel

The gear next to a column name opens a panel for that group or user and the active action:

- The principal's **simple permission** for the action (the one new grants go into), as a form: name, description,
  enabled, constraints, additional actions, groups and users. If there is none yet, the panel says so; tick a cell
  first.
- Every **other permission** that grants the action to the principal, read-only, with a link to edit it on the
  classic page.

![The gear panel for NOC on the Change tab](img/gear-panel.png)

Panel changes are staged and reviewed like cell changes. Adding constraints, actions, groups or users to the simple
permission makes it no longer simple: new grants then go into a new permission. The panel warns before staging such
a change.

Constraints use NetBox's format: an object, or a list of objects combined with OR, and `$user` for the current user.
They are checked against every object type of the permission, as on the classic form.

## Read-only mode

Users who may view permissions but not add, change or delete them see the matrix without checkboxes. See
[Permissions](permissions.md).
