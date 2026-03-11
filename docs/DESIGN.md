# Allow2 Python SDK v2 -- Design Document

**Status:** Draft
**Date:** 2026-03-11
**Gold Standard:** Node.js SDK v2 (`/workspace/ai/allow2/sdk/node/src/`, 14 files, ~2,450 lines)
**Target:** Functional equivalence with Node.js SDK v2

---

## 1. Overview

The Allow2 Python SDK v2 is a device-side SDK for integrating Allow2 Parental Freedom into Python applications: games (Pygame, Ren'Py), IoT devices (Raspberry Pi), desktop apps, automation scripts, and system services.

It mirrors the Node.js SDK v2 architecture exactly: same state machine, same API endpoints, same event names, same enforcement semantics. A developer familiar with one SDK can immediately use the other.

### Package Identity

- **PyPI name:** `allow2`
- **Import:** `import allow2` or `from allow2 import DeviceDaemon`
- **Version:** `2.0.0a1` (PEP 440 alpha)
- **Python:** 3.10+
- **License:** Same as Node SDK (SEE LICENSE IN LICENSE FILE)

---

## 2. File Structure

```
sdk/python/
├── pyproject.toml
├── LICENSE
└── src/
    └── allow2/
        ├── __init__.py          # Public exports
        ├── py.typed             # PEP 561 marker
        ├── models.py            # Dataclasses for all types
        ├── api.py               # Allow2Api HTTP client
        ├── daemon.py            # DeviceDaemon orchestrator
        ├── checker.py           # Check loop + per-activity enforcement
        ├── child_shield.py      # PIN verification + lockout
        ├── pairing.py           # QR/PIN pairing wizard
        ├── warnings.py          # Warning scheduler
        ├── offline.py           # Offline cache + grace period
        ├── request.py           # Request More Time
        ├── updates.py           # getUpdates polling
        ├── feedback.py          # Feedback submit/load/reply (extracted from daemon)
        ├── credentials/
        │   ├── __init__.py      # CredentialBackend protocol + factory
        │   ├── plaintext.py     # JSON file backend (~/.allow2/credentials.json)
        │   └── keyring_backend.py  # keyring-based backend
        └── child_resolver/
            ├── __init__.py      # ChildResolver protocol
            ├── linux_user.py    # OS username -> child mapping
            ├── selector.py      # Interactive selector (returns None)
            └── env_var.py       # ALLOW2_CHILD_ID env var (for scripts/CI)
```

**File count:** 18 source files (vs Node's 14). The delta is:
- `models.py` (new; Node uses ad-hoc objects, Python uses typed dataclasses)
- `feedback.py` (extracted; in Node it lives partly in daemon.js and api.js)
- `keyring_backend.py` (new; Node has libsecret TODO, we ship keyring)
- `env_var.py` (new; useful for headless/script scenarios)

---

## 3. Dependency Choices

### Required Dependencies (installed with `pip install allow2`)

| Package | Version | Rationale |
|---------|---------|-----------|
| `httpx` | `>=0.27` | Modern async-first HTTP client. Supports sync and async on the same API. Has built-in timeout, connection pooling, HTTP/2. Replaces Node's native `fetch`. |

### Optional Dependencies (extras)

| Extra | Packages | Rationale |
|-------|----------|-----------|
| `[keyring]` | `keyring>=25` | System keyring credential storage (GNOME Keyring, KDE Wallet, macOS Keychain, Windows Credential Locker). Replaces Node's libsecret TODO. |
| `[server]` | `aiohttp>=3.9` | Local pairing web server. Equivalent to Node's Express. Only needed if the integration wants to serve the pairing HTML page. Most integrations will handle pairing via their own UI. |
| `[all]` | All of the above | Convenience extra for full feature set. |

### Why httpx over alternatives

- **`urllib`/`urllib3`**: No native async. Would require `asyncio.to_thread()` wrappers, losing true async benefits (connection pooling, multiplexing).
- **`aiohttp`**: Async-only. Cannot be used in sync contexts without running an event loop. httpx supports both sync (`httpx.Client`) and async (`httpx.AsyncClient`) on the same code.
- **`requests`**: Sync-only, requires `aiohttp` or `httpx` for async anyway. httpx is the modern successor.

### Zero-dependency fallback

The SDK will NOT provide a zero-dependency fallback. Python 3.10+ always has `urllib`, but wrapping it to match httpx's interface would be significant work for marginal benefit. httpx is a pure-Python wheel with no native compilation -- it installs everywhere Python runs.

---

## 4. Type System (models.py)

All data structures are `dataclasses` with full type annotations. This provides IDE autocompletion, runtime validation, and JSON serialization without external schema libraries.

```python
# --- models.py ---

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DaemonState(str, Enum):
    """Mirrors Node SDK states exactly."""
    UNPAIRED = "unpaired"
    PAIRING = "pairing"
    PAIRED = "paired"
    ENFORCING = "enforcing"
    PARENT = "parent"


class WarningLevel(str, Enum):
    INFO = "info"
    URGENT = "urgent"
    FINAL = "final"
    COUNTDOWN = "countdown"


class FeedbackCategory(str, Enum):
    BYPASS = "bypass"
    MISSING_FEATURE = "missing_feature"
    NOT_WORKING = "not_working"
    QUESTION = "question"
    OTHER = "other"


class VerificationLevel(str, Enum):
    HONOUR = "honour"
    PIN = "pin"
    PARENT_ONLY = "parent-only"


@dataclass
class Activity:
    """An activity to monitor (e.g., Gaming, Internet, Screen Time)."""
    id: int

    def to_check_map(self) -> dict[str, int]:
        return {str(self.id): 1}


@dataclass
class Child:
    """A child entity from the controller's account."""
    id: int
    name: str
    pin_hash: str | None = None
    pin_salt: str | None = None
    avatar_url: str | None = None
    color: str | None = None
    has_account: bool = False
    linked_user_id: int | None = None
    os_username: str | None = None
    last_used_at: str | None = None  # ISO 8601


@dataclass
class Credentials:
    """Stored pairing credentials."""
    uuid: str
    user_id: int
    pair_id: int
    pair_token: str
    children: list[Child] = field(default_factory=list)


@dataclass
class ActivityState:
    """Per-activity enforcement state from a check response."""
    allowed: bool
    remaining: float  # seconds, math.inf if unlimited


@dataclass
class CheckResult:
    """Parsed result from /serviceapi/check."""
    activities: dict[str, ActivityState] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WarningThreshold:
    """A single warning threshold."""
    remaining: int  # seconds
    level: WarningLevel


@dataclass
class PairingInfo:
    """Returned by PairingWizard.start()."""
    pin: str
    port: int
    url: str
    qr_url: str
    connected: bool


@dataclass
class RequestResult:
    """Returned by create_request()."""
    request_id: str
    status_secret: str


@dataclass
class DeviceContext:
    """Context sent with feedback submissions."""
    device_name: str = "Allow2 Device"
    platform: str = "python"
    sdk_version: str = "2.0.0"
    product_name: str = "allow2"
```

### Serialization Convention

All dataclasses will have a `to_dict()` method (via a mixin or utility function) for JSON serialization, and a `@classmethod from_dict(cls, data: dict)` for deserialization from API responses. Field names in Python use `snake_case`; serialization maps to `camelCase` for API compatibility.

---

## 5. Event / Callback System

### Design Decision: Callback Registry (not asyncio.Event, not third-party)

Python has no built-in `EventEmitter`. The options:

1. **asyncio.Event / asyncio.Condition**: One-shot or condition-based; wrong abstraction for multi-listener event streams.
2. **Third-party (pyee, blinker)**: Adds dependency for a simple pattern.
3. **Custom callback registry**: Minimal, typed, zero-dependency.

We use option 3: a simple `EventEmitter` mixin that mirrors the Node.js pattern.

```python
# Embedded in daemon.py (or a small _events.py internal module)

from typing import Callable, Any
from collections import defaultdict

class EventEmitter:
    """
    Minimal EventEmitter matching the Node.js pattern.
    Supports: on(), off(), once(), emit().
    Thread-safe via a simple lock for add/remove.
    """

    def __init__(self) -> None:
        self._listeners: dict[str, list[Callable]] = defaultdict(list)

    def on(self, event: str, callback: Callable[..., Any]) -> None:
        """Register a listener for an event. Same callback can be registered multiple times."""
        self._listeners[event].append(callback)

    def off(self, event: str, callback: Callable[..., Any]) -> None:
        """Remove a specific listener."""
        try:
            self._listeners[event].remove(callback)
        except ValueError:
            pass

    def once(self, event: str, callback: Callable[..., Any]) -> None:
        """Register a listener that fires once then auto-removes."""
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            self.off(event, wrapper)
            return callback(*args, **kwargs)
        self.on(event, wrapper)

    def emit(self, event: str, *args: Any, **kwargs: Any) -> None:
        """
        Fire all listeners for an event.
        If a listener is a coroutine function, it is scheduled on the
        running event loop (fire-and-forget). If no loop is running,
        it is called synchronously (assuming it returns a coroutine
        that the caller can await or ignore).
        """
        for listener in self._listeners[event][:]:  # copy to allow mutation
            result = listener(*args, **kwargs)
            # If the listener returned a coroutine, schedule it
            if asyncio.iscoroutine(result):
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(result)
                except RuntimeError:
                    pass  # No running loop; coroutine is discarded

    def remove_all_listeners(self, event: str | None = None) -> None:
        """Remove all listeners, or all for a specific event."""
        if event is None:
            self._listeners.clear()
        else:
            self._listeners.pop(event, None)
```

### Event Names (exact match with Node SDK)

All event names use the same kebab-case strings as the Node SDK for cross-SDK consistency:

| Event | Payload | Emitted By |
|-------|---------|------------|
| `"paired"` | `{"user_id": int, "children": list[Child]}` | Daemon |
| `"unpaired"` | `{"error": Exception \| None}` | Daemon, Checker |
| `"pairing-required"` | `PairingInfo` | Daemon |
| `"pairing-error"` | `Exception` | Daemon |
| `"pairing-connection-status"` | `{"connected": bool}` | Daemon |
| `"child-select-required"` | `{"children": list[Child]}` | Daemon |
| `"child-selected"` | `{"child_id": int, "name": str \| None}` | Daemon |
| `"child-pin-failed"` | `{"child_id": int, "attempts_remaining": int}` | Daemon, ChildShield |
| `"child-locked-out"` | `{"child_id": int}` or `int` (seconds) | Daemon, ChildShield |
| `"parent-mode"` | `{}` | Daemon |
| `"parent-mode-entered"` | (none) | ChildShield |
| `"session-timeout"` | `{}` | Daemon, ChildShield |
| `"status-requested"` | `{"state": DaemonState, ...}` | Daemon |
| `"warning"` | `{"level": WarningLevel, "activity_id": str, "remaining": int}` | Checker (via WarningScheduler) |
| `"activity-blocked"` | `{"activity_id": int, "activity": str, "remaining": 0}` | Checker |
| `"soft-lock"` | `{"reason": str}` | Checker |
| `"hard-lock"` | `{"reason": str}` | Checker |
| `"unlock"` | `{"reason": str, "activity_id": int \| None}` | Checker |
| `"offline-grace"` | `{"since": float, "grace_remaining": float}` | Checker |
| `"offline-deny"` | `{"since": float, "offline_duration": float}` | Checker |
| `"children-updated"` | `{"children": list[Child]}` | Daemon |
| `"request-created"` | `{"request_id": str}` | RequestManager |
| `"request-approved"` | `{"request_id": str, ...}` | Daemon, RequestManager |
| `"request-denied"` | `{"request_id": str, ...}` | Daemon, RequestManager |
| `"request-timeout"` | (none) | RequestManager |
| `"request-error"` | `Exception` | RequestManager |
| `"feedback-submitted"` | `{"discussion_id": str, "category": str}` | Daemon |
| `"feedback-loaded"` | `{"discussions": list}` | Daemon |
| `"feedback-reply-sent"` | `{"discussion_id": str, "message_id": str}` | Daemon |
| `"extension"` | `{"child_id": int, "activity": int, ...}` | UpdatePoller |
| `"day-type-changed"` | `{"child_id": int, "day_type": str}` | UpdatePoller |
| `"quota-updated"` | `{"child_id": int, "activity": int, ...}` | UpdatePoller |
| `"ban"` | `{"child_id": int, "activity": int, "banned": bool}` | UpdatePoller |

---

## 6. File-by-File Specification

### 6.1 `api.py` -- Allow2Api

Port of `api.js` (302 lines). HTTP client wrapping all Allow2 REST endpoints.

```python
class Allow2Api:
    """
    Low-level async HTTP client for the Allow2 REST API.

    VID/Token resolution order: explicit arg > env var > baked-in default.
    Env vars: ALLOW2_API_URL, ALLOW2_VID, ALLOW2_TOKEN.
    """

    def __init__(
        self,
        *,
        api_url: str | None = None,
        vid: int | None = None,
        token: str | None = None,
        timeout: float = 15.0,
    ) -> None: ...

    # -- Properties --
    @property
    def base_url(self) -> str: ...
    @property
    def vid(self) -> int: ...

    # -- Internal --
    async def _fetch(self, path: str, *, method: str = "GET",
                     json_body: dict | None = None,
                     headers: dict | None = None) -> dict: ...
        """
        Core HTTP method. Uses httpx.AsyncClient.
        - Sets Content-Type: application/json
        - Parses JSON response
        - On non-2xx: raises Allow2ApiError with .status, .code, .body
        - Timeout via httpx.Timeout
        """

    # -- Pairing --
    async def init_qr_pairing(self, *, uuid: str, device_name: str,
                               platform: str = "python") -> dict: ...
    async def init_pin_pairing(self, *, uuid: str, device_name: str,
                                platform: str = "python") -> dict: ...
    async def check_pairing_status(self, pairing_session_id: str) -> dict: ...

    # -- Check --
    async def check(self, *, user_id: int, pair_id: int, pair_token: str,
                    child_id: int, activities: dict[str, int],
                    tz: str, log: bool = True) -> dict: ...

    # -- Updates --
    async def get_updates(self, *, user_id: int, pair_id: int,
                          pair_token: str,
                          timestamp_millis: int | None = None) -> dict: ...

    # -- Requests --
    async def create_request(self, *, user_id: int, pair_id: int,
                             pair_token: str, child_id: int,
                             duration: int, activity: int,
                             message: str | None = None) -> dict: ...
    async def get_request_status(self, request_id: str,
                                  status_secret: str) -> dict: ...

    # -- Feedback --
    async def submit_feedback(self, *, user_id: int, pair_id: int,
                              pair_token: str, child_id: int | None,
                              vid: int | None, category: str,
                              message: str,
                              device_context: dict | None = None) -> dict: ...
    async def load_feedback(self, *, user_id: int, pair_id: int,
                            pair_token: str) -> dict: ...
    async def feedback_reply(self, *, user_id: int, pair_id: int,
                             pair_token: str, discussion_id: str,
                             message: str) -> dict: ...

    # -- Usage --
    async def log_usage(self, *, user_id: int, pair_id: int,
                        pair_token: str, child_id: int,
                        activities: dict) -> dict: ...
```

**Error class:**

```python
class Allow2ApiError(Exception):
    """Raised on non-2xx API responses."""
    def __init__(self, message: str, *, status: int, code: str | None = None,
                 body: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body
```

**httpx client lifecycle:** A single `httpx.AsyncClient` instance is created lazily on first request and reused for connection pooling. Exposes `async close()` for clean shutdown. Supports context manager protocol (`async with Allow2Api() as api:`).

### 6.2 `daemon.py` -- DeviceDaemon

Port of `daemon.js` (769 lines). Main orchestrator.

```python
class DeviceDaemon(EventEmitter):
    """
    Main entry point for the Allow2 Device SDK.

    Manages the full device lifecycle:
      unpaired -> pairing -> paired -> enforcing
                                    -> parent (unrestricted)
    """

    def __init__(
        self,
        *,
        activities: list[Activity],
        credential_backend: CredentialBackend,
        child_resolver: ChildResolver,
        device_name: str = "Allow2 Device",
        check_interval: int = 60,          # seconds
        grace_period: int = 300,           # seconds
        hard_lock_timeout: int = 300,      # seconds
        warnings: list[WarningThreshold] | None = None,
        pairing_port: int = 3000,
        api_url: str | None = None,
        vid: int | None = None,
        token: str | None = None,
    ) -> None: ...

    # -- Properties (read-only) --
    @property
    def api(self) -> Allow2Api: ...
    @property
    def credentials(self) -> Credentials | None: ...
    @property
    def child_id(self) -> int | None: ...
    @property
    def running(self) -> bool: ...
    @property
    def paired(self) -> bool: ...
    @property
    def state(self) -> DaemonState: ...
    @property
    def is_parent_mode(self) -> bool: ...
    @property
    def can_submit_feedback(self) -> bool: ...

    # -- Lifecycle --
    async def start(self) -> None: ...
    def stop(self) -> None: ...
    async def open_app(self) -> None: ...
    def close_app(self) -> None: ...
    def enter_parent_mode(self) -> None: ...
    async def on_pairing_complete(self, credentials: Credentials) -> None: ...

    # -- Child Management --
    async def select_child(self, child_id: int, name: str | None = None) -> None: ...
    def child_pin_failed(self, child_id: int, attempts_remaining: int) -> None: ...
    def session_timeout(self) -> None: ...

    # -- Requests --
    async def request_more_time(self, *, duration: int, activity: int,
                                message: str | None = None) -> dict: ...
    async def poll_request_status(self, request_id: str,
                                   status_secret: str) -> dict: ...

    # -- Feedback --
    async def submit_feedback(self, *, category: FeedbackCategory,
                              message: str,
                              device_context: DeviceContext | None = None) -> dict: ...
    async def load_device_feedback(self) -> dict: ...
    async def reply_to_feedback(self, discussion_id: str, message: str) -> dict: ...

    @staticmethod
    def feedback_params_to_text(category: FeedbackCategory) -> str: ...

    # -- Internal --
    async def _start_pairing(self) -> None: ...
    async def _on_paired(self, credentials: Credentials) -> None: ...
    async def _begin_enforcement(self) -> None: ...
    async def _resolve_child(self) -> None: ...
    def _start_checker(self) -> None: ...
    def _start_heartbeat(self) -> None: ...
    def _stop_heartbeat(self) -> None: ...
    def _update_last_used(self, child_id: int) -> None: ...
```

**Async task management:** The daemon uses `asyncio.create_task()` for the check loop, heartbeat, and pairing poll. All tasks are tracked in a `set[asyncio.Task]` and cancelled in `stop()`. Timer-based operations (heartbeat, hard-lock timeout) use `asyncio.call_later()` or `asyncio.sleep()` in a loop.

### 6.3 `checker.py` -- Checker

Port of `checker.js` (296 lines).

```python
SCREEN_TIME_ACTIVITY: int = 8

class Checker:
    """
    Periodic check loop with per-activity enforcement.

    Not an EventEmitter itself -- delegates to the daemon's emit().
    """

    def __init__(
        self,
        *,
        api: Allow2Api,
        emit: Callable[..., None],
        credentials: Credentials,
        child_id: int,
        activities: list[Activity],
        check_interval: int = 60,         # seconds
        hard_lock_timeout: int = 300,     # seconds
        grace_period: int = 300,          # seconds
        warning_thresholds: list[WarningThreshold] | None = None,
    ) -> None: ...

    # -- Public --
    def start(self) -> None: ...            # Creates asyncio task for _run_check loop
    def stop(self) -> None: ...             # Cancels task, clears timers
    def on_time_extended(self, activity_id: int) -> None: ...
    def get_remaining(self) -> dict[str, ActivityState] | None: ...
    def reset(self, child_id: int) -> None: ...

    # -- Internal --
    async def _run_check(self) -> None: ... # Loop: _do_check() then sleep(interval)
    async def _do_check(self) -> None: ...  # API call, clear offline, process result
    def _process_result(self, result: dict) -> None: ...
    def _trigger_soft_lock(self, reason: str) -> None: ...
    def _handle_error(self, err: Exception) -> None: ...
```

**Key behavioral details ported exactly:**
- `_state: dict[str, ActivityState]` tracks per-activity allowed/remaining.
- Detects allowed-to-blocked transition per activity; emits `activity-blocked`.
- Screen Time (ID 8) exhaustion triggers `soft-lock`.
- All activities blocked also triggers `soft-lock`.
- `soft-lock` starts a hard-lock countdown (`asyncio.call_later`).
- Blocked-to-allowed cancels soft-lock, emits `unlock`.
- HTTP 401 emits `unpaired` and stops the loop.
- Network errors trigger offline grace / deny logic.
- Timezone via `time.tzname` or `zoneinfo` (Python 3.9+ stdlib).

### 6.4 `child_shield.py` -- ChildShield

Port of `child-shield.js` (411 lines).

```python
MAX_PIN_ATTEMPTS: int = 5
LOCKOUT_DURATION: float = 300.0  # seconds
DEFAULT_SESSION_TIMEOUT: float = 300.0  # seconds

def hash_pin(pin: str, salt: str) -> str:
    """SHA-256(pin + salt) as lowercase hex. Uses hashlib."""
    ...

def safe_compare(a: str, b: str) -> bool:
    """Constant-time comparison via hmac.compare_digest."""
    ...

class ChildShield(EventEmitter):
    """
    Child identification, PIN verification, and session management.
    """

    def __init__(
        self,
        *,
        children: list[Child],
        verification_level: VerificationLevel = VerificationLevel.PIN,
        session_timeout: float = DEFAULT_SESSION_TIMEOUT,
        on_select_required: Callable | None = None,
    ) -> None: ...

    # -- Public --
    def select_child(self, child_id: int, pin: str | None = None) -> bool: ...
    def select_parent(self, pin: str) -> bool: ...
    def clear_selection(self) -> None: ...
    def get_current_child(self) -> Child | None: ...
    def is_parent_mode(self) -> bool: ...
    def record_activity(self) -> None: ...
    def update_children(self, children: list[Child]) -> None: ...
    def get_children(self) -> list[dict]: ...  # Safe copy without PINs
    def destroy(self) -> None: ...

    # -- Internal --
    def _find_child(self, child_id: int) -> Child | None: ...
    def _find_parent_entry(self) -> Child | None: ...
    def _activate_child(self, child: Child) -> None: ...
    def _enter_parent_mode(self) -> None: ...
    def _reset_session_timer(self) -> None: ...
    def _stop_session_timer(self) -> None: ...
    def _on_session_timeout(self) -> None: ...
    def _get_attempt_record(self, key: str | int) -> dict: ...
    def _is_locked_out(self, key: str | int) -> bool: ...
    def _lockout_remaining(self, key: str | int) -> float: ...
    def _record_failed_attempt(self, key: str | int) -> None: ...
    def _clear_attempts(self, key: str | int) -> None: ...
```

**Session timer:** Uses `threading.Timer` (not asyncio) because ChildShield may be used outside an async context (e.g., in a Pygame main loop). The timer calls `_on_session_timeout()` which emits events synchronously.

### 6.5 `pairing.py` -- PairingWizard

Port of `pairing.js` (698 lines, including HTML templates).

```python
class PairingWizard(EventEmitter):
    """
    Manages one-time device pairing. Parents NEVER enter credentials on device.

    Flow:
    1. Call API to register pairing session (initPINPairing)
    2. API returns server-assigned PIN + session ID
    3. Device displays PIN (and QR deep link)
    4. Parent enters PIN in Allow2 app on their phone
    5. Wizard polls checkPairingStatus until confirmed
    6. On confirmation: store credentials, emit 'paired'
    """

    def __init__(
        self,
        *,
        api: Allow2Api,
        credential_backend: CredentialBackend,
        port: int = 3000,
        device_name: str = "Python Device",
        uuid: str | None = None,
    ) -> None: ...

    # -- Public --
    async def start(self) -> PairingInfo: ...
    async def stop(self) -> None: ...
    def get_pin(self) -> str | None: ...
    def get_qr_url(self) -> str | None: ...
    async def complete_pairing(self, pairing_data: dict) -> Credentials: ...

    # -- Internal --
    async def _load_or_create_uuid(self) -> str: ...
    def _start_init_retry(self) -> None: ...
    def _start_polling(self) -> None: ...
    async def _start_http_server(self) -> None: ...  # Optional, uses aiohttp if available
```

**HTTP server design:** The local pairing web server is optional. If `aiohttp` is installed (via `[server]` extra), PairingWizard starts an aiohttp server serving the same HTML as the Node SDK. If `aiohttp` is not installed, `start()` still works -- it just skips the web server and returns the PairingInfo for the integration to display however it wants.

**Polling:** Uses `asyncio.create_task` with a loop that sleeps 5s between polls. Max 360 polls (30 minutes). Retry logic on init failure matches Node SDK exactly (5s retry interval).

### 6.6 `warnings.py` -- WarningScheduler

Port of `warnings.js` (87 lines). Smallest module.

```python
DEFAULT_THRESHOLDS: list[WarningThreshold] = [
    WarningThreshold(remaining=900, level=WarningLevel.INFO),      # 15 min
    WarningThreshold(remaining=300, level=WarningLevel.URGENT),    # 5 min
    WarningThreshold(remaining=60,  level=WarningLevel.FINAL),     # 1 min
    WarningThreshold(remaining=30,  level=WarningLevel.COUNTDOWN), # 30 sec
]

class WarningScheduler:
    """
    Tracks remaining time per activity and emits 'warning' events
    when thresholds are crossed. Fire-once-per-level per activity.
    """

    def __init__(
        self,
        *,
        emit: Callable[..., None],
        thresholds: list[WarningThreshold] | None = None,
    ) -> None: ...

    def update(self, activities: dict[str, dict]) -> None: ...
        """Called by Checker after each check. Evaluates thresholds."""

    def reset_activity(self, activity_id: str) -> None: ...
    def reset_all(self) -> None: ...
```

Internal state: `_fired: dict[str, set[WarningLevel]]` -- maps activity ID to set of levels already fired.

### 6.7 `offline.py` -- OfflineHandler

Port of `offline.js` (133 lines).

```python
DEFAULT_GRACE_PERIOD: int = 300  # seconds

class OfflineHandler(EventEmitter):
    """
    Caches last successful check result. Enforces grace period.
    After grace: deny-by-default.
    Cache persisted to ~/.allow2/cache.json.
    """

    def __init__(
        self,
        *,
        grace_period: int = DEFAULT_GRACE_PERIOD,
        cache_path: str | None = None,  # Default: ~/.allow2/cache.json
    ) -> None: ...

    async def cache_result(self, check_result: dict) -> None: ...
    async def get_cached_result(self) -> dict | None: ...
    async def get_grace_elapsed(self) -> float: ...  # seconds, math.inf if no cache
    async def is_in_grace_period(self) -> bool: ...
    async def should_deny(self) -> bool: ...

    # -- Internal --
    async def _write_disk(self, data: dict) -> None: ...
    async def _load_disk(self) -> None: ...
```

Uses `aiofiles` if available, otherwise `asyncio.to_thread(pathlib.Path.write_text, ...)` for non-blocking disk I/O. File permissions set via `os.chmod(path, 0o600)`.

### 6.8 `request.py` -- RequestManager

Port of `request.js` (124 lines).

```python
class RequestManager(EventEmitter):
    """Request More Time flow with polling."""

    def __init__(
        self,
        *,
        api: Allow2Api,
        poll_interval: float = 5.0,    # seconds
        timeout: float = 300.0,        # seconds
    ) -> None: ...

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
    ) -> RequestResult: ...

    def start_polling(self, request_id: str, status_secret: str) -> None: ...
    def stop_polling(self) -> None: ...

    # -- Internal --
    async def _poll(self, request_id: str, status_secret: str) -> None: ...
```

### 6.9 `updates.py` -- UpdatePoller

Port of `updates.js` (179 lines).

```python
class UpdatePoller(EventEmitter):
    """
    Polls GET /api/getUpdates for delta changes.
    Emits: extension, day-type-changed, quota-updated, ban, children-updated.
    """

    def __init__(
        self,
        *,
        api: Allow2Api,
        poll_interval: float = 30.0,  # seconds
    ) -> None: ...

    def start(self, credentials: Credentials) -> None: ...
    def stop(self) -> None: ...

    # -- Internal --
    async def _poll(self) -> None: ...
    async def _fetch_updates(self) -> None: ...
    def _process_updates(self, result: dict) -> None: ...
    def _handle_error(self, err: Exception) -> None: ...
```

### 6.10 `feedback.py` -- Feedback helpers

Extracted from Node's `daemon.js` and `api.js` for cleaner separation. The daemon delegates to these, but they can also be used standalone.

```python
VALID_CATEGORIES: list[FeedbackCategory] = list(FeedbackCategory)

CATEGORY_LABELS: dict[FeedbackCategory, str] = {
    FeedbackCategory.BYPASS: "Bypass / Circumvention report",
    FeedbackCategory.MISSING_FEATURE: "Missing Feature report",
    FeedbackCategory.NOT_WORKING: "Not Working report",
    FeedbackCategory.QUESTION: "Question",
    FeedbackCategory.OTHER: "General feedback",
}

def feedback_category_to_text(category: FeedbackCategory) -> str: ...
```

The actual API calls live in `Allow2Api`. The daemon's `submit_feedback()`, `load_device_feedback()`, and `reply_to_feedback()` methods construct the params and call through `self._api`.

### 6.11 `credentials/__init__.py` -- CredentialBackend Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class CredentialBackend(Protocol):
    """
    Interface for credential storage backends.
    All methods are async to support both file I/O and keyring lookups.
    """

    async def store(self, data: dict) -> None: ...
    async def load(self) -> dict | None: ...
    async def clear(self) -> None: ...
    async def load_last_used(self) -> dict[str, str]: ...     # childId -> ISO timestamp
    async def update_last_used(self, child_id: int) -> None: ...


async def create_backend(
    backend_type: str = "plaintext",
    **kwargs: Any,
) -> CredentialBackend:
    """
    Factory for credential backends.
    Types: 'plaintext', 'keyring'.
    """
    ...
```

### 6.12 `credentials/plaintext.py` -- PlaintextBackend

Port of `credentials/plaintext.js` (97 lines).

```python
class PlaintextBackend:
    """
    Stores credentials as JSON in ~/.allow2/credentials.json.
    File permissions: 0o600. Directory permissions: 0o700.
    """

    def __init__(self, *, path: str | None = None) -> None: ...
        # Default: Path.home() / ".allow2" / "credentials.json"

    async def store(self, data: dict) -> None: ...
    async def load(self) -> dict | None: ...
    async def clear(self) -> None: ...
    async def load_last_used(self) -> dict[str, str]: ...
    async def update_last_used(self, child_id: int) -> None: ...
```

Uses `pathlib.Path` for path manipulation, `json` for serialization, `os.chmod` for permissions.

### 6.13 `credentials/keyring_backend.py` -- KeyringBackend

New (Node has libsecret as TODO).

```python
class KeyringBackend:
    """
    Stores credentials in the system keyring via the `keyring` package.
    Service name: 'allow2-sdk'.
    Keys: 'credentials', 'last-used'.
    Values: JSON-serialized strings.

    Requires: pip install allow2[keyring]
    """

    def __init__(self, *, service_name: str = "allow2-sdk") -> None: ...

    async def store(self, data: dict) -> None: ...
    async def load(self) -> dict | None: ...
    async def clear(self) -> None: ...
    async def load_last_used(self) -> dict[str, str]: ...
    async def update_last_used(self, child_id: int) -> None: ...
```

All keyring calls are wrapped in `asyncio.to_thread()` since `keyring` is synchronous and may block on D-Bus (GNOME Keyring) or other system calls.

### 6.14 `child_resolver/__init__.py` -- ChildResolver Protocol

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class ChildResolver(Protocol):
    """
    Interface for resolving which child is using the device.
    Can be a function or an object with resolve().
    """

    async def resolve(self, children: list[Child]) -> dict | None:
        """
        Return {"child_id": int, "child_name": str} or None.
        Returning None means interactive selection is required.
        """
        ...
```

The daemon also accepts a plain `Callable[[list[Child]], dict | None]` (sync or async) for simple use cases, matching the Node SDK's function-or-object pattern.

### 6.15 `child_resolver/linux_user.py`

Port of `child-resolver/linux-user.js` (81 lines).

```python
def get_linux_username() -> str:
    """Get current username from $USER or os.getlogin()."""
    ...

async def resolve(children: list[Child]) -> dict | None:
    """
    Match current Linux username to a child's name or os_username field.
    Case-insensitive. Skips parent entry (id=0 or name='__parent__').
    Returns {"child_id": int, "child_name": str} or None.
    """
    ...

# Also available as a class for Protocol compliance:
class LinuxUserResolver:
    async def resolve(self, children: list[Child]) -> dict | None:
        return await resolve(children)
```

### 6.16 `child_resolver/selector.py`

Port of `child-resolver/selector.js` (50 lines).

```python
async def resolve(children: list[Child]) -> None:
    """Always returns None. Selection must happen via UI."""
    return None

class SelectorResolver:
    async def resolve(self, children: list[Child]) -> None:
        return None

def request_selection(child_shield: ChildShield) -> None:
    """Emit child-select-required on the given ChildShield."""
    child_shield.emit("child-select-required", child_shield.get_children())
```

### 6.17 `child_resolver/env_var.py` (new)

Python-specific addition for headless/script scenarios.

```python
class EnvVarResolver:
    """
    Resolves child from ALLOW2_CHILD_ID environment variable.
    Useful for automation scripts, CI, Raspberry Pi headless setups.
    """

    def __init__(self, *, env_var: str = "ALLOW2_CHILD_ID") -> None: ...

    async def resolve(self, children: list[Child]) -> dict | None:
        """
        If ALLOW2_CHILD_ID is set, find matching child by ID.
        Returns {"child_id": int, "child_name": str} or None.
        """
        ...
```

### 6.18 `__init__.py` -- Public Exports

```python
"""
Allow2 Device SDK v2 -- Parental Freedom for apps and devices.
https://developer.allow2.com
"""

# Core
from allow2.daemon import DeviceDaemon
from allow2.child_shield import ChildShield
from allow2.pairing import PairingWizard
from allow2.api import Allow2Api, Allow2ApiError

# Utilities
from allow2.updates import UpdatePoller
from allow2.request import RequestManager
from allow2.offline import OfflineHandler
from allow2.warnings import WarningScheduler
from allow2.feedback import feedback_category_to_text

# Models
from allow2.models import (
    Activity, Child, Credentials, DaemonState, WarningLevel,
    WarningThreshold, FeedbackCategory, VerificationLevel,
    PairingInfo, RequestResult, DeviceContext, ActivityState,
    CheckResult,
)

# Credential backends
from allow2.credentials import CredentialBackend, create_backend
from allow2.credentials.plaintext import PlaintextBackend

# Child resolvers
from allow2.child_resolver.linux_user import LinuxUserResolver
from allow2.child_resolver.selector import SelectorResolver
from allow2.child_resolver.env_var import EnvVarResolver

__version__ = "2.0.0a1"
__all__ = [
    "DeviceDaemon", "ChildShield", "PairingWizard", "Allow2Api",
    "Allow2ApiError", "UpdatePoller", "RequestManager", "OfflineHandler",
    "WarningScheduler", "feedback_category_to_text",
    "Activity", "Child", "Credentials", "DaemonState", "WarningLevel",
    "WarningThreshold", "FeedbackCategory", "VerificationLevel",
    "PairingInfo", "RequestResult", "DeviceContext", "ActivityState",
    "CheckResult",
    "CredentialBackend", "create_backend", "PlaintextBackend",
    "LinuxUserResolver", "SelectorResolver", "EnvVarResolver",
    "__version__",
]
```

---

## 7. Async vs Sync Design Decision

**Primary API: async (asyncio).** All public methods that do I/O are `async def`.

**Sync wrapper: NOT provided in v1.** Rationale:
- Adding sync wrappers doubles the API surface and test burden.
- Python 3.10+ developers working with daemons/services expect async.
- For simple scripts, `asyncio.run(daemon.start())` is one line.
- Pygame/Ren'Py integrations can run the event loop in a background thread.

If demand arises, a `allow2.sync` module can be added later wrapping every async method with `asyncio.run()` or `loop.run_until_complete()`.

---

## 8. Packaging (pyproject.toml)

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "allow2"
version = "2.0.0a1"
description = "Allow2 Device SDK -- Parental Freedom for apps and devices"
readme = "README.md"
license = {text = "SEE LICENSE IN LICENSE FILE"}
requires-python = ">=3.10"
authors = [
    {name = "Allow2 Pty Ltd"},
]
keywords = [
    "parental-controls",
    "parental-freedom",
    "allow2",
    "screen-time",
    "device-management",
    "child-safety",
]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "Programming Language :: Python :: 3",
    "Programming Language :: Python :: 3.10",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
    "Topic :: Software Development :: Libraries",
    "Framework :: AsyncIO",
    "Typing :: Typed",
]
dependencies = [
    "httpx>=0.27",
]

[project.optional-dependencies]
keyring = ["keyring>=25"]
server = ["aiohttp>=3.9"]
all = ["keyring>=25", "aiohttp>=3.9"]
dev = [
    "pytest>=8",
    "pytest-asyncio>=0.24",
    "respx>=0.22",        # httpx mock
    "coverage>=7",
    "mypy>=1.11",
    "ruff>=0.6",
]

[project.urls]
Homepage = "https://developer.allow2.com"
Repository = "https://github.com/Allow2/allow2python"
Issues = "https://github.com/Allow2/allow2python/issues"

[tool.hatch.build.targets.wheel]
packages = ["src/allow2"]

[tool.mypy]
python_version = "3.10"
strict = true

[tool.ruff]
target-version = "py310"
line-length = 100

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

---

## 9. Testing Strategy

### Test Structure

```
tests/
├── conftest.py              # Shared fixtures (mock API, mock credentials)
├── test_api.py              # Allow2Api HTTP client tests
├── test_daemon.py           # DeviceDaemon lifecycle + state machine tests
├── test_checker.py          # Check loop + enforcement logic tests
├── test_child_shield.py     # PIN verification + lockout tests
├── test_pairing.py          # Pairing wizard tests
├── test_warnings.py         # Warning scheduler tests
├── test_offline.py          # Offline handler tests
├── test_request.py          # Request More Time tests
├── test_updates.py          # UpdatePoller tests
├── test_feedback.py         # Feedback tests
├── test_credentials.py      # PlaintextBackend + KeyringBackend tests
├── test_child_resolvers.py  # All resolver tests
└── test_models.py           # Dataclass serialization tests
```

### Testing Approach

| Layer | Tool | Approach |
|-------|------|----------|
| HTTP client | `respx` | Mock httpx requests. Test all endpoints, error codes (401, 500), timeouts, JSON parsing failures. |
| State machine | `pytest-asyncio` | Test all state transitions: unpaired->pairing->paired->enforcing->parent. Test edge cases: double-start, stop-while-pairing, 401-during-enforcement. |
| PIN verification | Pure unit tests | Test hash_pin, safe_compare, lockout progression, session timeout. No I/O. |
| Warning scheduler | Pure unit tests | Test threshold firing, fire-once-per-level, reset behavior. |
| Offline handler | tmp_path fixture | Test cache write/read, grace period math, deny-by-default, corrupt file handling. |
| Credentials | tmp_path fixture | Test store/load/clear, file permissions (on Linux), last-used tracking. |
| Child resolvers | monkeypatch | Mock $USER, test case-insensitive matching, parent entry skipping. |
| Integration | Full stack with respx | DeviceDaemon with mocked API, test complete flows: pair -> select child -> check loop -> warning -> soft-lock -> hard-lock. |

### Coverage Target

80% line coverage minimum. 100% on critical paths: state machine transitions, PIN verification, offline deny logic, 401 handling.

### CI Matrix

```yaml
# GitHub Actions
strategy:
  matrix:
    python-version: ["3.10", "3.11", "3.12", "3.13"]
    os: [ubuntu-latest, macos-latest]
```

Windows is not a target for the device SDK (the Node SDK targets Linux specifically), but the test suite should pass on Windows with the exception of file-permission tests.

---

## 10. Usage Examples

### 10.1 Basic Desktop App (Linux)

```python
import asyncio
from allow2 import (
    DeviceDaemon, Activity, PlaintextBackend, LinuxUserResolver,
)

async def main():
    backend = PlaintextBackend()
    resolver = LinuxUserResolver()

    daemon = DeviceDaemon(
        activities=[Activity(id=1), Activity(id=8)],  # Internet + Screen Time
        credential_backend=backend,
        child_resolver=resolver,
        device_name="Living Room PC",
    )

    # Wire up event handlers
    daemon.on("child-select-required", lambda data:
        print(f"Select a child: {[c['name'] for c in data['children']]}"))
    daemon.on("warning", lambda w:
        print(f"Warning [{w['level']}]: {w['remaining']}s remaining"))
    daemon.on("soft-lock", lambda d:
        print(f"LOCKED: {d['reason']}"))
    daemon.on("unpaired", lambda d:
        print("Device unpaired!"))

    await daemon.start()

    # Keep running until interrupted
    try:
        await asyncio.Event().wait()
    except KeyboardInterrupt:
        daemon.stop()

asyncio.run(main())
```

### 10.2 Raspberry Pi Kiosk

```python
import asyncio
from allow2 import (
    DeviceDaemon, Activity, PlaintextBackend, SelectorResolver,
)

async def main():
    daemon = DeviceDaemon(
        activities=[Activity(id=3)],  # Gaming
        credential_backend=PlaintextBackend(),
        child_resolver=SelectorResolver(),
        device_name="Pi Arcade Cabinet",
        check_interval=30,
    )

    daemon.on("pairing-required", lambda info:
        show_on_display(f"PIN: {info.pin}"))
    daemon.on("child-select-required", lambda data:
        show_child_picker(data["children"]))
    daemon.on("soft-lock", lambda _:
        blank_screen())
    daemon.on("unlock", lambda _:
        resume_game())

    await daemon.start()
    await daemon.open_app()  # Trigger pairing if not paired

    await asyncio.Event().wait()

asyncio.run(main())
```

### 10.3 Automation Script (headless)

```python
import asyncio
from allow2 import DeviceDaemon, Activity, PlaintextBackend, EnvVarResolver

async def main():
    # Pre-paired device, child set via ALLOW2_CHILD_ID=123
    daemon = DeviceDaemon(
        activities=[Activity(id=1)],
        credential_backend=PlaintextBackend(),
        child_resolver=EnvVarResolver(),
        device_name="Homework Timer",
    )

    daemon.on("activity-blocked", lambda d:
        print(f"Activity {d['activity_id']} blocked. Stopping."))

    await daemon.start()

    # Do work while enforcement runs in background...
    await do_homework_timer()

    daemon.stop()

asyncio.run(main())
```

### 10.4 Pygame Integration

```python
import asyncio
import threading
from allow2 import DeviceDaemon, Activity, PlaintextBackend, SelectorResolver

# Run Allow2 daemon in background thread
daemon = DeviceDaemon(
    activities=[Activity(id=3), Activity(id=8)],
    credential_backend=PlaintextBackend(),
    child_resolver=SelectorResolver(),
    device_name="My Pygame Game",
)

locked = False

def on_soft_lock(_):
    global locked
    locked = True

def on_unlock(_):
    global locked
    locked = False

daemon.on("soft-lock", on_soft_lock)
daemon.on("unlock", on_unlock)

def run_daemon():
    loop = asyncio.new_event_loop()
    loop.run_until_complete(daemon.start())
    loop.run_forever()

daemon_thread = threading.Thread(target=run_daemon, daemon=True)
daemon_thread.start()

# Pygame main loop
import pygame
pygame.init()
screen = pygame.display.set_mode((800, 600))
running = True

while running:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False

    if locked:
        screen.fill((0, 0, 0))
        # Show "Time's up!" overlay
    else:
        # Normal game rendering
        screen.fill((30, 30, 60))

    pygame.display.flip()

daemon.stop()
pygame.quit()
```

---

## 11. Key Design Decisions Summary

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Async framework | asyncio (stdlib) | No external dependency. Universal in Python 3.10+. |
| HTTP client | httpx | Async-native, sync fallback, modern, well-maintained. |
| Event system | Custom EventEmitter | Zero-dependency, matches Node SDK API exactly. |
| Type system | dataclasses + enums | Stdlib, IDE-friendly, no pydantic dependency. |
| Sync wrappers | Not in v1 | Avoids API surface bloat. `asyncio.run()` suffices. |
| Credential keyring | Optional via `[keyring]` extra | Not everyone has GNOME/KDE. Plaintext is the default. |
| Pairing HTTP server | Optional via `[server]` extra | Most integrations handle pairing UI themselves. |
| Build system | hatchling | Modern, fast, PEP 621 compliant. No setup.py needed. |
| Linter | ruff | Fast, replaces flake8+isort+pyupgrade. |
| Type checker | mypy (strict) | Full type safety. `py.typed` marker for downstream. |

---

## 12. Implementation Order

Recommended implementation sequence, with each step producing a testable unit:

| Phase | Files | Depends On | Est. Lines |
|-------|-------|------------|------------|
| 1 | `models.py`, `__init__.py`, `pyproject.toml` | Nothing | ~200 |
| 2 | `api.py` | models | ~250 |
| 3 | `credentials/` (all) | models | ~200 |
| 4 | `child_shield.py` | models, EventEmitter | ~350 |
| 5 | `warnings.py` | models | ~60 |
| 6 | `offline.py` | models | ~100 |
| 7 | `checker.py` | api, models, warnings | ~250 |
| 8 | `child_resolver/` (all) | models | ~100 |
| 9 | `request.py` | api, models, EventEmitter | ~100 |
| 10 | `updates.py` | api, models, EventEmitter | ~140 |
| 11 | `feedback.py` | models | ~30 |
| 12 | `pairing.py` | api, credentials, EventEmitter | ~300 |
| 13 | `daemon.py` | everything | ~600 |
| 14 | Tests | everything | ~1500 |

**Total estimated:** ~2,880 lines of source + ~1,500 lines of tests.

---

## 13. API Endpoint Mapping

Complete mapping of Node SDK API calls to Python SDK methods, ensuring nothing is missed:

| Node Method | Python Method | Endpoint | HTTP |
|-------------|---------------|----------|------|
| `initQRPairing` | `init_qr_pairing` | `/api/pair/qr/init` | POST |
| `initPINPairing` | `init_pin_pairing` | `/api/pair/pin/init` | POST |
| `checkPairingStatus` | `check_pairing_status` | `/api/pair/status/{id}` | GET |
| `check` | `check` | `/serviceapi/check` | POST |
| `getUpdates` | `get_updates` | `/api/getUpdates` | GET |
| `createRequest` | `create_request` | `/api/request/createRequest` | POST |
| `getRequestStatus` | `get_request_status` | `/api/request/{id}/status` | GET |
| `submitFeedback` | `submit_feedback` | `/api/feedback/submit` | POST |
| `loadFeedback` | `load_feedback` | `/api/feedback/load` | POST |
| `feedbackReply` | `feedback_reply` | `/api/feedback/reply` | POST |
| `logUsage` | `log_usage` | `/api/logUsage` | POST |

All endpoints use `deviceToken` from the API client's `self.token` (the application-level token, not per-device). The per-device identity is `pairId` + `pairToken`.

---

## 14. Critical Behavioral Parity Checklist

These behaviors MUST match the Node SDK exactly. Each should have a dedicated test:

- [ ] State machine transitions: unpaired -> pairing -> paired -> enforcing -> parent
- [ ] HTTP 401 from any endpoint -> clear credentials, emit `unpaired`, stop loops
- [ ] Screen Time (activity 8) exhaustion -> `soft-lock` with reason `screen-time-exhausted`
- [ ] All activities blocked -> `soft-lock` with reason `all-activities-blocked`
- [ ] Soft-lock timeout -> `hard-lock` after `hard_lock_timeout` seconds
- [ ] Soft-lock cancelled on unlock -> clear hard-lock timer
- [ ] Warning fire-once-per-level: same (activity, level) never emits twice
- [ ] Warning reset on time extension or child change
- [ ] PIN hash: `SHA-256(pin + salt)` as lowercase hex
- [ ] PIN comparison: constant-time (`hmac.compare_digest`)
- [ ] PIN lockout: 5 failed attempts -> 300s lockout
- [ ] Lockout expiry: attempts reset after lockout period
- [ ] Session timeout: clears child, emits `session-timeout`, requests re-selection
- [ ] Offline grace period: use cached result for `grace_period` seconds
- [ ] Offline deny: after grace period, emit `offline-deny`
- [ ] Offline clear: successful API check clears offline state
- [ ] Pairing PIN: server-assigned (not locally generated)
- [ ] Pairing QR URL: `https://app.allow2.com/pair?pin=XXXXXX`
- [ ] Pairing poll: 5s interval, 30-minute max (360 polls)
- [ ] Pairing retry: if init fails, retry every 5s until connected
- [ ] Pairing connection-status: emit after 2 consecutive poll failures
- [ ] Request polling: 5s interval, 5-minute timeout
- [ ] feedbackDeviceAuth: uses userId + pairId + pairToken (NOT deviceToken)
- [ ] Feedback categories: bypass, missing_feature, not_working, question, other
- [ ] canSubmitFeedback: parent=true, child with linked account=true, child without=false
- [ ] Heartbeat: runs when paired but no child selected, 60s interval
- [ ] Heartbeat detects 401 -> unpair
- [ ] Children sorted by lastUsedAt descending (most recent first)
- [ ] Child resolver accepts function or object with resolve()
- [ ] Credential backend file permissions: 0o600 (file), 0o700 (directory)
- [ ] UUID generation: random UUID, persisted across restarts
- [ ] Check loop: log=true by default, includes timezone
