from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any, Callable


class EventEmitter:
    """Minimal EventEmitter matching the Node.js pattern."""

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable[..., Any]]] = defaultdict(list)

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        self._listeners[event].append(callback)

    def off(self, event: str, callback: Callable[..., Any]) -> None:
        try:
            self._listeners[event].remove(callback)
        except ValueError:
            pass

    def once(self, event: str, callback: Callable[..., Any]) -> None:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.off(event, wrapper)
            return callback(*args, **kwargs)
        self.on(event, wrapper)

    def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        for listener in self._listeners[event][:]:
            result = listener(*args, **kwargs)
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    pass

    def remove_all_listeners(self, event: str | None = None) -> None:
        if event is None:
            self._listeners.clear()
        else:
            self._listeners.pop(event, None)
