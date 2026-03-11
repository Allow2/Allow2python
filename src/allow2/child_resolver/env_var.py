from __future__ import annotations

import os
from typing import Any

from allow2.models import Child


class EnvVarResolver:
    """Resolves child from ALLOW2_CHILD_ID environment variable.
    Useful for automation scripts, CI, Raspberry Pi headless setups."""

    def __init__(self, *, env_var: str = "ALLOW2_CHILD_ID") -> None:
        self._env_var = env_var

    async def resolve(self, children: list[Child]) -> dict[str, Any] | None:
        raw = os.environ.get(self._env_var)
        if not raw:
            return None

        try:
            target_id = int(raw)
        except ValueError:
            return None

        for child in children:
            if child.id == target_id:
                return {"child_id": child.id, "child_name": child.name}

        return None
