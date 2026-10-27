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
        # 4.7.0 and 4.7.1 wrote plaintext API tokens from background bulk requests into job results; the REST API is
        # driven by tokens. CI tests min_version and the latest patch.
        min_version = "4.7.2"
        # The last minor CI has passed on. Raise it once the integration tests pass on NetBox's next minor (the
        # "feature" job), so an upgraded NetBox refuses to load an untested plugin instead of failing at runtime.
        max_version = "4.7.99"
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

            from .conf import MENU_PLACEMENTS, get_setting
            from .core.planner import check_name_template

            try:
                check_name_template(get_setting("new_permission_name"))
            except ValueError as e:
                raise ImproperlyConfigured(str(e)) from None
            # Any other value would silently mean the Plugins menu.
            placement = get_setting("menu_placement")
            if placement not in MENU_PLACEMENTS:
                choices = ", ".join(f'"{p}"' for p in MENU_PLACEMENTS)
                raise ImproperlyConfigured(f"menu_placement must be one of {choices}, not {placement!r}.")

    config = PermissionsMatrixConfig
