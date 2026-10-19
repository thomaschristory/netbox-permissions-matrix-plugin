import re

import netbox_permissions_matrix_plugin
from netbox_permissions_matrix_plugin import conf


def test_version_is_pep440():
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+|(a|b|rc)\d+)?", netbox_permissions_matrix_plugin.__version__)


def test_importable_without_netbox():
    # Outside NetBox there is no PluginConfig, so no config either; the pure modules still import.
    assert getattr(netbox_permissions_matrix_plugin, "config", None) is None


def test_default_menu_placement_is_valid():
    assert conf.DEFAULTS["menu_placement"] in conf.MENU_PLACEMENTS
