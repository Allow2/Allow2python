from __future__ import annotations

import json
import math
import os
import time
from pathlib import Path
from typing import Any

from allow2.events import EventEmitter

DEFAULT_GRACE_PERIOD = 300
DEFAULT_CACHE_PATH = str(Path.home() / ".allow2" / "cache.json")


class OfflineHandler(EventEmitter):
    """Caches last successful check result. Enforces grace period.
    After grace: deny-by-default. Cache persisted to ~/.allow2/cache.json."""

    def __init__(
        self,
        *,
        grace_period: int = DEFAULT_GRACE_PERIOD,
        cache_path: str | None = None,
    ) -> None:
        super().__init__()
        self._grace_period = grace_period
        self._cache_path = cache_path or DEFAULT_CACHE_PATH
        self._cached: dict[str, Any] | None = None
        self._loaded = False

    async def cache_result(self, check_result: dict[str, Any]) -> None:
        self._cached = {
            "result": check_result,
            "timestamp": time.time() * 1000,
        }
        await self._write_disk(self._cached)

    async def get_cached_result(self) -> dict[str, Any] | None:
        if not self._loaded:
            await self._load_disk()
        if self._cached is None:
            return None
        return self._cached["result"]

    async def get_grace_elapsed(self) -> float:
        if not self._loaded:
            await self._load_disk()
        if self._cached is None:
            return math.inf
        return (time.time() * 1000 - self._cached["timestamp"]) / 1000

    async def is_in_grace_period(self) -> bool:
        elapsed = await self.get_grace_elapsed()
        if elapsed < self._grace_period:
            self.emit("offline-grace", elapsed)
            return True
        return False

    async def should_deny(self) -> bool:
        elapsed = await self.get_grace_elapsed()
        if elapsed >= self._grace_period:
            self.emit("offline-deny")
            return True
        return False

    async def _write_disk(self, data: dict[str, Any]) -> None:
        try:
            dir_path = os.path.dirname(self._cache_path)
            os.makedirs(dir_path, mode=0o700, exist_ok=True)
            with open(self._cache_path, "w") as f:
                json.dump(data, f)
            os.chmod(self._cache_path, 0o600)
        except OSError:
            pass

    async def _load_disk(self) -> None:
        self._loaded = True
        try:
            with open(self._cache_path) as f:
                parsed = json.load(f)
            if (
                isinstance(parsed, dict)
                and "result" in parsed
                and isinstance(parsed.get("timestamp"), (int, float))
            ):
                self._cached = parsed
        except (OSError, json.JSONDecodeError):
            pass
