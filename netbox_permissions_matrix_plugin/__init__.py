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

        def ready(self):
            super().ready()
            self.check_settings()

        @staticmethod
        def check_settings():
            # A bad new_permission_name would only fail when a review names a new permission, as a 500; stop NetBox
            # from starting instead, with the reason.
            from django.core.exceptions import ImproperlyConfigured

            from .conf import get_setting
            from .core.planner import check_name_template

            try:
                check_name_template(get_setting("new_permission_name"))
            except ValueError as e:
                raise ImproperlyConfigured(str(e)) from None

    config = PermissionsMatrixConfig
