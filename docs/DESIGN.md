# Design

This page records why the plugin works the way it does. It is written for contributors; users should start with
the [overview](index.md).

## Intent

NetBox permissions are sets: one `ObjectPermission` grants a list of actions on a list of object types to a list of
groups and users, optionally narrowed by constraints. That model is powerful but hard to read. Answering "what can
the NOC group change?" or "who can delete prefixes?" means opening permissions one by one.

The plugin shows the same data as a matrix: object types down the side, groups (and optionally users) across the
top, one lettered chip per action in each cell. Ticking and unticking chips edits the native permissions.

## Goals

- Read every native `ObjectPermission` and show the real, current state of each cell.
- Edit the native records directly. A change made in the matrix is visible on the classic Permissions page and the
  other way round.
- Make shared permissions safe to edit: a change for one group never silently changes what another group can do.
- Show every change before it is written, and write it in one transaction.
- Cover what the classic permission page offers: name, description, enabled, constraints, users, groups,
  additional actions.

## Non-goals

- No storage of its own. The plugin has no models and no migrations. Uninstalling it leaves a normal, working
  permission setup.
- No replacement for the classic Permissions pages. They stay the place for unusual setups; the matrix links to
  them.
- No change to how NetBox evaluates permissions.

## Anti-goals

These would make the plugin a failure even if it worked:

- Producing anything the native permission system cannot read, or that only makes sense with the plugin
  installed.
- Changing the access of a group or user the operator did not touch.
- Writing anything without showing it first.

## Constraints

- NetBox 4.7.0 or later (Django 6.1, Python 3.12 to 3.14). `min_version = "4.7.0"` and no `max_version`: the plugin
  keeps loading on newer NetBox releases, and CI tests the supported range.
