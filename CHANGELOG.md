# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added

- All actions tab, now the default: every action in one grid, one lettered chip per action in each cell, with
  per-action toggles in each column header. `GET matrix/?action=*` returns it.
- Gear panel lists the principal's permissions and edits any of them: name, description, enabled and constraints.
  Edits in the REST API can name a permission by `perm_id`.

### Changed

- New grants go into one simple permission per principal and set of actions, named after the actions:
  `noc_va` for view and add, `noc_vacd` for all four. The default `new_permission_name` is now
  `{principal}_{actions}`. Ticking or unticking an action moves the object type to the permission for its new set;
  a permission left with no object types takes the new set and keeps its ID, renamed if it still has its generated
  name.
- A disabled permission no longer receives new grants.
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

[Unreleased]: https://github.com/thomaschristory/netbox-permissions-matrix-plugin/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/thomaschristory/netbox-permissions-matrix-plugin/releases/tag/v0.1.0
