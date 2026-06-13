"""EventBus — a tiny synchronous pub/sub for plugin hooks.

Lets ironic/observer plugins (`__office__` playing a sound on copy, `__far__`
showing server distance) react to app events without the core knowing about
them. Best-effort: a handler that raises never breaks the emitter.

Event names are dotted strings, e.g. ``op.copy.done``, ``op.move.done``,
``op.delete.done``. The payload is event-specific (an ``OpResult`` for op.*).
"""

from __future__ import annotations

from collections.abc import Callable


__all__ = ["EventBus"]

Handler = Callable[[object], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = {}

    def on(self, event: str, handler: Handler) -> None:
        """Subscribe ``handler`` to ``event``."""
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, payload: object = None) -> None:
        """Notify every subscriber of ``event``. Handler errors are swallowed."""
        for handler in list(self._handlers.get(event, ())):
            try:
                handler(payload)
            except Exception:
                pass  # a misbehaving plugin must not break the app
