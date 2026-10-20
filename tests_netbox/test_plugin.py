from unittest import mock

from django.apps import apps
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.test import SimpleTestCase, override_settings
from netbox.plugins import PluginConfig

from netbox_permissions_matrix_plugin.conf import PLUGIN_NAME


def plugin_settings(**values):
    return {**settings.PLUGINS_CONFIG, PLUGIN_NAME: {**settings.PLUGINS_CONFIG[PLUGIN_NAME], **values}}


class PluginLoadTest(SimpleTestCase):
    def test_plugin_is_installed(self):
        config = apps.get_app_config("netbox_permissions_matrix_plugin")
        self.assertEqual(config.verbose_name, "Permissions Matrix")
        self.assertEqual(config.min_version, "4.7.0")
        self.assertIsNone(config.max_version)


class SettingsCheckTest(SimpleTestCase):
    def check(self):
        apps.get_app_config(PLUGIN_NAME).check_settings()

    def test_default_settings_pass(self):
        self.check()

    def test_unknown_placeholder_in_new_permission_name_stops_startup(self):
        bad = plugin_settings(new_permission_name="{principal}_{team}")
        with (
            override_settings(PLUGINS_CONFIG=bad),
            self.assertRaisesMessage(ImproperlyConfigured, "unknown placeholder {team}"),
        ):
            self.check()

    def test_custom_new_permission_name_passes(self):
        with override_settings(PLUGINS_CONFIG=plugin_settings(new_permission_name="{actions} for {principal}")):
            self.check()

    def test_ready_checks_settings(self):
        # NetBox's own ready() registers menus and URLs; it is skipped so only the plugin's check runs again.
        bad = plugin_settings(new_permission_name="{principal}_{team}")
        with (
            mock.patch.object(PluginConfig, "ready"),
            override_settings(PLUGINS_CONFIG=bad),
            self.assertRaisesMessage(ImproperlyConfigured, "unknown placeholder {team}"),
        ):
            apps.get_app_config(PLUGIN_NAME).ready()
