from __future__ import annotations

from typing import Any

from allow2.models import Child


async def resolve(children: list[Child]) -> None:
    return None


class SelectorResolver:
    async def resolve(self, children: list[Child]) -> None:
        return None


def request_selection(child_shield: Any) -> None:
    if child_shield and hasattr(child_shield, "emit") and hasattr(child_shield, "get_children"):
        child_shield.emit("child-select-required", child_shield.get_children())
