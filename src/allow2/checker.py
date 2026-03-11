from __future__ import annotations

import asyncio
import math
import time
from typing import Any, Callable

from allow2.api import Allow2Api, Allow2ApiError
from allow2.models import Activity, ActivityState, Credentials, WarningThreshold
from allow2.warnings import WarningScheduler

SCREEN_TIME_ACTIVITY = 8


class Checker:
    """Periodic check loop with per-activity enforcement.
    Not an EventEmitter itself -- delegates to the daemon's emit()."""

    def __init__(
        self,
        *,
        api: Allow2Api,
        emit: Callable[..., Any],
        credentials: Credentials,
        child_id: int,
        activities: list[Activity],
        check_interval: int = 60,
        hard_lock_timeout: int = 300,
        grace_period: int = 300,
        warning_thresholds: list[WarningThreshold] | None = None,
    ) -> None:
        self._api = api
        self._emit = emit
        self._credentials = credentials
        self._child_id = child_id
        self._activities = activities
        self._check_interval = check_interval
        self._hard_lock_timeout = hard_lock_timeout
        self._grace_period = grace_period

        try:
            self._tz = time.tzname[0]
        except (IndexError, AttributeError):
            self._tz = "UTC"

        self._state: dict[str, ActivityState] = {}
        self._soft_locked = False
        self._soft_lock_handle: asyncio.TimerHandle | None = None
        self._offline_since: float | None = None
        self._offline_grace_emitted = False
        self._task: asyncio.Task[None] | None = None
        self._running = False

        self._warnings = WarningScheduler(
            emit=self._emit,
            thresholds=warning_thresholds,
        )

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        try:
            loop = asyncio.get_running_loop()
            self._task = loop.create_task(self._run_check())
        except RuntimeError:
            pass

    def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            self._task = None
        if self._soft_lock_handle is not None:
            self._soft_lock_handle.cancel()
            self._soft_lock_handle = None

    def on_time_extended(self, activity_id: int) -> None:
        self._warnings.reset_activity(str(activity_id))
        if self._soft_locked:
            self._soft_locked = False
            if self._soft_lock_handle is not None:
                self._soft_lock_handle.cancel()
                self._soft_lock_handle = None
            self._emit("unlock", {"reason": "time-extended", "activityId": activity_id})

    def get_remaining(self) -> dict[str, dict[str, Any]] | None:
        if not self._state:
            return None
        result: dict[str, dict[str, Any]] = {}
        for key, val in self._state.items():
            result[key] = {"allowed": val.allowed, "remaining": val.remaining}
        return result

    def reset(self, child_id: int) -> None:
        self._child_id = child_id
        self._state.clear()
        self._soft_locked = False
        self._offline_since = None
        self._offline_grace_emitted = False
        self._warnings.reset_all()
        if self._soft_lock_handle is not None:
            self._soft_lock_handle.cancel()
            self._soft_lock_handle = None

    async def _run_check(self) -> None:
        while self._running:
            try:
                await self._do_check()
            except Exception as err:
                self._handle_error(err)

            if self._running:
                await asyncio.sleep(self._check_interval)

    async def _do_check(self) -> None:
        activity_map: dict[str, int] = {}
        for act in self._activities:
            activity_map[str(act.id)] = 1

        result = await self._api.check(
            user_id=self._credentials.user_id,
            pair_id=self._credentials.pair_id,
            pair_token=self._credentials.pair_token,
            tz=self._tz,
            child_id=self._child_id,
            activities=activity_map,
            log=True,
        )

        if self._offline_since is not None:
            self._offline_since = None
            self._offline_grace_emitted = False

        self._process_result(result)

    def _process_result(self, result: dict[str, Any]) -> None:
        activities = result.get("activities", {})
        ids = list(activities.keys())

        all_blocked = True
        warning_data: dict[str, dict[str, Any]] = {}

        for act_id in ids:
            current = activities[act_id]
            allowed = bool(current.get("allowed"))
            remaining_val = current.get("remaining")
            remaining = remaining_val if remaining_val is not None else math.inf

            prev = self._state.get(act_id)
            was_allowed = prev.allowed if prev else True

            if was_allowed and not allowed:
                self._emit("activity-blocked", {
                    "activityId": int(act_id),
                    "activity": current.get("activity", act_id),
                    "remaining": 0,
                })
                if int(act_id) == SCREEN_TIME_ACTIVITY:
                    self._trigger_soft_lock("screen-time-exhausted")

            if not was_allowed and allowed and prev is not None:
                self._warnings.reset_activity(act_id)

            self._state[act_id] = ActivityState(allowed=allowed, remaining=remaining)

            if allowed:
                all_blocked = False
                warning_data[act_id] = {"remaining": remaining}

        if len(ids) > 0 and all_blocked and not self._soft_locked:
            self._trigger_soft_lock("all-activities-blocked")

        if self._soft_locked and not all_blocked:
            self._soft_locked = False
            if self._soft_lock_handle is not None:
                self._soft_lock_handle.cancel()
                self._soft_lock_handle = None
            self._emit("unlock", {"reason": "activity-unblocked"})

        if warning_data:
            self._warnings.update(warning_data)

    def _trigger_soft_lock(self, reason: str) -> None:
        if self._soft_locked:
            return
        self._soft_locked = True
        self._emit("soft-lock", {"reason": reason})

        try:
            loop = asyncio.get_running_loop()
            self._soft_lock_handle = loop.call_later(
                self._hard_lock_timeout,
                self._on_hard_lock_timeout,
            )
        except RuntimeError:
            pass

    def _on_hard_lock_timeout(self) -> None:
        if self._soft_locked and self._running:
            self._emit("hard-lock", {"reason": "soft-lock-timeout"})

    def _handle_error(self, err: Exception) -> None:
        if isinstance(err, Allow2ApiError) and err.status == 401:
            self._emit("unpaired", {"error": err})
            self.stop()
            return

        now = time.time() * 1000
        if self._offline_since is None:
            self._offline_since = now

        offline_duration = now - self._offline_since

        if offline_duration < self._grace_period * 1000:
            if not self._offline_grace_emitted:
                self._offline_grace_emitted = True
                self._emit("offline-grace", {
                    "since": self._offline_since,
                    "graceRemaining": self._grace_period * 1000 - offline_duration,
                })
        else:
            self._emit("offline-deny", {
                "since": self._offline_since,
                "offlineDuration": offline_duration,
            })
