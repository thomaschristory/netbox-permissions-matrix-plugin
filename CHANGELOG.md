# Changelog

All notable changes to this project are documented here. Format: [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
versioning: [SemVer](https://semver.org/).

## [Unreleased]

### Added

- Export the matrix as YAML (shown columns and rows, every action) and import such a file: within the file's scope
  the changes are staged for the normal review, nothing is written until Apply. Groups, users and object types are
  named, never numbered, so a file can move between NetBox instances. Also `POST import/` in the REST API.
- Matrix page in Admin > Authentication, right below Permissions: action tabs, search, app filter, user
  columns, column picker, bulk toggles, gear panel, staged changes with review and apply.
- Who can page per object type, and a Permissions Matrix tab on each group.
- Change planner: turns matrix cell changes into create, update and delete operations on NetBox's own
  permissions, splitting shared permissions so no other group or user changes access.
- REST API: `matrix/`, `plan/` and `apply/` under `/api/plugins/permissions-matrix/`, with a version token against
  concurrent changes and NetBox permission checks on every operation.
- Project scaffold: plugin configuration, settings, CI, release and documentation workflows, development stack.
