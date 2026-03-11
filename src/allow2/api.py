from __future__ import annotations

import os
import warnings
from typing import Any

import httpx

DEFAULT_API_URL = "https://api.allow2.com"
DEFAULT_VID = 0
DEFAULT_TOKEN = ""


class Allow2ApiError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.body = body


class Allow2Api:
    """Low-level async HTTP client for the Allow2 REST API."""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        vid: int | None = None,
        token: str | None = None,
        timeout: float = 15.0,
    ) -> None:
        self._base_url = api_url or os.environ.get("ALLOW2_API_URL") or DEFAULT_API_URL
        self._timeout = timeout

        env_vid = os.environ.get("ALLOW2_VID")
        self._vid = vid or (int(env_vid) if env_vid else 0) or DEFAULT_VID
        self._token = token or os.environ.get("ALLOW2_TOKEN") or DEFAULT_TOKEN

        if not self._vid or not self._token:
            warnings.warn(
                "Allow2 API: VID/Token not configured. "
                "Set ALLOW2_VID and ALLOW2_TOKEN environment variables, "
                "or pass vid/token in options.",
                stacklevel=2,
            )

        self._client: httpx.AsyncClient | None = None

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def vid(self) -> int:
        return self._vid

    @property
    def token(self) -> str:
        return self._token

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout),
            )
        return self._client

    async def close(self) -> None:
        if self._client is not None and not self._client.is_closed:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Allow2Api:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def _fetch(
        self,
        path: str,
        *,
        method: str = "GET",
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        url = self._base_url + path
        client = self._get_client()

        req_headers: dict[str, str] = {"Content-Type": "application/json"}
        if headers:
            req_headers.update(headers)

        response = await client.request(
            method,
            url,
            json=json_body if json_body is not None else None,
            headers=req_headers,
        )

        body: dict[str, Any] | None = None
        try:
            body = response.json()
        except Exception:
            if not response.is_success:
                raise Allow2ApiError(
                    f"API error {response.status_code}",
                    status=response.status_code,
                )
            raise Allow2ApiError(
                "Unexpected non-JSON response from API",
                status=response.status_code,
            )

        if not response.is_success:
            msg = (body.get("message") if body else None) or f"API error {response.status_code}"
            raise Allow2ApiError(
                msg,
                status=response.status_code,
                code=body.get("code") if body else None,
                body=body,
            )

        return body  # type: ignore[return-value]

    async def init_qr_pairing(
        self,
        *,
        uuid: str,
        device_name: str,
        platform: str = "python",
    ) -> dict[str, Any]:
        return await self._fetch("/api/pair/qr/init", method="POST", json_body={
            "uuid": uuid,
            "name": device_name,
            "deviceToken": self._token,
            "vid": self._vid,
            "platform": platform,
        })

    async def init_pin_pairing(
        self,
        *,
        uuid: str,
        device_name: str,
        platform: str = "python",
    ) -> dict[str, Any]:
        return await self._fetch("/api/pair/pin/init", method="POST", json_body={
            "uuid": uuid,
            "name": device_name,
            "deviceToken": self._token,
            "vid": self._vid,
            "platform": platform,
        })

    async def check_pairing_status(self, pairing_session_id: str) -> dict[str, Any]:
        return await self._fetch(f"/api/pair/status/{pairing_session_id}")

    async def check(
        self,
        *,
        user_id: int,
        pair_id: int,
        pair_token: str,
        child_id: int,
        activities: dict[str, int],
        tz: str,
        log: bool = True,
    ) -> dict[str, Any]:
        return await self._fetch("/serviceapi/check", method="POST", json_body={
            "userId": user_id,
            "pairId": pair_id,
            "pairToken": pair_token,
            "deviceToken": self._token,
            "tz": tz,
            "childId": child_id,
            "activities": activities,
            "log": log,
        })

    async def get_updates(
        self,
        *,
        user_id: int,
        pair_id: int,
        pair_token: str,
        timestamp_millis: int | None = None,
    ) -> dict[str, Any]:
        params: dict[str, str] = {
            "userId": str(user_id),
            "pairId": str(pair_id),
            "pairToken": pair_token,
            "deviceToken": self._token,
        }
        if timestamp_millis is not None:
            params["timestampMillis"] = str(timestamp_millis)

        query = "&".join(f"{k}={v}" for k, v in params.items())
        return await self._fetch(f"/api/getUpdates?{query}")

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
    ) -> dict[str, Any]:
        return await self._fetch("/api/request/createRequest", method="POST", json_body={
            "userId": user_id,
            "pairId": pair_id,
            "pairToken": pair_token,
            "childId": child_id,
            "duration": duration,
            "activity": activity,
            "message": message,
        })

    async def get_request_status(
        self, request_id: str, status_secret: str
    ) -> dict[str, Any]:
        return await self._fetch(
            f"/api/request/{request_id}/status",
            headers={"X-Status-Secret": status_secret},
        )

    async def submit_feedback(
        self,
        *,
        user_id: int,
        pair_id: int,
        pair_token: str,
        child_id: int | None = None,
        vid: int | None = None,
        category: str,
        message: str,
        device_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return await self._fetch("/api/feedback/submit", method="POST", json_body={
            "userId": user_id,
            "pairId": pair_id,
            "pairToken": pair_token,
            "childId": child_id,
            "vid": vid or self._vid,
            "category": category,
            "message": message,
            "deviceContext": device_context,
        })

    async def load_feedback(
        self,
        *,
        user_id: int,
        pair_id: int,
        pair_token: str,
    ) -> dict[str, Any]:
        return await self._fetch("/api/feedback/load", method="POST", json_body={
            "userId": user_id,
            "pairId": pair_id,
            "pairToken": pair_token,
        })

    async def feedback_reply(
        self,
        *,
        user_id: int,
        pair_id: int,
        pair_token: str,
        discussion_id: str,
        message: str,
    ) -> dict[str, Any]:
        return await self._fetch("/api/feedback/reply", method="POST", json_body={
            "userId": user_id,
            "pairId": pair_id,
            "pairToken": pair_token,
            "discussionId": discussion_id,
            "message": message,
        })

    async def log_usage(
        self,
        *,
        user_id: int,
        pair_id: int,
        pair_token: str,
        child_id: int,
        activities: dict[str, Any],
    ) -> dict[str, Any]:
        return await self._fetch("/api/logUsage", method="POST", json_body={
            "userId": user_id,
            "pairId": pair_id,
            "pairToken": pair_token,
            "deviceToken": self._token,
            "childId": child_id,
            "activities": activities,
        })
