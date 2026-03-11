from __future__ import annotations

import asyncio
import inspect
import logging
from typing import Any, Callable

from allow2.api import Allow2Api
from allow2.checker import Checker
from allow2.events import EventEmitter
from allow2.feedback import CATEGORY_LABELS, VALID_CATEGORIES
from allow2.models import (
    Activity,
    Child,
    Credentials,
    DaemonState,
    DeviceContext,
    FeedbackCategory,
    WarningThreshold,
)
from allow2.pairing import PairingWizard

logger = logging.getLogger("allow2.daemon")


class DeviceDaemon(EventEmitter):
    """Main entry point for the Allow2 Device SDK.

    Manages the full device lifecycle:
      unpaired -> pairing -> paired -> enforcing | parent
    """

    def __init__(
        self,
        *,
        activities: list[Activity],
        credential_backend: Any,
        child_resolver: Any,
        device_name: str = "Allow2 Device",
        check_interval: int = 60,
        grace_period: int = 300,
        hard_lock_timeout: int = 300,
        warnings: list[WarningThreshold] | None = None,
        pairing_port: int = 3000,
        api_url: str | None = None,
        vid: int | None = None,
        token: str | None = None,
    ) -> None:
        super().__init__()

        if not activities:
            raise ValueError("activities list is required and must not be empty")
        if credential_backend is None:
            raise ValueError("credential_backend is required")
        if child_resolver is None:
            raise ValueError("child_resolver is required")

        self._device_name = device_name
        self._activities = activities
        self._check_interval = check_interval
        self._credential_backend = credential_backend
        self._child_resolver = child_resolver
        self._grace_period = grace_period
        self._hard_lock_timeout = hard_lock_timeout
        self._warning_thresholds = warnings
        self._pairing_port = pairing_port

        self._api = Allow2Api(
            api_url=api_url,
            vid=vid,
            token=token,
        )

        self._checker: Checker | None = None
        self._credentials: Credentials | None = None
        self._child_id: int | None = None
        self._running = False
        self._pairing_wizard: PairingWizard | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None

        self._state = DaemonState.UNPAIRED

    @property
    def api(self) -> Allow2Api:
        return self._api

    @property
    def credentials(self) -> Credentials | None:
        return self._credentials

    @property
    def child_id(self) -> int | None:
        return self._child_id

    @property
    def running(self) -> bool:
        return self._running

    @property
    def paired(self) -> bool:
        return (
            self._credentials is not None
            and bool(self._credentials.pair_id)
            and bool(self._credentials.pair_token)
        )

    @property
    def state(self) -> DaemonState:
        return self._state

    @property
    def is_parent_mode(self) -> bool:
        return self._state == DaemonState.PARENT

    @property
    def can_submit_feedback(self) -> bool:
        if self._state == DaemonState.PARENT:
            return True
        if self._credentials is None or not self._credentials.user_id:
            return False
        if self._child_id and self._credentials.children:
            for child in self._credentials.children:
                cid = child.id
                if cid == self._child_id:
                    return child.linked_user_id is not None
            return False
        return bool(self._credentials.user_id)

    async def start(self) -> None:
        if self._running:
            return
        self._running = True

        try:
            creds_data = await self._credential_backend.load()
            if creds_data:
                self._credentials = Credentials.from_dict(creds_data)
            else:
                self._credentials = None
        except Exception as err:
            logger.error("Failed to load credentials: %s", err)
            self._credentials = None

        if not self._credentials or not self._credentials.pair_id or not self._credentials.pair_token:
            self._state = DaemonState.UNPAIRED
            logger.info("Device not paired. Waiting for user to open Allow2 app.")
            return

        self._state = DaemonState.PAIRED
        await self._begin_enforcement()

    def stop(self) -> None:
        self._running = False
        self._stop_heartbeat()
        if self._checker is not None:
            self._checker.stop()
            self._checker = None
        if self._pairing_wizard is not None:
            asyncio.ensure_future(self._pairing_wizard.stop())
            self._pairing_wizard = None
        self._child_id = None

        if self._credentials and self._credentials.pair_id:
            self._state = DaemonState.PAIRED
        else:
            self._state = DaemonState.UNPAIRED

    def close_app(self) -> None:
        if self._pairing_wizard is not None:
            asyncio.ensure_future(self._pairing_wizard.stop())
            self._pairing_wizard = None
        if not self._credentials or not self._credentials.pair_id:
            self._state = DaemonState.UNPAIRED

    async def open_app(self) -> None:
        if self._state == DaemonState.UNPAIRED or not self._credentials or not self._credentials.pair_id:
            await self._start_pairing()
        else:
            remaining = self._checker.get_remaining() if self._checker else None
            self.emit("status-requested", {
                "state": self._state.value,
                "children": [c.to_dict() for c in (self._credentials.children if self._credentials else [])],
                "currentChildId": self._child_id,
                "remaining": remaining,
            })

    def enter_parent_mode(self) -> None:
        if self._checker is not None:
            self._checker.stop()
            self._checker = None
        self._state = DaemonState.PARENT
        self.emit("parent-mode", {})

    async def on_pairing_complete(self, credentials: Credentials) -> None:
        await self._on_paired(credentials)

    async def select_child(self, child_id: int, name: str | None = None) -> None:
        if self._checker is not None:
            self._checker.stop()

        self._child_id = child_id
        self._state = DaemonState.ENFORCING
        self.emit("child-selected", {"childId": child_id, "name": name})

        self._update_last_used(child_id)

        if self._running and self._credentials:
            self._start_checker()

    def child_pin_failed(self, child_id: int, attempts_remaining: int) -> None:
        self.emit("child-pin-failed", {
            "childId": child_id,
            "attemptsRemaining": attempts_remaining,
        })
        if attempts_remaining <= 0:
            self.emit("child-locked-out", {"childId": child_id})

    def session_timeout(self) -> None:
        if self._checker is not None:
            self._checker.stop()
            self._checker = None
        self._child_id = None
        self._state = DaemonState.PAIRED
        self.emit("session-timeout", {})

        if self._running and self._credentials:
            asyncio.ensure_future(self._resolve_child())

    async def request_more_time(
        self,
        *,
        duration: int,
        activity: int,
        message: str | None = None,
    ) -> dict[str, Any]:
        if self._child_id is None:
            raise RuntimeError("No child selected")
        if self._credentials is None:
            raise RuntimeError("Not paired")
        return await self._api.create_request(
            user_id=self._credentials.user_id,
            pair_id=self._credentials.pair_id,
            pair_token=self._credentials.pair_token,
            child_id=self._child_id,
            duration=duration,
            activity=activity,
            message=message,
        )

    async def poll_request_status(
        self, request_id: str, status_secret: str
    ) -> dict[str, Any]:
        result = await self._api.get_request_status(request_id, status_secret)

        if result and result.get("status") == "approved":
            self.emit("request-approved", {
                "requestId": request_id,
                "activityId": result.get("activityId"),
                "duration": result.get("duration"),
            })
            if self._checker and result.get("activityId"):
                self._checker.on_time_extended(result["activityId"])
        elif result and result.get("status") == "denied":
            self.emit("request-denied", {
                "requestId": request_id,
                "reason": result.get("reason"),
            })

        return result

    async def submit_feedback(
        self,
        *,
        category: FeedbackCategory,
        message: str,
        device_context: DeviceContext | None = None,
    ) -> dict[str, Any]:
        if not self.can_submit_feedback:
            raise RuntimeError("Cannot submit feedback: no account associated")
        if not category or not message:
            raise ValueError("category and message are required")
        if category not in VALID_CATEGORIES:
            raise ValueError(
                f"Invalid category. Must be one of: {', '.join(c.value for c in VALID_CATEGORIES)}"
            )

        context = DeviceContext(device_name=self._device_name)
        if device_context is not None:
            context.device_name = device_context.device_name
            context.platform = device_context.platform
            context.sdk_version = device_context.sdk_version
            context.product_name = device_context.product_name

        if self._credentials is None:
            raise RuntimeError("Not paired")

        result = await self._api.submit_feedback(
            user_id=self._credentials.user_id,
            pair_id=self._credentials.pair_id,
            pair_token=self._credentials.pair_token,
            child_id=self._child_id,
            vid=self._api.vid,
            category=category.value,
            message=message,
            device_context=context.to_dict(),
        )

        self.emit("feedback-submitted", {
            "discussionId": result.get("discussionId"),
            "category": category.value,
        })

        return result

    async def load_device_feedback(self) -> dict[str, Any]:
        if self._credentials is None or not self._credentials.pair_id:
            raise RuntimeError("Device not paired")

        result = await self._api.load_feedback(
            user_id=self._credentials.user_id,
            pair_id=self._credentials.pair_id,
            pair_token=self._credentials.pair_token,
        )

        self.emit("feedback-loaded", {
            "discussions": (result.get("discussions") if result else []) or [],
        })

        return result

    async def reply_to_feedback(self, discussion_id: str, message: str) -> dict[str, Any]:
        if not discussion_id or not message:
            raise ValueError("discussionId and message are required")
        if self._credentials is None:
            raise RuntimeError("Not paired")

        result = await self._api.feedback_reply(
            user_id=self._credentials.user_id,
            pair_id=self._credentials.pair_id,
            pair_token=self._credentials.pair_token,
            discussion_id=discussion_id,
            message=message,
        )

        self.emit("feedback-reply-sent", {
            "discussionId": discussion_id,
            "messageId": result.get("messageId"),
        })

        return result

    @staticmethod
    def feedback_params_to_text(category: FeedbackCategory) -> str:
        return CATEGORY_LABELS.get(category, "Feedback")

    async def _start_pairing(self) -> None:
        if self._state == DaemonState.PAIRING and self._pairing_wizard is not None:
            return

        self._state = DaemonState.PAIRING

        self._pairing_wizard = PairingWizard(
            api=self._api,
            credential_backend=self._credential_backend,
            port=self._pairing_port,
            device_name=self._device_name,
        )

        self._pairing_wizard.on("paired", lambda creds: asyncio.ensure_future(self._on_wizard_paired(creds)))
        self._pairing_wizard.on("error", lambda err: self.emit("pairing-error", err))
        self._pairing_wizard.on("connection-status", lambda s: self.emit("pairing-connection-status", s))

        try:
            info = await self._pairing_wizard.start()
            self.emit("pairing-required", {
                "wizard": self._pairing_wizard,
                "pin": info.pin,
                "port": info.port,
                "url": info.url,
                "qrUrl": info.qr_url,
                "connected": info.connected,
            })
        except Exception as err:
            self.emit("pairing-error", err)

    async def _on_wizard_paired(self, credentials: Credentials) -> None:
        self._pairing_wizard = None
        await self._on_paired(credentials)

    async def _on_paired(self, credentials: Credentials) -> None:
        self._credentials = credentials
        self._state = DaemonState.PAIRED

        self.emit("paired", {
            "userId": credentials.user_id,
            "children": [c.to_dict() for c in credentials.children],
        })

        if self._running:
            await self._begin_enforcement()

    def _start_heartbeat(self) -> None:
        self._stop_heartbeat()
        try:
            loop = asyncio.get_running_loop()
            self._heartbeat_task = loop.create_task(self._heartbeat_loop())
        except RuntimeError:
            pass

    def _stop_heartbeat(self) -> None:
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None

    async def _heartbeat_loop(self) -> None:
        while True:
            await asyncio.sleep(60)

            if self._checker or not self._credentials or not self._credentials.pair_id:
                self._stop_heartbeat()
                return

            try:
                result = await self._api.get_updates(
                    user_id=self._credentials.user_id,
                    pair_id=self._credentials.pair_id,
                    pair_token=self._credentials.pair_token,
                )
                if result and result.get("children"):
                    children_raw = result["children"]
                    self._credentials.children = [
                        Child.from_dict(c) if isinstance(c, dict) else c
                        for c in children_raw
                    ]
                    self.emit("children-updated", {"children": [c.to_dict() for c in self._credentials.children]})
            except Exception as err:
                from allow2.api import Allow2ApiError
                if isinstance(err, Allow2ApiError) and err.status == 401:
                    self._stop_heartbeat()
                    self._state = DaemonState.UNPAIRED
                    self._credentials = None
                    self._child_id = None
                    try:
                        if hasattr(self._credential_backend, "clear"):
                            await self._credential_backend.clear()
                    except Exception:
                        pass
                    self.emit("unpaired", {"error": err})
                    return

    async def _begin_enforcement(self) -> None:
        await self._resolve_child()

        if self._child_id:
            self._state = DaemonState.ENFORCING
            self._stop_heartbeat()
            self._start_checker()
        else:
            self._start_heartbeat()

    async def _resolve_child(self) -> None:
        children = self._credentials.children if self._credentials else []

        annotated: list[Child] = []
        for c in children:
            copy = Child(
                id=c.id, name=c.name, pin_hash=c.pin_hash, pin_salt=c.pin_salt,
                avatar_url=c.avatar_url, color=c.color, has_account=c.has_account,
                linked_user_id=c.linked_user_id, os_username=c.os_username,
                last_used_at=None,
            )
            annotated.append(copy)

        if hasattr(self._credential_backend, "load_last_used"):
            try:
                last_used_map = await self._credential_backend.load_last_used()
                if last_used_map:
                    for child in annotated:
                        ts = last_used_map.get(str(child.id))
                        if ts:
                            child.last_used_at = ts
            except Exception as err:
                logger.error("Failed to load lastUsed data: %s", err)

        annotated.sort(
            key=lambda c: c.last_used_at or "",
            reverse=True,
        )

        match: dict[str, Any] | None = None
        if callable(self._child_resolver) and not hasattr(self._child_resolver, "resolve"):
            result = self._child_resolver(annotated)
            if inspect.isawaitable(result):
                match = await result
            else:
                match = result
        elif hasattr(self._child_resolver, "resolve"):
            result = self._child_resolver.resolve(annotated)
            if inspect.isawaitable(result):
                match = await result
            else:
                match = result

        if match and match.get("child_id"):
            self._child_id = match["child_id"]
            self._state = DaemonState.ENFORCING
            self._update_last_used(match["child_id"])
            self.emit("child-selected", {
                "childId": match["child_id"],
                "name": match.get("child_name"),
            })
        else:
            self.emit("child-select-required", {
                "children": [c.to_dict() for c in annotated],
            })

    def _start_checker(self) -> None:
        if self._checker is not None:
            self._checker.stop()

        if self._credentials is None or self._child_id is None:
            return

        self._checker = Checker(
            api=self._api,
            emit=self.emit,
            credentials=self._credentials,
            child_id=self._child_id,
            activities=self._activities,
            check_interval=self._check_interval,
            hard_lock_timeout=self._hard_lock_timeout,
            grace_period=self._grace_period,
            warning_thresholds=self._warning_thresholds,
        )

        def on_unpaired(*args: Any, **kwargs: Any) -> None:
            self._state = DaemonState.UNPAIRED
            self._credentials = None
            if self._checker is not None:
                self._checker.stop()
                self._checker = None
            self._child_id = None
            self.off("unpaired", on_unpaired)

        self.on("unpaired", on_unpaired)
        self._checker.start()

    def _update_last_used(self, child_id: int) -> None:
        if hasattr(self._credential_backend, "update_last_used"):
            try:
                asyncio.ensure_future(self._credential_backend.update_last_used(child_id))
            except RuntimeError:
                pass
