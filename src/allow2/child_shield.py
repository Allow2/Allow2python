from __future__ import annotations

import hashlib
import hmac
import threading
import time
from typing import Any, Callable

from allow2.events import EventEmitter
from allow2.models import Child, VerificationLevel

MAX_PIN_ATTEMPTS = 5
LOCKOUT_DURATION = 300.0
DEFAULT_SESSION_TIMEOUT = 300.0


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((pin + salt).encode()).hexdigest()


def safe_compare(a: str, b: str) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    return hmac.compare_digest(a, b)


class ChildShield(EventEmitter):
    """Child identification, PIN verification, and session management."""

    def __init__(
        self,
        *,
        children: list[Child],
        verification_level: VerificationLevel = VerificationLevel.PIN,
        session_timeout: float = DEFAULT_SESSION_TIMEOUT,
        on_select_required: Callable[..., Any] | None = None,
    ) -> None:
        super().__init__()
        self._children = list(children)
        self._verification_level = verification_level
        self._session_timeout = session_timeout

        self._current_child: Child | None = None
        self._parent_mode = False
        self._session_timer: threading.Timer | None = None
        self._last_activity: float = 0

        self._attempts: dict[str | int, dict[str, Any]] = {}

        if on_select_required is not None:
            self.on("child-select-required", on_select_required)

    def select_child(self, child_id: int, pin: str | None = None) -> bool:
        if self._verification_level == VerificationLevel.PARENT_ONLY:
            return False

        child = self._find_child(child_id)
        if child is None:
            return False

        if self._is_locked_out(child_id):
            remaining = self._lockout_remaining(child_id)
            self.emit("child-locked-out", int(remaining + 0.5))
            return False

        if self._verification_level == VerificationLevel.PIN:
            if pin is None:
                return False
            if child.pin_hash and child.pin_salt:
                computed = hash_pin(pin, child.pin_salt)
                if not safe_compare(computed, child.pin_hash):
                    self._record_failed_attempt(child_id)
                    return False

        self._clear_attempts(child_id)
        self._activate_child(child)
        return True

    def select_parent(self, pin: str) -> bool:
        if not pin:
            return False

        parent_entry = self._find_parent_entry()
        if parent_entry is None:
            return False

        if self._is_locked_out("parent"):
            remaining = self._lockout_remaining("parent")
            self.emit("child-locked-out", int(remaining + 0.5))
            return False

        if not parent_entry.pin_hash or not parent_entry.pin_salt:
            return False

        computed = hash_pin(pin, parent_entry.pin_salt)
        if not safe_compare(computed, parent_entry.pin_hash):
            self._record_failed_attempt("parent")
            return False

        self._clear_attempts("parent")
        self._enter_parent_mode()
        return True

    def clear_selection(self) -> None:
        self._stop_session_timer()
        self._current_child = None
        self._parent_mode = False
        self._last_activity = 0
        self.emit("child-select-required", self.get_children())

    def get_current_child(self) -> Child | None:
        return self._current_child

    def is_parent_mode(self) -> bool:
        return self._parent_mode

    def record_activity(self) -> None:
        self._last_activity = time.time()
        if self._current_child or self._parent_mode:
            self._reset_session_timer()

    def update_children(self, children: list[Child]) -> None:
        self._children = list(children)
        if self._current_child is not None:
            still = self._find_child(self._current_child.id)
            if still is None:
                self.clear_selection()
            else:
                self._current_child = Child(
                    id=still.id,
                    name=still.name,
                    pin_hash=still.pin_hash,
                    pin_salt=still.pin_salt,
                    avatar_url=still.avatar_url,
                    color=still.color,
                    has_account=still.has_account,
                    linked_user_id=still.linked_user_id,
                    os_username=still.os_username,
                    last_used_at=still.last_used_at,
                )

    def get_children(self) -> list[dict[str, Any]]:
        return [c.safe_copy() for c in self._children]

    def destroy(self) -> None:
        self._stop_session_timer()
        self.remove_all_listeners()

    def _find_child(self, child_id: int) -> Child | None:
        for child in self._children:
            if child.id == child_id:
                return child
        return None

    def _find_parent_entry(self) -> Child | None:
        for child in self._children:
            if child.id == 0 or child.name == "__parent__":
                return child
        return None

    def _activate_child(self, child: Child) -> None:
        self._parent_mode = False
        self._current_child = Child(
            id=child.id,
            name=child.name,
            pin_hash=child.pin_hash,
            pin_salt=child.pin_salt,
            avatar_url=child.avatar_url,
            color=child.color,
            has_account=child.has_account,
            linked_user_id=child.linked_user_id,
            os_username=child.os_username,
            last_used_at=child.last_used_at,
        )
        self._last_activity = time.time()
        self._reset_session_timer()
        self.emit("child-selected", child.id, child.name)

    def _enter_parent_mode(self) -> None:
        self._current_child = None
        self._parent_mode = True
        self._last_activity = time.time()
        self._reset_session_timer()
        self.emit("parent-mode-entered")

    def _reset_session_timer(self) -> None:
        self._stop_session_timer()
        if self._session_timeout <= 0:
            return
        self._session_timer = threading.Timer(
            self._session_timeout, self._on_session_timeout
        )
        self._session_timer.daemon = True
        self._session_timer.start()

    def _stop_session_timer(self) -> None:
        if self._session_timer is not None:
            self._session_timer.cancel()
            self._session_timer = None

    def _on_session_timeout(self) -> None:
        self._session_timer = None
        self._current_child = None
        self._parent_mode = False
        self._last_activity = 0
        self.emit("session-timeout")
        self.emit("child-select-required", self.get_children())

    def _get_attempt_record(self, key: str | int) -> dict[str, Any]:
        if key not in self._attempts:
            self._attempts[key] = {"failed": 0, "lockoutUntil": 0.0}
        return self._attempts[key]

    def _is_locked_out(self, key: str | int) -> bool:
        record = self._get_attempt_record(key)
        now = time.time()
        if record["lockoutUntil"] > 0 and now < record["lockoutUntil"]:
            return True
        if record["lockoutUntil"] > 0 and now >= record["lockoutUntil"]:
            record["failed"] = 0
            record["lockoutUntil"] = 0.0
        return False

    def _lockout_remaining(self, key: str | int) -> float:
        record = self._get_attempt_record(key)
        remaining = record["lockoutUntil"] - time.time()
        return remaining if remaining > 0 else 0

    def _record_failed_attempt(self, key: str | int) -> None:
        record = self._get_attempt_record(key)
        record["failed"] += 1
        if record["failed"] >= MAX_PIN_ATTEMPTS:
            record["lockoutUntil"] = time.time() + LOCKOUT_DURATION
            self.emit("child-locked-out", int(LOCKOUT_DURATION))
        else:
            self.emit("child-pin-failed", record["failed"], MAX_PIN_ATTEMPTS)

    def _clear_attempts(self, key: str | int) -> None:
        self._attempts.pop(key, None)
