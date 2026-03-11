from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from allow2.models import Child


@runtime_checkable
class ChildResolver(Protocol):
    async def resolve(self, children: list[Child]) -> dict[str, Any] | None: ...
