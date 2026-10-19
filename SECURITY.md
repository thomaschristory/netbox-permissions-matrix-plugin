# Security policy

## Supported versions

Only the latest release gets security fixes while the plugin is below 1.0.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting:
[Report a vulnerability](https://github.com/thomaschristory/netbox-permissions-matrix-plugin/security/advisories/new)
(**Security > Report a vulnerability** on the repository). Only the maintainer sees the report, and the fix and an
advisory are published together.

The plugin edits NetBox permissions, so a bug that lets a user grant access they should not be able to grant is a
security issue. See the [permissions page](https://thomaschristory.github.io/netbox-permissions-matrix-plugin/permissions/)
of the documentation for the checks the plugin makes.
