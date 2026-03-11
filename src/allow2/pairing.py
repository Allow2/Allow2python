from __future__ import annotations

import asyncio
import logging
import uuid as uuid_mod
from typing import Any

from allow2.api import Allow2Api
from allow2.events import EventEmitter
from allow2.models import Credentials, PairingInfo

logger = logging.getLogger("allow2.pairing")


class PairingWizard(EventEmitter):
    """Manages one-time device pairing. Parents NEVER enter credentials on device."""

    def __init__(
        self,
        *,
        api: Allow2Api,
        credential_backend: Any,
        port: int = 3000,
        device_name: str = "Python Device",
        uuid: str | None = None,
    ) -> None:
        super().__init__()
        self._api = api
        self._credential_backend = credential_backend
        self._port = port
        self._device_name = device_name
        self._uuid = uuid

        self._pin: str | None = None
        self._session_id: str | None = None
        self._paired = False
        self._pairing_result: dict[str, Any] | None = None
        self._poll_task: asyncio.Task[None] | None = None
        self._init_retry_task: asyncio.Task[None] | None = None
        self._qr_url: str | None = None
        self._connected = False
        self._consecutive_errors = 0
        self._server: Any = None

    async def start(self) -> PairingInfo:
        if self._poll_task is not None or self._init_retry_task is not None:
            logger.warning("start() called but already running -- ignoring")
            return PairingInfo(
                pin=self._pin or "------",
                port=self._port,
                url=f"http://localhost:{self._port}",
                qr_url=self._qr_url or "",
                connected=self._connected,
            )

        self._paired = False
        self._pairing_result = None

        if not self._uuid:
            self._uuid = await self._load_or_create_uuid()

        api_result: dict[str, Any] | None = None
        try:
            logger.info(
                "Calling initPINPairing (uuid=%s, device=%s)",
                self._uuid, self._device_name,
            )
            api_result = await self._api.init_pin_pairing(
                uuid=self._uuid,
                device_name=self._device_name,
            )
        except Exception as err:
            logger.warning("API initPINPairing failed: %s -- falling back", err)
            api_result = None

        if api_result and api_result.get("pin"):
            self._pin = str(api_result["pin"])
            self._session_id = (
                api_result.get("sessionId")
                or api_result.get("pairingSessionId")
            )
            self._connected = True
            self._consecutive_errors = 0
        else:
            self._pin = "------"
            self._session_id = None
            self._connected = False
            logger.warning("API unreachable -- will retry")
            self._start_init_retry()

        self._qr_url = f"https://app.allow2.com/pair?pin={self._pin}"

        try:
            await self._start_http_server()
        except Exception as err:
            logger.warning(
                "HTTP server failed on port %d: %s -- pairing still works via PIN/QR",
                self._port, err,
            )
            self._server = None

        if self._session_id:
            self._start_polling()

        info = PairingInfo(
            pin=self._pin,
            port=self._port,
            url=f"http://localhost:{self._port}",
            qr_url=self._qr_url,
            connected=self._connected,
        )
        self.emit("started", {
            "pin": self._pin,
            "port": self._port,
            "qrUrl": self._qr_url,
            "connected": self._connected,
        })
        return info

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except (asyncio.CancelledError, Exception):
                pass
            self._poll_task = None

        if self._init_retry_task is not None:
            self._init_retry_task.cancel()
            try:
                await self._init_retry_task
            except (asyncio.CancelledError, Exception):
                pass
            self._init_retry_task = None

        if self._server is not None:
            try:
                await self._server.shutdown()
            except Exception:
                pass
            self._server = None

    def get_pin(self) -> str | None:
        return self._pin

    def get_qr_url(self) -> str | None:
        return self._qr_url

    async def complete_pairing(self, pairing_data: dict[str, Any]) -> Credentials:
        if not pairing_data.get("userId") or not pairing_data.get("pairId") or not pairing_data.get("pairToken"):
            raise ValueError(
                "Pairing callback missing required fields (userId, pairId, pairToken)"
            )

        from allow2.models import Child

        children_raw = pairing_data.get("children", [])
        children = [
            Child.from_dict(c) if isinstance(c, dict) else c
            for c in children_raw
        ]

        credentials = Credentials(
            uuid=self._uuid or "",
            user_id=pairing_data["userId"],
            pair_id=pairing_data["pairId"],
            pair_token=pairing_data["pairToken"],
            children=children,
        )

        await self._credential_backend.store(credentials.to_dict())

        self._paired = True
        self._pairing_result = credentials.to_dict()
        self.emit("paired", credentials)

        await self.stop()
        return credentials

    async def _load_or_create_uuid(self) -> str:
        try:
            creds = await self._credential_backend.load()
            if creds and creds.get("uuid"):
                return creds["uuid"]
        except Exception:
            pass

        new_uuid = str(uuid_mod.uuid4())
        try:
            await self._credential_backend.store({"uuid": new_uuid})
        except Exception:
            pass
        return new_uuid

    def _start_init_retry(self) -> None:
        if self._init_retry_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
            self._init_retry_task = loop.create_task(self._init_retry_loop())
        except RuntimeError:
            pass

    async def _init_retry_loop(self) -> None:
        while not self._paired and self._session_id is None:
            await asyncio.sleep(5)
            try:
                result = await self._api.init_pin_pairing(
                    uuid=self._uuid or "",
                    device_name=self._device_name,
                )
                if result and result.get("pin"):
                    self._pin = str(result["pin"])
                    self._session_id = (
                        result.get("sessionId")
                        or result.get("pairingSessionId")
                    )
                    self._qr_url = f"https://app.allow2.com/pair?pin={self._pin}"
                    self._connected = True
                    self._consecutive_errors = 0
                    logger.info("Reconnected! PIN: %s (session=%s)", self._pin, self._session_id)
                    self.emit("connection-status", {
                        "connected": True,
                        "pin": self._pin,
                        "qrUrl": self._qr_url,
                    })
                    self._start_polling()
                    break
            except Exception as err:
                logger.warning("Init retry failed: %s", err)
                self.emit("connection-status", {"connected": False})

        self._init_retry_task = None

    def _start_polling(self) -> None:
        if self._poll_task is not None:
            return
        try:
            loop = asyncio.get_running_loop()
            self._poll_task = loop.create_task(self._poll_loop())
        except RuntimeError:
            pass

    async def _poll_loop(self) -> None:
        poll_count = 0
        max_polls = 360

        while not self._paired:
            await asyncio.sleep(5)
            poll_count += 1

            if poll_count > max_polls:
                self.emit("error", Exception("Pairing timed out after 30 minutes"))
                break

            try:
                result = await self._api.check_pairing_status(self._session_id or "")
                if (
                    result
                    and result.get("paired")
                    and result.get("userId")
                    and result.get("pairId")
                    and result.get("pairToken")
                ):
                    await self.complete_pairing(result)
                    break

                if not self._connected:
                    self._connected = True
                    self._consecutive_errors = 0
                    logger.info("Connection restored")
                    self.emit("connection-status", {"connected": True})
            except Exception as err:
                self._consecutive_errors += 1
                if self._consecutive_errors >= 2 and self._connected:
                    self._connected = False
                    logger.warning("Connection lost: %s", err)
                    self.emit("connection-status", {"connected": False})
                if poll_count % 12 == 0:
                    logger.warning("Poll error: %s", err)

        self._poll_task = None

    async def _start_http_server(self) -> None:
        try:
            import aiohttp.web as web
        except ImportError:
            return

        app = web.Application()
        wizard = self

        async def handle_root(_request: Any) -> Any:
            return web.Response(
                text=_build_pairing_page(wizard._pin or "", wizard._port, wizard._qr_url or ""),
                content_type="text/html",
            )

        async def handle_status(_request: Any) -> Any:
            return web.json_response({
                "paired": wizard._paired,
                "result": {"userId": wizard._pairing_result.get("userId")} if wizard._paired and wizard._pairing_result else None,
            })

        async def handle_callback(request: Any) -> Any:
            if wizard._paired:
                return web.json_response({"error": "Already paired"}, status=409)
            body = await request.json()
            if not body or not body.get("userId") or not body.get("pairId") or not body.get("pairToken"):
                return web.json_response(
                    {"error": "Missing required fields (userId, pairId, pairToken)"},
                    status=400,
                )
            try:
                credentials = await wizard.complete_pairing(body)
                return web.json_response({"success": True, "userId": credentials.user_id})
            except Exception as err:
                return web.json_response({"error": str(err)}, status=500)

        async def handle_success(_request: Any) -> Any:
            return web.Response(text=_build_success_page(), content_type="text/html")

        app.router.add_get("/", handle_root)
        app.router.add_get("/status", handle_status)
        app.router.add_post("/pair-callback", handle_callback)
        app.router.add_get("/success", handle_success)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "localhost", self._port)
        await site.start()
        self._server = runner


