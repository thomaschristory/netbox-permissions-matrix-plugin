# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Changed

- **The menu item moves to the Plugins menu by default** (`menu_placement` now defaults to `"plugins"`). Putting it
  below Permissions in Admin > Authentication edits NetBox's core menu, which has no plugin API, so it is now opt-in:
  set `menu_placement: "admin"` to keep the previous place. It still falls back to the Plugins menu, with a warning,
  when NetBox's Admin menu changes shape.
- NetBox does not start when `menu_placement` is neither `"plugins"` nor `"admin"`; before, any other value meant
  the Plugins menu without a word.

- The plugin requires NetBox 4.7.2 or later (`min_version`): 4.7.0 and 4.7.1 wrote plaintext API tokens from
  background bulk requests into job results. CI now tests 4.7.2 as well as the latest patch.
- The plugin declares `max_version = "4.7.99"`, so NetBox 4.8 refuses to load it until a release tested on 4.8
  raises the limit, instead of failing at runtime.
- The plugin's pages use NetBox's `ConditionalLoginRequiredMixin` for the login check, and keep NetBox's own
  `head` and `javascript` template blocks.

## [0.4.1] - 2026-10-20

### Fixed

- The who-can page shows constraints as JSON (`{"site__slug":"paris"}`), like the matrix and the review, instead of
  as Python dictionaries, in the effective access and in the cell tooltips.

## [0.4.0] - 2026-10-20

### Added

- App sections have letter toggles in each column: one gives or takes an action on every row of the app for that
  group or user only, for example every Core right for NOC. On the group tab and the single-action tabs, each column
  has the letter of its action.
- **Revert last** in the staged-changes bar, and Ctrl+Z (Cmd+Z), takes back the last change: a cell, a toggle, the
  gear panel, an import or a Discard, one step at a time.
- The staged-changes bar flashes briefly with each change.

## [0.3.0] - 2026-10-20

### Added

- Documentation: Disabled permissions page. How NetBox treats a disabled permission, how the matrix shows it, and
  what ticking, unticking, the toggles, the gear panel, export and import and the REST API do with it.

### Changed

- **Groups** and **Users** buttons replace the Columns button and the Users switch: each picks the columns of its
  kind. All groups and no users are shown at first.
- Export with `user_id` alone keeps every group. `groups=0` leaves groups out.

### Fixed

- A permission created in the same change set that deletes another can take the deleted one's name. It no longer
  gets a number (`noc_v 2`) because the name was still taken while the plan was worked out. The same goes for the
  name of a permission split off and then emptied again in the same change set (`shared (NOC) 2`).
- Groups the viewer cannot view are no longer named: the matrix's group markers, the who-can sources and the
  groups and users a permission is assigned to say "a group you cannot view" (or "a user you cannot view") instead.
- The who-can page counts access through groups the viewer cannot view, and says when it leaves out groups or users
  the viewer cannot view.
- Browsers no longer keep an old `matrix.js` or `matrix.css` after the files change between releases: their URLs
  carry a hash of the contents instead of the plugin version.
- A `new_permission_name` with an unknown placeholder, such as `{team}`, no longer makes every review that creates a
  permission fail with a 500. NetBox now refuses to start and the error names the placeholder.
  Attribute or index access, such as `{principal[2]}`, is refused the same way.
- Creating, renaming or deleting a permission of another group or user no longer forces a fresh review before
  apply. Apply is still refused when a name the review gives is taken meanwhile.
- Apply returns a 409 asking you to reload and review again when a group or user in the plan is deleted while it is
  written, instead of a server error. Nothing is written.
- Renaming a permission in the gear panel to a name already in use now shows a warning in the review with the name
  that will be used instead (`NOC | view 2`). Before, the number was added without a word.

## [0.2.0] - 2026-10-19

### Added

- All actions grid, now the matrix page: every action in one grid, one lettered chip per action in each cell, with
  per-action toggles in each column header, row and app section (`all V A C D ...`). `GET matrix/?action=*` returns
  it.
- `show_action_tabs` setting, off by default: brings back the View, Add, Change, Delete and custom action tabs next
  to All actions.
- Constraints page in the documentation: how NetBox constraints work, how the matrix shows them, how to set and
  remove them, with recipes.
- Gear panel lists the principal's permissions and edits any of them: name, description, enabled and constraints.
  Edits in the REST API can name a permission by `perm_id`.

### Changed

- New grants go into one simple permission per principal and set of actions, named after the actions:
  `noc_va` for view and add, `noc_vacd` for all four. The default `new_permission_name` is now
  `{principal}_{actions}`. Ticking or unticking an action moves the object type to the permission for its new set;
  a permission left with no object types takes the new set and keeps its ID, renamed if it still has its generated
  name.
- A disabled permission no longer receives new grants.
- Permissions named in the 0.1.0 style (`NOC | view`) keep being used and are renamed to the new style
  (`noc_va`) when their actions change. A `new_permission_name` set to the old default now gives `noc | va`-style
  names: switch it to `{principal}_{actions}`, or another pattern with `{actions}`.
- The gear panel no longer offers additional actions, groups or users; use the permission's NetBox page or the API.

## [0.1.0] - 2026-10-19

### Added

- Export the matrix as YAML (shown columns and rows, every action) and import such a file: within the file's scope
  the changes are staged for the normal review, nothing is written until Apply. Groups, users and object types are
  named, never numbered, so a file can move between NetBox instances. Also `POST import/` in the REST API.
- Matrix page in Admin > Authentication, right below Permissions: action tabs, search, app filter, user
  columns, column picker, bulk toggles, gear panel, staged changes with review and apply.
- Who can page per object type, and a Permissions Matrix tab on each group.
- Change planner: turns matrix cell changes into create, update and delete operations on NetBox's own
  permissions, splitting shared permissions so no other group or user changes access.
- REST API: `matrix/`, `principal/`, `plan/`, `apply/` and `import/` under `/api/plugins/permissions-matrix/`, with a
  version token against concurrent changes and NetBox permission checks on every operation. Read-only API tokens
  cannot plan, apply or import.
- Documentation site: installation, quick start, configuration, the matrix, how changes map to permissions, who can,
  group tab, export and import, permissions, REST API, limitations, troubleshooting and development.
- Project scaffold: plugin configuration, settings, CI, release and documentation workflows, development stack.

[Unreleased]: https://github.com/thomaschristory/netbox-permissions-matrix-plugin/compare/v0.4.1...HEAD
[0.4.1]: https://github.com/thomaschristory/netbox-permissions-matrix-plugin/compare/v0.4.0...v0.4.1
[0.4.0]: https://github.com/thomaschristory/netbox-permissions-matrix-plugin/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/thomaschristory/netbox-permissions-matrix-plugin/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/thomaschristory/netbox-permissions-matrix-plugin/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/thomaschristory/netbox-permissions-matrix-plugin/releases/tag/v0.1.0
