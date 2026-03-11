from __future__ import annotations

import asyncio
from typing import Any

from allow2.api import Allow2Api
from allow2.events import EventEmitter
from allow2.models import RequestResult

DEFAULT_POLL_INTERVAL = 5.0
DEFAULT_TIMEOUT = 300.0


class RequestManager(EventEmitter):
    """Request More Time flow with polling."""

    def __init__(
        self,
        *,
        api: Allow2Api,
        poll_interval: float = DEFAULT_POLL_INTERVAL,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        super().__init__()
        self._api = api
        self._poll_interval = poll_interval
        self._timeout = timeout
        self._poll_task: asyncio.Task[None] | None = None
        self._timeout_handle: asyncio.TimerHandle | None = None

    async def create_request(
        self,
        *,
        user_id: int,
        pair_id: int,
        pair_token: str,
        child_id: int,
        duration: int,
        activity: int,
        message: str | None = None,
    ) -> RequestResult:
        try:
            response = await self._api.create_request(
                user_id=user_id,
                pair_id=pair_id,
                pair_token=pair_token,
                child_id=child_id,
                duration=duration,
                activity=activity,
                message=message,
            )
            request_id = response["requestId"]
            status_secret = response["statusSecret"]

            self.emit("request-created", {"requestId": request_id})
            self.start_polling(request_id, status_secret)

            return RequestResult(request_id=request_id, status_secret=status_secret)
        except Exception as err:
            self.emit("request-error", err)
            raise

    def start_polling(self, request_id: str, status_secret: str) -> None:
        self.stop_polling()

        try:
            loop = asyncio.get_running_loop()
            self._timeout_handle = loop.call_later(
                self._timeout,
                self._on_timeout,
            )
            self._poll_task = loop.create_task(self._poll(request_id, status_secret))
        except RuntimeError:
            pass

    def stop_polling(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            self._poll_task = None
        if self._timeout_handle is not None:
            self._timeout_handle.cancel()
            self._timeout_handle = None

    def _on_timeout(self) -> None:
        self.stop_polling()
        self.emit("request-timeout")

    async def _poll(self, request_id: str, status_secret: str) -> None:
        while True:
            await asyncio.sleep(self._poll_interval)
            try:
                status = await self._api.get_request_status(request_id, status_secret)

                if status.get("status") == "approved":
                    self.stop_polling()
                    self.emit("request-approved", {
                        "requestId": request_id,
                        "extension": status.get("extension"),
                    })
                    return

                if status.get("status") == "denied":
                    self.stop_polling()
                    self.emit("request-denied", {"requestId": request_id})
                    return

            except Exception as err:
                self.emit("request-error", err)
