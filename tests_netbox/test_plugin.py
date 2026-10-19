from django.apps import apps
from django.test import SimpleTestCase


class PluginLoadTest(SimpleTestCase):
    def test_plugin_is_installed(self):
        config = apps.get_app_config("netbox_permissions_matrix_plugin")
        self.assertEqual(config.verbose_name, "Permissions Matrix")
        self.assertEqual(config.min_version, "4.7.0")
        self.assertIsNone(config.max_version)
