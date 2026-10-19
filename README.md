# netbox-permissions-matrix-plugin

[![ci](https://github.com/thomaschristory/netbox-permissions-matrix-plugin/actions/workflows/ci.yml/badge.svg)](https://github.com/thomaschristory/netbox-permissions-matrix-plugin/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/netbox-permissions-matrix-plugin)](https://pypi.org/project/netbox-permissions-matrix-plugin/)
[![Python](https://img.shields.io/pypi/pyversions/netbox-permissions-matrix-plugin)](https://pypi.org/project/netbox-permissions-matrix-plugin/)

A NetBox plugin that shows NetBox's object permissions as a matrix: object types down the side, groups (and
optionally users) across the top, one checkbox per cell for the selected action. Ticking and unticking cells edits
NetBox's own permissions, with a review of every change before it is written.

**Documentation: https://thomaschristory.github.io/netbox-permissions-matrix-plugin/**

> **Status: pre-release.** Below 1.0, read the review dialog before applying changes.

## Features

- One page answers "what can this group do?" and "who can change prefixes?".
- View, Add, Change, Delete and custom action tabs; bulk toggles per row, app and column.
- Edits native `ObjectPermission` records only. No models, no migrations; uninstalling leaves a normal setup.
- Safe with shared permissions: a change for one group never changes another group's access.
- Stage, review, apply: every created, changed or deleted permission is shown first and written in one transaction.
- Who can page per object type, and a Permissions Matrix tab on each group.
- Export to YAML and import back, on the same NetBox or another one, through the same review.

## Compatibility

| Plugin | NetBox | Python |
|--------|--------|--------|
| 0.1 | 4.7.0 and later | 3.12 to 3.14 |

## Quick start

```bash
pip install netbox-permissions-matrix-plugin
```

```python
# configuration.py
PLUGINS = ["netbox_permissions_matrix_plugin"]
```

Run `python manage.py collectstatic --no-input`, restart NetBox and open **Admin > Authentication > Permissions
Matrix**.

## Documentation

- [Installation](https://thomaschristory.github.io/netbox-permissions-matrix-plugin/installation/)
- [Quick start](https://thomaschristory.github.io/netbox-permissions-matrix-plugin/quickstart/)
- [Configuration](https://thomaschristory.github.io/netbox-permissions-matrix-plugin/configuration/)
- [Design](https://thomaschristory.github.io/netbox-permissions-matrix-plugin/DESIGN/)

## Development

```bash
make dev           # NetBox 4.7 with the plugin on http://localhost:8000 (admin / admin)
make seed          # sample groups, users and overlapping permissions
make test          # unit tests, no NetBox needed
make test-netbox   # integration tests inside the dev stack
make lint          # ruff
make docs          # build the documentation site
```

## License

Apache-2.0, see [LICENSE](https://github.com/thomaschristory/netbox-permissions-matrix-plugin/blob/main/LICENSE).
