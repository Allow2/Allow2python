# Allow2 SDK for Python

[![PyPI version](https://img.shields.io/pypi/v/allow2.svg?style=flat-square)](https://pypi.org/project/allow2/)
[![Python versions](https://img.shields.io/pypi/pyversions/allow2.svg?style=flat-square)](https://pypi.org/project/allow2/)
[![CI](https://img.shields.io/github/actions/workflow/status/Allow2/allow2python/ci.yml?style=flat-square)](https://github.com/Allow2/allow2python/actions)

Official Allow2 Parental Freedom SDK for Python.

| | |
|---|---|
| **Package** | `allow2` |
| **Targets** | Python 3.10+ |
| **Dependencies** | `httpx` |
| **Optional** | `aiohttp` (pairing server), `keyring` (secure credential storage) |
| **Language** | Python (asyncio) |

## Installation

```bash
pip install allow2
```

With optional secure credential storage:

```bash
pip install allow2[keyring]
```

## Quick Start

```python
import asyncio
from allow2 import DeviceDaemon, PlaintextBackend, Activity

async def main():
    backend = PlaintextBackend()

    daemon = DeviceDaemon(
        device_name='Living Room PC',
        activities=[Activity(id=1), Activity(id=8)],    # Internet + Screen Time
        credential_backend=backend,
        child_resolver=lambda children: None,            # interactive selection
    )

    daemon.on('pairing-required', lambda info: print(f"Enter PIN: {info['pin']}"))
    daemon.on('child-select-required', lambda data: print('Select child:', [c['name'] for c in data['children']]))
    daemon.on('warning', lambda w: print(f"Warning: {w['level']}, {w['remaining']}s left"))
    daemon.on('soft-lock', lambda _: print('Time is up!'))

    await daemon.start()
    await daemon.open_app()     # triggers pairing if unpaired

asyncio.run(main())
```

## Modules

| Module | File | Purpose |
|--------|------|---------|
| **DeviceDaemon** | `daemon.py` | Main orchestrator managing the full device lifecycle |
| **Allow2Api** | `api.py` | httpx-based async REST client for all Allow2 endpoints |
| **PairingWizard** | `pairing.py` | aiohttp-based pairing wizard (QR code + PIN display) |
| **ChildShield** | `child_shield.py` | PIN hashing (SHA-256 + salt), rate limiting, session timeout |
| **Checker** | `checker.py` | Permission check loop with per-activity enforcement and stacking |
| **Warnings** | `warnings.py` | Configurable progressive warning scheduler |
| **OfflineHandler** | `offline.py` | Response cache, grace period, deny-by-default fallback |
| **RequestManager** | `request.py` | Request flow (more time, day type change, ban lift) with polling |
| **UpdatePoller** | `updates.py` | Poll for children, quota, ban, and day type changes |
| **Credentials** | `credentials/` | `PlaintextBackend` default + optional `KeyringBackend` |

## Permission Checks

```python
# The check loop runs automatically once a child is selected.
# Listen for results:
@daemon.on('check-result')
def on_check(result):
    for activity_id, activity in result['activities'].items():
        print(f"{activity_id}: allowed={activity['allowed']}, remaining={activity['remaining']}s")
    print(f"Today: {result['day_type_today']}, Tomorrow: {result['day_type_tomorrow']}")
```

## Request More Time

```python
# Child requests 30 more minutes of gaming
result = await daemon.request_more_time(
    activity=3,         # Gaming
    duration=30,        # minutes
    message="Can I please have more time? Almost done with this level.",
)

# Poll until parent responds
status = await daemon.poll_request_status(result['request_id'], result['status_secret'])

if status['status'] == 'approved':
    print(f"Approved! {status['duration']} extra minutes.")
elif status['status'] == 'denied':
    print("Request denied.")
```

## Feedback

```python
# Submit feedback
result = await daemon.submit_feedback(
    category='not_working',
    message='The block screen appears even when time is remaining.',
)

# Load feedback threads
feedback = await daemon.load_device_feedback()
for thread in feedback['discussions']:
    print(f"[{thread['category']}] {thread['status']} - {thread['message_count']} messages")

# Reply to a thread
await daemon.reply_to_feedback(result['discussion_id'], 'This happens every Tuesday.')
```

## Warnings

The SDK fires progressive warnings as time runs out:

```
15 min -> 5 min -> 1 min -> 30 sec -> 10 sec -> BLOCKED
```

```python
@daemon.on('warning')
def on_warning(data):
    show_warning_banner(f"{data['remaining']} seconds remaining")

@daemon.on('soft-lock')
def on_lock(_):
    show_block_screen()
```

## Credential Storage

The SDK uses a pluggable credential backend. The default `PlaintextBackend` writes to `~/.allow2/credentials.json` with `0600` permissions.

For production, use the `KeyringBackend` (backed by the system keychain) or implement your own:

```python
class MyCredentialBackend:
    async def load(self) -> dict | None:
        """Return {'user_id': ..., 'pair_id': ..., 'pair_token': ..., 'children': [...]} or None."""
        ...

    async def store(self, credentials: dict) -> None:
        """Persist credentials."""
        ...

    async def clear(self) -> None:
        """Remove stored credentials."""
        ...
```

## Target Platforms

| Platform | Notes |
|----------|-------|
| **Linux** | Desktop apps, daemons, Raspberry Pi |
| **macOS** | Desktop apps, system services |
| **Windows** | Desktop apps, services |
| **Embedded** | Any device with Python 3.10+ and httpx |
| **Server** | Django, FastAPI, Flask service integrations |

## Architecture

The SDK follows the Allow2 Device Operational Lifecycle:

1. **Pairing** (one-time) -- QR code or 6-digit PIN, parent never enters credentials on device
2. **Child Identification** (every session) -- OS account mapping, child selector with PIN, or verification via the child's Allow2 app (iOS/Android) or web portal
3. **Parent Access** -- parent verifies via their Allow2 app (iOS/Android), web portal, or locally with PIN for unrestricted mode
4. **Permission Checks** (continuous) -- POST to service URL every 30-60s with `log: true`
5. **Warnings & Countdowns** -- progressive alerts before blocking
6. **Requests** -- child requests changes (more time, day type change, ban lift), parent approves/denies from their phone (also works offline via voice codes)
7. **Feedback** -- bug reports and feature requests sent directly to you, the developer

All API communication uses `httpx` with async support. The check endpoint POSTs to the **service URL** (`service.allow2.com`), while all other endpoints use the **API URL** (`api.allow2.com`).

Environment overrides via `ALLOW2_API_URL`, `ALLOW2_VID`, and `ALLOW2_TOKEN` environment variables.

## Offline Operation

Once a device is paired, Allow2 remains fully configurable even when the device is offline. The parent can still manage the child's limits, approve requests, and change settings from their Allow2 app or the web portal -- changes are synchronised the next time the device connects.

On the device side:

- **Cached permissions** -- the last successful check result is cached locally. During a configurable grace period (default 5 minutes), the device continues to enforce the cached result.
- **Deny-by-default** -- after the grace period expires without connectivity, all activities are blocked. This prevents children from bypassing controls by disabling Wi-Fi or enabling airplane mode.
- **Requests (offline)** -- children can still submit all request types (more time, day type change, ban lift) even when the device is offline. The request is presented to the parent via their app or a voice code that can be read over the phone. The parent approves or denies from their end, and the device applies the result when connectivity resumes (or immediately via a voice code response entered locally).
- **Automatic resync** -- when the device comes back online, it immediately fetches the latest permissions, processes any queued requests, and resumes normal check polling.

This means a paired device is never "unmanageable" -- the parent always has control, regardless of the device's network state.

## License

See [LICENSE](LICENSE) for details.
