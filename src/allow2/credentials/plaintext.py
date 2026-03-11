from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_PATH = str(Path.home() / ".allow2" / "credentials.json")


class PlaintextBackend:
    """Stores credentials as JSON in ~/.allow2/credentials.json.
    File permissions: 0o600. Directory permissions: 0o700."""

    def __init__(self, *, path: str | None = None) -> None:
        self._path = path or DEFAULT_PATH

    async def store(self, data: dict[str, Any]) -> None:
        dir_path = os.path.dirname(self._path)
        os.makedirs(dir_path, mode=0o700, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(self._path, 0o600)

    async def load(self) -> dict[str, Any] | None:
        try:
            with open(self._path) as f:
                return json.load(f)
        except FileNotFoundError:
            return None

    async def clear(self) -> None:
        try:
            os.unlink(self._path)
        except FileNotFoundError:
            pass

    async def load_last_used(self) -> dict[str, str]:
        last_used_path = os.path.join(os.path.dirname(self._path), "last-used.json")
        try:
            with open(last_used_path) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    async def update_last_used(self, child_id: int) -> None:
        last_used_path = os.path.join(os.path.dirname(self._path), "last-used.json")
        data = await self.load_last_used()
        data[str(child_id)] = datetime.now(timezone.utc).isoformat()
        dir_path = os.path.dirname(last_used_path)
        os.makedirs(dir_path, mode=0o700, exist_ok=True)
        with open(last_used_path, "w") as f:
            json.dump(data, f, indent=2)
        os.chmod(last_used_path, 0o600)
