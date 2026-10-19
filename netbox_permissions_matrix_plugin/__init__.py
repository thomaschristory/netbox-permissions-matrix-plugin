from .version import __version__

try:
    from netbox.plugins import PluginConfig
except ImportError:  # imported outside NetBox (pure unit tests, build tools)
    PluginConfig = None

if PluginConfig is not None:
    from .conf import DEFAULTS

    class PermissionsMatrixConfig(PluginConfig):
        name = "netbox_permissions_matrix_plugin"
        verbose_name = "Permissions Matrix"
        description = "Show and edit NetBox object permissions as a matrix of object types and groups"
        version = __version__
        author = "Thomas Christory"
        author_email = "9317624+thomaschristory@users.noreply.github.com"
        base_url = "permissions-matrix"
        min_version = "4.7.0"
        # No max_version: the plugin only uses the stable permission model, and CI also runs against NetBox's next
        # release.
        required_settings = []
        default_settings = DEFAULTS

    config = PermissionsMatrixConfig
