# Installation

## Requirements

| Component | Version |
|-----------|---------|
| NetBox | 4.7.2 to 4.7.x |
| Python | 3.12, 3.13 or 3.14 (whatever your NetBox runs on) |

Outside that range NetBox still starts, but without the plugin: it only logs a warning, `Unable to load plugin
netbox_permissions_matrix_plugin: ...`. When you upgrade NetBox to a new minor version, upgrade the plugin first to a
release that supports it.

The plugin has no dependencies of its own beyond NetBox, and it adds no database tables, so there is nothing to
migrate.

## Bare metal or VM

Install the package into NetBox's virtual environment:

```bash
source /opt/netbox/venv/bin/activate
pip install netbox-permissions-matrix-plugin
```

To keep it across NetBox upgrades, add it to `local_requirements.txt`:

```bash
echo netbox-permissions-matrix-plugin >> /opt/netbox/local_requirements.txt
```

Enable it in `/opt/netbox/netbox/netbox/configuration.py`:

```python
PLUGINS = ["netbox_permissions_matrix_plugin"]
```

Collect the static files (the matrix page ships a small script and stylesheet) and restart NetBox:

```bash
cd /opt/netbox/netbox
python manage.py collectstatic --no-input
sudo systemctl restart netbox netbox-rq
```

## netbox-docker

Add the package to `plugin_requirements.txt`:

```text
netbox-permissions-matrix-plugin
```

Enable it in `configuration/plugins.py`:

```python
PLUGINS = ["netbox_permissions_matrix_plugin"]
```

Then rebuild the image as described in the
[netbox-docker plugin guide](https://github.com/netbox-community/netbox-docker/wiki/Using-Netbox-Plugins). The
image runs `collectstatic` on start.

## Check that it works

Log in as a user who can view permissions and open **Plugins > Permissions Matrix**. If the item is missing, see
[Troubleshooting](troubleshooting.md#the-menu-item-is-missing), and check **Admin > System > Plugins** that the plugin
is listed.

## Uninstalling

Remove the plugin from `PLUGINS`, restart NetBox, then `pip uninstall netbox-permissions-matrix-plugin`. The
permissions it created or changed are ordinary NetBox permissions and keep working.
