# Development

## Requirements

- [uv](https://docs.astral.sh/uv/) for the unit tests, linting and the documentation.
- Docker with Compose for the development stack and the integration tests.

## The development stack

```bash
make dev    # builds NetBox 4.7 with the plugin mounted, and starts it on http://localhost:8000
make seed   # sample groups, users and overlapping permissions (safe to run again)
```

Log in as `admin` / `admin`. If port 8000 is taken, pick another one: `NETBOX_PORT=8010 make dev`, and pass the same
variable to the other `make` targets that talk to the stack.

The plugin directory is mounted into the container:

- Python and template changes need a restart (`make restart`). Templates are cached because the stack runs with
  `DEBUG` off.
- Static files (`matrix.js`, `matrix.css`) are served from the mount. Their URLs carry `?v=` and a hash of their
  contents, so a normal reload picks up an edit.

`make logs` follows NetBox's log; `make down` stops the stack.

## Tests

```bash
make test          # tests/: pure pytest, no NetBox needed (netbox.plugins is stubbed)
make test-netbox   # tests_netbox/: Django tests inside the running stack
make lint          # ruff check and ruff format --check
make format        # fix what ruff can
```

- `tests/` covers the planner, the cell states, the version token, export and import parsing, and the documentation
  itself (no em dashes, every page in the navigation, internal links, configuration examples). The planner also has
  property-based tests that check, on random permission sets, that no principal other than the one changed ever gains
  or loses access.
- `tests_netbox/` covers the loader, the REST API, the views, the menu and export and import against a real NetBox
  and PostgreSQL.

CI runs both on every pull request, the integration tests against the lowest supported NetBox (`min_version`), the
latest 4.7 patch and NetBox's `feature` branch (allowed to fail, as an early warning, and run with `max_version`
lifted).

## Layout

| Path | What |
|------|------|
| `netbox_permissions_matrix_plugin/core/` | Pure Python: the snapshot model, cell states, the planner, the version token, export and import. No Django imports. |
| `loader.py` | Reads NetBox's permissions, groups and users into a snapshot, in a fixed number of queries. |
| `service.py` | What the page, the group tab, export and import and the API share: access checks, the matrix, plans. |
| `applier.py` | Writes a plan in one transaction, checking the user's permissions before and after each write. |
| `api/` | The REST API. |
| `views.py`, `templates/`, `static/` | The pages. `matrix.js` draws the matrix from the API, without a build step. |
| `dev/` | The development stack and the seed script. |

The design and the rules the planner follows are in [Design](DESIGN.md) and
[How changes map to permissions](changes.md).

## Documentation

```bash
make docs         # strict build into site/
make docs-serve   # live preview on http://localhost:8001
```

Write plain, British-leaning prose, without em dashes: a test enforces it. Add every new page to the `nav` in
`mkdocs.yml`, another test checks that too.

## Packaging and releases

```bash
make dist   # build the sdist and wheel, then check them with twine and dev/scripts/check_dist.py
```

Releases follow [Keep a Changelog](changelog.md) and Conventional Commits:

1. Bump `netbox_permissions_matrix_plugin/version.py` and move the changelog's Unreleased section under the new
   version and date. If `min_version` or `max_version` changed, update the compatibility tables in `README.md` and
   `docs/index.md`. Raise `max_version` to the next minor (for example `4.8.99`) only once the `feature` integration
   job passes on it.
2. Merge, then tag `vX.Y.Z` on main and push the tag.
3. The `release` workflow builds and publishes to PyPI with trusted publishing; the `docs` workflow publishes this
   site.
4. Create the GitHub release with the changelog section as notes.
