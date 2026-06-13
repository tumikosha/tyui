"""dunders.core.plugins — plugin runtime (api, events, discovery).

Plugin *authors* import from the stable ``dunders.sdk`` facade, not from here.
"""

from dunders.core.plugins.api import PluginApi
from dunders.core.plugins.events import EventBus
from dunders.core.plugins.loader import discover_plugins, load_plugins, plugins_dir
from dunders.core.plugins.plugin import DunderPlugin


__all__ = [
    "PluginApi",
    "EventBus",
    "DunderPlugin",
    "discover_plugins",
    "load_plugins",
    "plugins_dir",
]
