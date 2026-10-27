import ast
import re
import tomllib
from pathlib import Path

from netbox.plugins import PluginConfig

import netbox_permissions_matrix_plugin
from netbox_permissions_matrix_plugin import compat, conf

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "netbox_permissions_matrix_plugin"


def test_version_is_pep440():
    assert re.fullmatch(r"\d+\.\d+\.\d+(\.dev\d+|(a|b|rc)\d+)?", netbox_permissions_matrix_plugin.__version__)


def test_config_is_defined_at_module_level():
    config = netbox_permissions_matrix_plugin.config
    assert config is netbox_permissions_matrix_plugin.PermissionsMatrixConfig
    assert issubclass(config, PluginConfig)
    assert config.name == conf.PLUGIN_NAME
    assert config.version == netbox_permissions_matrix_plugin.__version__
    assert config.default_settings is conf.DEFAULTS


def test_config_is_not_guarded():
    # The conftest stub makes netbox.plugins importable, so the test above also passes with a try/except import or an
    # `if PluginConfig` guard around the class; check the source instead.
    tree = ast.parse((PACKAGE / "__init__.py").read_text())
    assert not [node for node in tree.body if isinstance(node, ast.Try | ast.If)]
    top_level = [
        (type(node), getattr(node, "module", None) or getattr(node, "name", None) or ast.unparse(node.targets[0]))
        for node in tree.body
        if isinstance(node, ast.ImportFrom | ast.ClassDef | ast.Assign)
    ]
    assert (ast.ImportFrom, "netbox.plugins") in top_level
    assert (ast.ClassDef, "PermissionsMatrixConfig") in top_level
    assert (ast.Assign, "config") in top_level


def test_entry_point_names_the_config():
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["project"]["entry-points"]["netbox.plugins"] == {
        conf.PLUGIN_NAME: "netbox_permissions_matrix_plugin:config"
    }


def test_version_is_read_without_importing_the_package():
    # The build backend takes the version from version.py as text; it must stay a plain assignment, with no import
    # that would need NetBox.
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())
    assert pyproject["tool"]["hatch"]["version"] == {"path": "netbox_permissions_matrix_plugin/version.py"}
    tree = ast.parse((PACKAGE / "version.py").read_text())
    assert [type(node) for node in tree.body] == [ast.Assign]


def test_default_menu_placement_is_valid():
    assert conf.DEFAULTS["menu_placement"] in conf.MENU_PLACEMENTS


def _version(value):
    return tuple(int(part) for part in value.split("."))


def test_compat_checked_against_matches_version_bounds():
    # The release steps in docs/development.md add each tested NetBox to this line when max_version is raised.
    match = re.search(r"^Checked against NetBox: (.+)\.$", compat.__doc__, re.MULTILINE)
    assert match, "compat.py's docstring has no 'Checked against NetBox: ...' line"
    checked = [_version(v) for v in match.group(1).split(", ")]
    assert checked == sorted(set(checked))
    min_version = _version(netbox_permissions_matrix_plugin.config.min_version)
    max_version = _version(netbox_permissions_matrix_plugin.config.max_version)
    assert checked[0] == min_version
    assert all(v <= max_version for v in checked)
    # Every minor up to max_version has been checked.
    assert checked[-1][:2] == max_version[:2]
    assert '"Checked against" line' in (ROOT / "docs" / "development.md").read_text()