def _build_pairing_page(pin: str, port: int, qr_url: str) -> str:
    digits = "".join(f'<span class="digit">{d}</span>' for d in pin)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Allow2 - Device Pairing</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  min-height: 100vh; display: flex; align-items: center; justify-content: center;
}}
.card {{ background: #fff; border-radius: 16px; padding: 48px 40px; max-width: 480px; width: 90%; text-align: center; }}
.logo {{ font-size: 28px; font-weight: 700; color: #667eea; margin-bottom: 8px; }}
.subtitle {{ font-size: 14px; color: #888; margin-bottom: 32px; }}
.pin-display {{ display: flex; justify-content: center; gap: 10px; margin: 32px 0; }}
.digit {{ display: inline-flex; align-items: center; justify-content: center; width: 56px; height: 68px; font-size: 36px; font-weight: 700; background: #f0f2ff; border: 2px solid #dde0f5; border-radius: 12px; }}
.status {{ font-size: 14px; color: #888; margin-top: 32px; }}
</style>
</head>
<body>
<div class="card">
  <div class="logo">Allow2</div>
  <div class="subtitle">Device Pairing</div>
  <p>Enter this PIN in the Allow2 app on your phone to pair this device.</p>
  <div class="pin-display">{digits}</div>
  <div class="status">Waiting for parent to confirm...</div>
</div>
<script>
(function() {{
  function checkStatus() {{
    var xhr = new XMLHttpRequest();
    xhr.open("GET", "/status", true);
    xhr.onload = function() {{
      if (xhr.status === 200) {{
        try {{
          var data = JSON.parse(xhr.responseText);
          if (data.paired) {{ window.location.href = "/success"; return; }}
        }} catch (e) {{}}
      }}
      setTimeout(checkStatus, 2000);
    }};
    xhr.onerror = function() {{ setTimeout(checkStatus, 2000); }};
    xhr.send();
  }}
  setTimeout(checkStatus, 2000);
}})();
</script>
</body>
</html>"""


def _build_success_page() -> str:
    return """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Allow2 - Paired Successfully</title>
<style>
body { font-family: sans-serif; background: #48bb78; min-height: 100vh; display: flex; align-items: center; justify-content: center; }
.card { background: #fff; border-radius: 16px; padding: 48px 40px; max-width: 480px; text-align: center; }
.logo { font-size: 28px; font-weight: 700; color: #48bb78; }
.message { font-size: 20px; margin: 16px 0 8px; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">Allow2</div>
  <div class="message">Device Paired Successfully</div>
  <p>This device is now connected to your Allow2 account. You can close this window.</p>
</div>
</body>
</html>"""