- Only public NetBox and Django APIs, plus one documented exception: the menu item is inserted into NetBox's core
  Admin menu (see [Navigation](#navigation)).

## Vocabulary

- **Principal**: a group or a user that permissions are assigned to.
- **Cell**: one (principal, object type, action) triple.
- **Grant**: a permission that covers a cell: it is assigned to the principal, lists the object type and lists the
  action.
- **Simple permission**: a permission assigned to exactly one principal, enabled and without constraints, whatever
  its actions. The plugin creates, grows and shrinks only simple permissions, so each principal ends up with at most
  one per set of actions. If several qualify for a set (made by hand), the one with the lowest ID is used.
- **Action letters**: the short form of an action set used in names: `v` view, `a` add, `c` change, `d` delete, `r`
  render_config, `s` sync, any other action its first letter. Reserved actions come first in that order, then
  custom actions by name. View, add and change is `vac`.

## The matrix page

URL `/plugins/permissions-matrix/`. Menu entry "Permissions Matrix" in Admin > Authentication, right below
"Permissions".

### Layout

```
[All actions] [View] [Add] [Change] [Delete] [custom actions...]   [search] [app filter] [groups] [users]

                            |   NOC ⚙       |   Ops ⚙       |
                            | [V A C D R S] | [V A C D R S] |
  DCIM      all V A C D R S |               |               |
    Device  all V A C D R   |  V A C D R    |  V A C D R    |
    Site    all V A C D     |  V A C D      |  V A C D      |
  Core      all V A C D R S |               |               |
    Data S. all V A C D   S |  V A C D   S  |  V A C D   S  |

                                            3 changes staged   [Discard] [Review changes]
```

- **All actions**, the default view, shows every action at once: each cell is a row of lettered chips, one per
  action, each with its own state. The actions are View, Add, Change, Delete, then every custom action registered by
  a model (`registry["model_actions"]`, NetBox 4.6+), then every free-text "additional action" found in existing
  permissions. A custom action only has a chip on rows whose model registered it; the slot stays empty elsewhere so
  the letters line up. Free-text actions have a chip on every row, because NetBox cannot tell which models they
  apply to.
- **Single-action tabs** follow when the `show_action_tabs` setting is on, one per action, with one box per cell. On a custom action tab, only rows whose
  model registered that action are enabled; the others are greyed out.
- **Rows** are the object types that NetBox allows in a permission (the same `OBJECTPERMISSION_OBJECT_TYPES` filter
  the classic form uses), grouped by app. App sections can be collapsed. A search box filters rows by name; an app
  filter limits the apps shown; a "Only rows with grants" switch hides empty rows.
- **Columns** are groups, then users, sorted by name. The "groups" picker limits the groups shown, all by default.
  The "users" picker adds columns for users that have at least one permission assigned directly, none by default.
  Users who get access only through a group do not get a column; the "Who can" page shows them. Both choices are kept
  in the URL so they can be bookmarked.
- A user column shows the user's **direct** permissions. Access the user also gets through a group is shown as a
  small "inherited" marker in the cell, with the group named in the tooltip ("a group you cannot view" for a group
  the viewer may not view). The marker is never editable from the user column: changing it would change the group. Ticking such a cell adds a direct grant for the user.
- Object types that existing permissions reference but that NetBox does not offer in the permission form (for
  example non-public types set through the API) have no row. The planner still keeps them intact when it rewrites
  or splits a permission.
- The header row and the first column stay in view while scrolling.
- Each column header has a gear icon (see [The gear panel](#the-gear-panel)). On All actions it also has one letter
  toggle per action, which ticks or unticks that action on every visible, enabled row in the column; on a
  single-action tab it has one "all" toggle. Each row and app section has an "all" toggle that does the same across
  the visible columns, for every action on All actions; there it is followed by one letter toggle per action that
  applies to the row, which toggles only that action across the visible columns.
- Clicking an object type name opens the [Who can](#who-can-page) page for it.

### Cell states

Each chip on All actions, or box on a single-action tab, shows one state:

| State | Look | Meaning |
|-------|------|---------|
| Not granted | empty | No permission covers the cell. |
| Granted | filled | At least one enabled permission without constraints covers the cell. |
| Constrained | half-filled box | Only enabled permissions with constraints cover the cell. |
| Disabled | grey box, faded | Only disabled permissions cover the cell. NetBox ignores them. |
| Staged | coloured outline | Changed in the browser, not yet applied. |

Hovering a cell lists every permission that covers it, with its constraints and a link to the classic permission
page.

Clicking a cell cycles between two target states: granted (unconstrained) and not granted. A constrained or
disabled cell becomes granted on the first click. The second click marks the cell as not granted, which removes
every covering permission's grant for it, constrained or not.

### The gear panel

The gear icon on a column opens a side panel listing the principal's permissions: every permission assigned to it on
All actions, the ones granting the column's action on a single-action tab (on the group tab, the action of the
column). Each entry shows its name, actions, number of object types, disabled and constrained badges, and a link to
its classic page. Opening an entry gives a form for:

- name and description;
- enabled;
- constraints (JSON), which apply to every object type and action of that permission.

A permission shared with other principals carries a warning in its form: the edit changes their access too. A new
name already in use gets a number appended, and the review warns with the name that will be used.

Edits made in the panel are staged per permission ID and go through the same review. The planner applies them
before the cell changes, to the permission as the panel showed it, so a permission disabled or constrained in a
change set no longer takes that change set's grants. When the cell changes then delete the edited permission, the
review warns that the edit is lost. The editor must be able to see every group and user the permission is assigned
to. Adding constraints to a simple
permission, or disabling it, makes it no longer simple: the plugin then stops reusing it, and the next grant of
that action set for this principal creates a new simple permission. The review warns when an edit does this.
Additional actions, groups and users are not offered in the panel, since they would break the naming by action
set; the REST API still accepts them.

Constraints are validated the way the classic form validates them: a single object or a list of objects (combined
with OR), the `$user` token allowed, and a test query run against every object type of the permission.

### Saving: stage, review, apply

1. Clicks and panel edits are staged in the browser. The page shows the number of staged changes and highlights
   the changed cells. Leaving the page with staged changes asks for confirmation.
2. "Review changes" sends the staged change set to the server, which computes a plan without writing anything and
   returns it. The review dialog lists every permission that will be created, modified or deleted, field by field
   (before and after), and states which principals each change affects.
3. "Apply" sends the same change set again with the version token received in step 2. The server recomputes the
   plan, checks that the permissions it touches have not changed since the plan was made, and writes everything in
   one database transaction. If anything changed meanwhile, or a group or user in the change set was deleted while
   it was written, nothing is written (HTTP 409) and the page asks to reload.

## How changes map to native permissions

The planner is pure Python. It works on a snapshot of the permissions (plain data, no ORM) and a change set, and
returns a list of operations. The views and the API load the snapshot, call the planner and apply the operations.
Keeping the planner free of Django makes it fast to test exhaustively.

### Granting a cell

Grants are handled per (principal p, object type t), with A the actions ticked for that pair:

1. Drop from A every action an enabled permission without constraints already covers. If nothing is left, do
   nothing.
2. If one of p's simple permissions S lists t (the lowest ID if several do), remove t from S and add S's actions to
   A.
3. Add t to p's simple permission for exactly the action set A. If there is none:
   - if step 2 emptied S, S becomes it: it takes the actions A and the object type t, keeping its ID, description
     and settings. If S still has a generated name (the template's result for its old actions, with or without a
     number), it is renamed for A; a name set by hand is kept;
   - otherwise, create it. Its name comes from the `new_permission_name` setting (default
     `"{principal}_{actions}"`, for example `noc_vac`). A number is appended if the name is already taken. Names
     of permissions the change set deletes are not taken: the plan is worked out a second time with them free.
     Names held only by permissions the plan creates and then drops are free too: the names given in the plan are
     numbered again once those are gone.

Several object types ending with the same action set share one simple permission. After all grants and revokes, a
simple permission the change set emptied takes over a non-empty permission the same change set created for the same
principal, when one action set contains the other, so ticking change on every object type of `noc_va` renames
`noc_va` to `noc_vac` instead of deleting it and creating a new one.

For a user, step 1 only looks at the user's direct permissions; a grant inherited from a group does not count.

### Revoking a cell

For each permission P that covers the revoked cells of principal p (constrained or not, enabled or not):

1. Work out what P grants p: the set of (object type, action) pairs `P.object_types x P.actions`, then remove the
   revoked pairs. Call what is left the *remainder*.
2. If nothing was removed, leave P alone.
3. Group the object types of the remainder by the set of actions they keep. Each group becomes one permission with
   those object types and those actions. This is the smallest set of rectangles that represents the remainder
   exactly when actions are kept per object type.
4. If P is one of p's simple permissions: the group that keeps all of P's actions stays in P; every other group goes
   into p's simple permission for its action set, as in step 3 of granting. If no group keeps all of P's actions,
   P itself becomes the permission for the first group that has none, renamed the same way; if nothing is left, P is
   deleted unless a grant reuses it.
5. If P is assigned to p only and is not simple:
   - remainder empty: delete P. It is never reused for a grant: its constraints or disabled flag would carry over to
     access ticked without them;
   - otherwise: rewrite P in place to the largest group (keeping its name, description, enabled and constraints)
     and create one new permission per other group.
6. If P is shared with other principals: remove p from P, so the others keep exactly what they had, and create one
   new permission per group of the remainder, assigned to p only, copying P's description, enabled and constraints.

New permissions created by a split are named `"{original name} ({principal})"`, with a number appended if needed.
Their description notes which permission they were split from.

### Example

`NOC-RW` grants view and change on Device and Site to the groups NOC and Ops. The operator unticks "change Site" for
NOC. The plan is:

- modify `NOC-RW`: remove group NOC (Ops keeps view and change on Device and Site);
- create `NOC-RW (NOC)`: view and change on Device, group NOC;
- create `NOC-RW (NOC) 2`: view on Site, group NOC.

### What the planner never does

- Merge or tidy permissions the operator did not touch.
- Change constraints, except through the gear panel.
- Touch users, groups or permissions outside the change set.

## Who can page

URL `/plugins/permissions-matrix/object-types/<app_label>.<model>/`. For one object type, a table of every principal
that holds any action on it: rows are groups and users, columns are actions, cells show the same states as the
matrix. A second table resolves group membership: every user with effective access, which action, and through which
group or direct permission. Superusers are listed separately because they bypass permissions. Constrained access is
shown with its constraints, because whether it applies depends on the object. Groups and users the viewer may not
view have no row in the first table; access through a hidden group still counts in the second, with the source "a
group you cannot view".

## Group tab

A "Permissions Matrix" tab on each group's page in NetBox (Admin > Authentication > Groups, then a group). It shows that group's matrix turned
around: object types down the side, actions across the top, the same cell states, the same staging and review. It
lets an operator review or edit one group without the full matrix.

## Export and import

- **Export** downloads the matrix as YAML: for each principal, for each action, the list of object types granted
  without constraints, separately the constrained grants with their constraints and permission names, and the cells
  covered only by disabled permissions, with the permission names. The export honours the current column and row
  filters.
- The file records its **scope**: the principals, actions and object types that were visible when it was exported.
  Principals are named by group name or username, object types by `app_label.model`, so a file can move between
  NetBox instances. IDs are not used.
- **Import** uploads such a file. Within the file's scope, the file is the full desired state: listed cells are
  granted, unlisted cells are revoked. Anything outside the scope is left alone, so exporting only DCIM and
  importing it back never touches IPAM. Constrained and disabled entries keep whatever covers the cell today; the
  import never creates constraints or changes the enabled flag. If such an entry names a cell that nothing grants
  on the target, or that the target grants without constraints, the cell is left unchanged and the review lists it
  as a warning.
- Unknown principals or object types in the file are listed as errors in the review, and their entries are skipped;
  the import never creates groups or users. The result is staged and goes through the normal review.

## REST API

Under `/api/plugins/permissions-matrix/`, authenticated with normal NetBox API tokens:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `matrix/` | GET | The matrix as JSON: actions, rows, columns, cell states, covering permission IDs. Filters: `action`, `group_id`, `user_id`, `app_label`, `include_users`. |
| `principal/` | GET | One group's or user's cells for every action (the group tab). Parameters: `type`, `id`. |
| `plan/` | POST | Dry run: takes a change set, returns the plan and a version token. |
| `apply/` | POST | Takes a change set and the version token, applies it in one transaction, returns what was written. |
| `import/` | POST | Takes a YAML export, returns the cell changes it implies, with warnings and errors, for the normal review. |

A change set is a list of cell changes:

```json
{
  "changes": [
    {"principal": {"type": "group", "id": 3}, "object_type": "dcim.device", "action": "change", "granted": false}
  ]
}
```

## Permissions

The plugin enforces NetBox's own permissions on the objects it reads and writes:

- Viewing the matrix needs `users.view_objectpermission` and `users.view_group` (`users.view_user` for user
  columns). The menu item needs `users.view_objectpermission`.
- Applying a plan needs `users.add_objectpermission`, `users.change_objectpermission` or
  `users.delete_objectpermission` for each operation it contains, checked through NetBox's restricted querysets, so
  constraints on those permissions are honoured. If any operation is not allowed, nothing is written.
- Without any write permission the page is read-only: chips show states but do not toggle, no review button.

## Change history

NetBox does not keep change records for `ObjectPermission` (the model has no change logging). The plugin writes each
applied plan to the `netbox_permissions_matrix_plugin` Python logger at INFO level: who applied it, and every
operation. It does not add a model to store history, because that would break the "no storage of its own" goal.

## Navigation

NetBox lets plugins add their own top-level menu or items under "Plugins", but not items inside core menus. To put
"Permissions Matrix" right below "Permissions" in Admin > Authentication, the plugin's `ready()` inserts a
`MenuItem` into that menu group before NetBox builds its menus. If NetBox's menu ever changes shape so that the
group or the Permissions item cannot be found, the plugin logs a warning and falls back to an entry under
"Plugins". The `menu_placement` setting can force the fallback.

## Implementation notes

- No models, no migrations.
- The matrix page renders a shell; the data arrives as JSON from the same endpoint the API uses and is drawn by a
  small vanilla JavaScript module (no build step), so a few hundred rows times dozens of columns stays fast.
- The snapshot is loaded with a fixed number of queries (permissions with prefetched object types, groups and users),
  whatever the number of permissions.
- The version token is a hash of every permission assigned to any principal in the change set (including the ones
  the plan does not modify, because grant decisions depend on them), the names the plan gives, and the principals
  themselves. Apply plans again, so a name taken (or freed) meanwhile changes the names and refuses the apply, while
  other permissions created, renamed or deleted meanwhile do not.
- Permission checks on created permissions run inside the transaction: the new rows are re-read through
  `.restrict(user, "add")` and the transaction is rolled back on a miss, as NetBox's own views do.
- The menu insertion replaces the `items` tuple of the Authentication group in `ADMIN_MENU` and finds the
  Permissions item by its link (`users:objectpermission_list`).

## Settings

| Setting | Default | Meaning |
|---------|---------|---------|
| `new_permission_name` | `"{principal}_{actions}"` | Name template for simple permissions the plugin creates. `{principal}` is the group name or username as a lower-case slug, `{actions}` (or `{action}`) the action letters. Checked when NetBox starts: any other placeholder, or `.` or `[...]` on one, stops NetBox with an error naming it. |
| `menu_placement` | `"admin"` | `"admin"` puts the item below Permissions; `"plugins"` uses the Plugins menu. |
| `show_action_tabs` | `False` | Whether the page offers the single-action tabs next to All actions. |
| `show_users_by_default` | `False` | Whether user columns are shown when the page opens. |
| `hidden_apps` | `[]` | App labels whose object types are not shown as rows. |

## Testing

- `tests/`: pure pytest, no NetBox. The planner, export and import parsing, and the docs checks. The planner has
  exhaustive tests, including a property test that applies random change sets and checks that every untouched
  principal keeps exactly the access it had and every touched cell ends in the requested state.
- `tests_netbox/`: Django tests run inside NetBox 4.7: views, API, permission enforcement, the menu insertion, the
  group tab, apply and conflict detection.
