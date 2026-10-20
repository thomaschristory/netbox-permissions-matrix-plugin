# REST API

Everything the matrix page does goes through the endpoints under `/api/plugins/permissions-matrix/`. Use them to
script permission changes with the same safety rules as the page: plan first, review, then apply with the token the
plan returned.

Authenticate as for any NetBox API call, with a token:

```bash
export NETBOX=https://netbox.example.com
export TOKEN="nbt_xxxxxxxx.yyyyyyyy"
curl -s -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" "$NETBOX/api/plugins/permissions-matrix/matrix/?action=change"
```

The [same permissions](permissions.md) as on the page apply. `plan/` and `apply/` also need a token with
**Write enabled** set: a read-only token can read the matrix but not plan or apply changes.

## `GET matrix/`

The matrix for one action, or for every action at once.

| Parameter | Default | Meaning |
|-----------|---------|---------|
| `action` | `view` | The action: `view`, `add`, `change`, `delete`, a registered custom action, or any other action name. `*` returns every action (see below). |
| `include_users` | the `show_users_by_default` setting | `true` adds a column for every user with a permission assigned directly. |
| `group_id` | all groups | Only these groups. Repeat the parameter for several. |
| `user_id` | | These users, whether or not they have direct permissions. Implies user columns. |
| `app_label` | all apps | Only rows of these apps. Repeat for several. |

The response:

```json
{
  "action": "change",
  "can_edit": true,
  "actions": [{"name": "view", "label": "View", "custom": false, "freeform": false, "help_text": ""}],
  "rows": [{"object_type": "dcim.device", "app_label": "dcim", "app_name": "DCIM", "label": "Device", "enabled": true}],
  "columns": [
    {"type": "group", "id": 1, "key": "group:1", "name": "NOC", "simple": null, "others": []}
  ],
  "cells": {
    "group:1": {
      "dcim.device": {"state": "granted", "perms": [{"id": 4, "name": "NOC-RW", "enabled": true, "constrained": false}]}
    }
  }
}
```

