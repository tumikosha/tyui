"""DunderPlugin — the contract a plugin object satisfies.

A plugin is any object exposing ``name``, ``version`` and ``register(api)``.
Authors implement it against :class:`~dunders.core.plugins.api.PluginApi`,
imported from the stable ``dunders.sdk`` facade.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from dunders.core.plugins.api import PluginApi


__all__ = ["DunderPlugin"]


@runtime_checkable
class DunderPlugin(Protocol):
    name: str
    version: str

    def register(self, api: PluginApi) -> None:
        """Extend the app through ``api`` (register providers, subscribe to
        events, …). Called once at startup."""
        ...
