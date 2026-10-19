# Constraints

A constraint limits a permission to some objects: "change devices, but only at the Paris site". This page explains
how NetBox constraints work, how the matrix shows them, and how to set, change and remove them from the matrix.

## How NetBox constraints work

A constraint belongs to a **permission**, not to a cell. It is a filter on the objects the permission applies to,
written as JSON:

```json
{"site__slug": "paris"}
```

The keys are Django ORM lookups on the model's fields, as NetBox's own permission form expects: a field name,
optionally followed by `__` and a related field or a lookup such as `__in` or `__startswith`. They are not the
filter names of the REST API or the list views, although many look the same.

- **One object**: every key must match (AND). `{"site__slug": "paris", "status": "active"}` is active objects at Paris.
- **A list of objects**: any of them may match (OR). `[{"site__slug": "paris"}, {"site__slug": "lyon"}]` is objects
  at Paris or at Lyon.
- **`$user`** stands for the user making the request. `{"user": "$user"}` on tokens means "the user's own tokens".
- **No constraints** (empty, `null`, `{}` or `[]`) means every object.

The same constraint applies to **every object type and every action** of its permission. A permission granting view
and change on Device and Rack with `{"site__slug": "paris"}` gives view and change on Paris devices and Paris racks.
So every object type in a constrained permission must have the fields the constraint names: `{"tenant__slug":
"acme"}` makes sense on Device, not on Circuit Type, which has no tenant.

When several permissions cover the same cell, NetBox combines them with OR: one unconstrained permission is enough
for full access, whatever constraints the others carry.

## How the matrix shows them

A chip (or box) is **half filled** when only constrained permissions cover it: the group or user has the action on
some objects of that type, not all. Hover it to see the permissions and their constraints. If any enabled permission
without constraints also covers it, the chip is simply granted.

The [who can](who-can.md) page lists constrained access with its constraints, for every user who gets it.

## Setting a constraint

Constraints are set per permission, in the [gear panel](matrix.md#the-gear-panel):

1. Click the gear next to the group or user's name.
2. Open the permission to constrain. Check the summary line first: it says which actions the permission has and how
   many object types it covers. The constraint will apply to all of them.
3. Type the constraint in **Constraints**, for example `{"site__slug": "paris"}`.
4. Click **Stage changes**, then **Review changes**. The review shows the constraints before and after, and warns
   if the permission was a simple one (see below).
5. Click **Apply**.

The plugin checks the constraint the same way NetBox's own permission form does: it must be an object or a list of
objects, and it is run as a test query against every object type of the permission. An unknown field fails the
review with a message such as `noc_vc: invalid filter for circuits.circuittype: Cannot resolve keyword 'tenant' into
field. Choices are: ...`, and nothing is written.

!!! warning "Shared permissions"
    A permission assigned to several groups or users says so at the top of its form. A constraint on it limits all
    of them, not only the column you opened the panel from.

## Constraints and simple permissions

The matrix grows and shrinks its own **simple** permissions, such as `noc_vc`: one group or user, enabled, no
constraints (see [How changes map to permissions](changes.md)). Adding a constraint to one of them takes it out of
that pool:

- the matrix stops adding object types to it or moving object types out of it when you tick chips;
- the next time you tick view and change for NOC on another object type, a new `noc_vc 2` is created for it, without
  constraints;
- unticking a chip the constrained permission covers still removes it from that permission, as for any permission.

Removing the constraint later (empty the box, stage and apply) makes it a simple permission again. If two simple
permissions then have the same actions, new grants go into the one with the lowest ID.

## Recipes

### Constrained access to one object type

To let NOC change devices at Paris only, while NOC has full change access elsewhere:

1. Check which permission grants it: open the gear panel and look at the object type count. If NOC's `noc_vc` covers
   Device and other object types, a constraint on it would apply to all of them.
2. If it covers more than Device, untick change on Device in the matrix and apply, then create a dedicated
   permission on NetBox's permission page (**Admin > Authentication > Permissions**: Device, the change action, the
   NOC group and the constraint). NOC keeps full change access on everything else through `noc_vc`.
3. If it covers only Device, set the constraint on it in the gear panel.

The matrix does not split a permission to isolate one object type: a constraint always covers the whole permission.

### Several sites

Use a list for OR: `[{"site__slug": "paris"}, {"site__slug": "lyon"}]`, or one lookup with `__in`:
`{"site__slug__in": ["paris", "lyon"]}`.

### The user's own objects

`{"user": "$user"}` on Token gives each user access to their own tokens only. `$user` is replaced by the user making
the request when NetBox checks the permission, so one permission serves everyone it is assigned to.

### Removing a constraint

Open the permission in the gear panel, empty **Constraints**, stage and apply. The chips it covers turn from half
filled to granted.

## What the matrix never does with constraints

- Ticking a chip never adds a constraint. Ticking a half-filled chip adds an **unconstrained** grant beside the
  constrained one, so the chip becomes granted; the constrained permission is left as it is.
- Unticking removes the cell from every permission that covers it, constrained or not. When that permission keeps
  other cells, the parts kept are split into new permissions that copy its constraints, so nothing gains access.
- An [import](export-import.md) never creates or changes constraints: constrained cells in the file are reported,
  not applied.
