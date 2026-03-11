from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from typing import Any

try:
    import keyring
except ImportError:
    keyring = None  # type: ignore[assignment]


class KeyringBackend:
    """Stores credentials in the system keyring via the keyring package.
    Requires: pip install allow2[keyring]"""

    def __init__(self, *, service_name: str = "allow2-sdk") -> None:
        if keyring is None:
            raise ImportError(
                "keyring backend requires the 'keyring' package. "
                "Install it with: pip install allow2[keyring]"
            )
        self._service = service_name

    async def store(self, data: dict[str, Any]) -> None:
        value = json.dumps(data)
        await asyncio.to_thread(keyring.set_password, self._service, "credentials", value)

    async def load(self) -> dict[str, Any] | None:
        raw = await asyncio.to_thread(keyring.get_password, self._service, "credentials")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return None

    async def clear(self) -> None:
        try:
            await asyncio.to_thread(keyring.delete_password, self._service, "credentials")
        except Exception:
            pass
        try:
            await asyncio.to_thread(keyring.delete_password, self._service, "last-used")
        except Exception:
            pass

    async def load_last_used(self) -> dict[str, str]:
        raw = await asyncio.to_thread(keyring.get_password, self._service, "last-used")
        if raw is None:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {}

    async def update_last_used(self, child_id: int) -> None:
        data = await self.load_last_used()
        data[str(child_id)] = datetime.now(timezone.utc).isoformat()
        value = json.dumps(data)
        await asyncio.to_thread(keyring.set_password, self._service, "last-used", value)