- `cells` lists only cells something covers; a missing cell is `none`.
- `state` is `granted`, `constrained`, `disabled` or `none`; see [Cell states](matrix.md#cell-states).
- A user cell can carry `"inherited": {"state": "granted", "groups": ["NOC"]}`: access through group membership,
  which the user column never edits.
- `columns[].simple` is the principal's permission holding only this one action, unconstrained, if there is one,
  and `columns[].others` every other permission granting it the action. This is narrower than a simple permission
  in [How changes map to permissions](changes.md): `noc_va` is simple there but appears under `others` for view.
- Permission objects in `perms`, `simple` and `others` also carry `description`, `actions`, `object_types`,
  `constraints`, `principals` and `url`.

With `action=*` the response has `"action": "*"` and three differences:

- `cells` has one more level, the action: `cells["group:1"]["dcim.device"]["change"]`.
- `rows[].enabled_actions` lists the actions that apply to the row, in place of `rows[].enabled`.
- `columns[].perms` lists every permission assigned to the principal, in place of `simple` and `others`.

## `GET principal/`

One group's or user's cells for every action, as the [group tab](group-tab.md) shows them.

| Parameter | Meaning |
|-----------|---------|
| `type` | `group` or `user`. |
| `id` | The group's or user's ID. Unknown, or not visible to you, gives HTTP 404. |

The response has `principal` (`type`, `id`, `key`, `name`), `can_edit`, `actions` and `rows` as for `matrix/`
(rows carry `enabled_actions`), `columns` keyed by action name, each with `simple` and `others` as above, and
`cells` keyed by object type then action: `cells["dcim.device"]["change"]`.

## Change sets

`plan/` and `apply/` take the same body:

```json
{
  "changes": [
    {"principal": {"type": "group", "id": 1}, "object_type": "dcim.site", "action": "change", "granted": false},
    {"principal": {"type": "user", "id": 7}, "object_type": "ipam.prefix", "action": "view", "granted": true}
  ],
  "edits": [
    {"principal": {"type": "group", "id": 1}, "perm_id": 12, "constraints": {"tenant__slug": "acme"}}
  ]
}
```

- `changes`: cells to grant (`true`) or revoke (`false`). If a cell appears twice, the last entry wins.
- `edits`: changes to one of a principal's permissions, as in the [gear panel](matrix.md#the-gear-panel). Give
  `perm_id`, the ID of a permission assigned to the principal. The older form with `action` instead still works,
  but only finds a permission holding that one action and nothing else, unconstrained: with permissions named by
  action set (`noc_va`), it usually finds nothing and the plan warns. Give one of `perm_id` and `action`, not both.
  An unknown `perm_id`, or a permission also assigned to groups or users you cannot see, is refused with HTTP 400. Optional fields: `name`, `description`, `enabled`, `constraints` (an object, a list of
  objects, or `null` to remove them), `add_actions`, `add_groups`, `add_users` (IDs). An edit naming a permission
  not assigned to the principal is left out, with a warning.

`object_type` must be one NetBox allows in a permission. Unknown groups or users, invalid action names and invalid
constraints are refused with HTTP 400.

## `POST plan/`

A dry run. Nothing is written.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$NETBOX/api/plugins/permissions-matrix/plan/" \
  -d '{"changes": [{"principal": {"type": "group", "id": 1}, "object_type": "dcim.site", "action": "change", "granted": false}]}'
```

```json
{
  "token": "3f1c...",
  "warnings": [],
  "operations": [
    {"op": "update", "key": "4", "id": 4, "before": {"name": "NOC-RW"}, "after": {"name": "NOC-RW"},
     "affects": [{"type": "group", "id": 1, "name": "NOC"}],
     "reasons": ["Remove NOC, who loses change dcim.site; other assignees unchanged"]},
    {"op": "create", "key": "new-1", "id": null, "before": null, "after": {"name": "NOC-RW (NOC)"},
     "affects": [{"type": "group", "id": 1, "name": "NOC"}],
     "reasons": ["Keep what NOC had from NOC-RW, without change dcim.site"]}
  ]
}
```

`before` and `after` are full permission objects (shortened above). `affects` lists the principals whose access the
operation changes. The [planning rules](changes.md) explain why each operation is there.

## `POST apply/`

The same body plus the `token` from `plan/`:

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$NETBOX/api/plugins/permissions-matrix/apply/" \
  -d '{"changes": [...], "token": "3f1c..."}'
```

The server plans the change set again and compares tokens. The response is the plan plus `written`, the list of
permissions created, changed and deleted (`op`, `id`, `name`).

| Status | Meaning |
|--------|---------|
| 200 | Applied. Everything in `written` is saved. |
| 400 | The change set is invalid, or `token` is missing. |
| 403 | The token is not write-enabled, you may not use the matrix, or not add, change or delete one of the permissions in the plan. Nothing was written. |
| 409 | A permission the plan depends on changed after `plan/`, a name the plan gives was taken, or a group or user in it was deleted during the apply. Nothing was written: plan again. |

The whole apply runs in one database transaction, with the permission table locked against other writers, so it
either applies completely or not at all.

## `POST import/`

Reads a file made by [export](export-import.md) and returns the cell changes that would make it true. Nothing is
written: send the changes to `plan/` and `apply/`.

```bash
curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  "$NETBOX/api/plugins/permissions-matrix/import/" \
  -d "$(jq -n --rawfile yaml matrix.yaml '{yaml: $yaml}')"
```

```json
{
  "changes": [
    {"principal": {"type": "group", "id": 2}, "name": "Ops", "object_type": "dcim.site", "action": "view",
     "granted": false}
  ],
  "warnings": [],
  "errors": ["Unknown group 'Ghosts': its entries are skipped."]
}
```

Each change has the shape `plan/` takes, plus `name` for display, which `plan/` ignores. Post the list as `changes`.

| Status | Meaning |
|--------|---------|
| 200 | The file was read. `errors` lists skipped entries, `warnings` cells left unchanged. |
| 400 | `yaml` is missing or empty, the text is not valid YAML, or it uses anchors and aliases. |
| 403 | The token is not write-enabled, or you may not add, change or delete permissions. |
