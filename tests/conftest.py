"""Lets the pure tests import the package without NetBox.

The package's __init__ defines the plugin config at module level, so importing anything under it imports
netbox.plugins. Outside NetBox, a stub with an empty PluginConfig stands in for it; inside NetBox the real one is
used.
"""

import importlib.util
import sys
import types

if importlib.util.find_spec("netbox") is None:

    class PluginConfig:
        """Stand-in for netbox.plugins.PluginConfig: the plugin's config class only needs a base to subclass."""

        def ready(self):
            pass

    netbox = types.ModuleType("netbox")
    netbox.__path__ = []
    plugins = types.ModuleType("netbox.plugins")
    plugins.PluginConfig = PluginConfig
    netbox.plugins = plugins
    sys.modules["netbox"] = netbox
    sys.modules["netbox.plugins"] = plugins
