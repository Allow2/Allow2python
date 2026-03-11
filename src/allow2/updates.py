from __future__ import annotations

import asyncio
import logging
from typing import Any

from allow2.api import Allow2Api, Allow2ApiError
from allow2.events import EventEmitter
from allow2.models import Credentials

logger = logging.getLogger("allow2.updates")


class UpdatePoller(EventEmitter):
    """Polls GET /api/getUpdates for delta changes."""

    def __init__(
        self,
        *,
        api: Allow2Api,
        poll_interval: float = 30.0,
    ) -> None:
        super().__init__()
        self._api = api
        self._poll_interval = poll_interval

        self._credentials: Credentials | None = None
        self._last_timestamp: int | None = None
        self._task: asyncio.Task[None] | None = None
        self._running = False

    def start(self, credentials: Credentials) -> None:
        if self._running:
            return
        self._credentials = credentials
        self._running = True
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._poll())
        except RuntimeError:
            pass

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _poll(self) -> None:
        while self._running:
            try:
                await self._fetch_updates()
            except Exception as err:
                self._handle_error(err)

            if self._running:
                await asyncio.sleep(self._poll_interval)

    async def _fetch_updates(self) -> None:
        if self._credentials is None:
            return

        kwargs: dict[str, Any] = {
            "user_id": self._credentials.user_id,
            "pair_id": self._credentials.pair_id,
            "pair_token": self._credentials.pair_token,
        }
        if self._last_timestamp is not None:
            kwargs["timestamp_millis"] = self._last_timestamp

        result = await self._api.get_updates(**kwargs)

        if result and result.get("timestampMillis"):
            self._last_timestamp = result["timestampMillis"]

        self._process_updates(result)

    def _process_updates(self, result: dict[str, Any]) -> None:
        if not result:
            return

        extensions = result.get("extensions")
        if extensions:
            for ext in extensions:
                self.emit("extension", {
                    "childId": ext.get("childId"),
                    "activity": ext.get("activity"),
                    "additionalMinutes": ext.get("additionalMinutes"),
                })

        day_type_changes = result.get("dayTypeChanges")
        if day_type_changes:
            for dtc in day_type_changes:
                self.emit("day-type-changed", {
                    "childId": dtc.get("childId"),
                    "dayType": dtc.get("dayType"),
                })

        quota_updates = result.get("quotaUpdates")
        if quota_updates:
            for qu in quota_updates:
                self.emit("quota-updated", {
                    "childId": qu.get("childId"),
                    "activity": qu.get("activity"),
                    "newQuota": qu.get("newQuota"),
                })

        bans = result.get("bans")
        if bans:
            for ban in bans:
                self.emit("ban", {
                    "childId": ban.get("childId"),
                    "activity": ban.get("activity"),
                    "banned": ban.get("banned"),
                })

        children = result.get("children")
        if children:
            self.emit("children-updated", children)

    def _handle_error(self, err: Exception) -> None:
        if isinstance(err, Allow2ApiError) and err.status == 401:
            self.emit("unpaired", {"error": err})
            self.stop()
            return
        self.emit("error", err)
