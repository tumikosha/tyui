"""Plugin discovery + registration (the "Mifflin" catalog loader).

Two sources, in order:
1. Installed packages exposing the ``dunders.plugins`` entry-point group
   (pip/pipx-installed dunders).
2. Local files/packages under ``$XDG_CONFIG_HOME/dunders/dunders/`` — a ``.py``
   file or a package dir, each exposing a module-level ``plugin`` object. This
   is the dev / hand-install path.

Everything is best-effort: a plugin that fails to import or register is skipped
with no effect on the app, mirroring the file manager's fault-tolerant scans.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from dunders.config.user_config import config_dir
from dunders.core.plugins.api import PluginApi
from dunders.core.plugins.plugin import DunderPlugin


__all__ = ["discover_plugins", "load_plugins", "plugins_dir"]


def plugins_dir() -> Path:
    """``$XDG_CONFIG_HOME/dunders/dunders`` — the local plugin directory."""
    return config_dir() / "dunders"


def discover_plugins(extra_dir: Path | None = None) -> list[DunderPlugin]:
    """Return every discoverable plugin object (entry points + local dir)."""
    found: list[DunderPlugin] = []
    found.extend(_from_entry_points())
    found.extend(_from_dir(extra_dir if extra_dir is not None else plugins_dir()))
    return found


def load_plugins(api: PluginApi, *, extra_dir: Path | None = None) -> list[str]:
    """Discover and register every plugin against ``api``.

    Returns the names of plugins that registered successfully. Import or
    registration failures are swallowed (best-effort).
    """
    loaded: list[str] = []
    for plugin in discover_plugins(extra_dir):
        try:
            plugin.register(api)
        except Exception:
            continue
        loaded.append(getattr(plugin, "name", repr(plugin)))
    return loaded


def _from_entry_points() -> list[DunderPlugin]:
    try:
        from importlib.metadata import entry_points

        eps = entry_points(group="dunders.plugins")
    except Exception:
        return []
    out: list[DunderPlugin] = []
    for ep in eps:
        try:
            obj = ep.load()
            # An entry point may point at a plugin instance or a zero-arg
            # factory that returns one.
            out.append(obj() if callable(obj) and not _is_plugin(obj) else obj)
        except Exception:
            continue
    return out


def _from_dir(base: Path) -> list[DunderPlugin]:
    if not base.is_dir():
        return []
    out: list[DunderPlugin] = []
    for entry in sorted(base.iterdir()):
        plugin = _load_local(entry)
        if plugin is not None:
            out.append(plugin)
    return out


def _load_local(path: Path) -> DunderPlugin | None:
    if path.is_dir():
        target = path / "__init__.py"
        if not target.is_file():
            return None
        name = path.name
    elif path.suffix == ".py" and not path.name.startswith("_"):
        target = path
        name = path.stem
    else:
        return None
    try:
        spec = importlib.util.spec_from_file_location(f"dunders_plugin_{name}", target)
        if spec is None or spec.loader is None:
            return None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    except Exception:
        return None
    return getattr(module, "plugin", None)


def _is_plugin(obj: object) -> bool:
    return hasattr(obj, "register") and hasattr(obj, "name")
