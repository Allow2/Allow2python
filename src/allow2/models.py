from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class DaemonState(str, Enum):
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
    id: int

    def to_check_map(self) -> dict[str, int]:
        return {str(self.id): 1}


@dataclass
class Child:
    id: int
    name: str
    pin_hash: str | None = None
    pin_salt: str | None = None
    avatar_url: str | None = None
    color: str | None = None
    has_account: bool = False
    linked_user_id: int | None = None
    os_username: str | None = None
    last_used_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "pinHash": self.pin_hash,
            "pinSalt": self.pin_salt,
            "avatarUrl": self.avatar_url,
            "color": self.color,
            "hasAccount": self.has_account,
            "LinkedUserId": self.linked_user_id,
            "osUsername": self.os_username,
            "lastUsedAt": self.last_used_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Child:
        return cls(
            id=data.get("id") or data.get("childId", 0),
            name=data.get("name", ""),
            pin_hash=data.get("pinHash"),
            pin_salt=data.get("pinSalt"),
            avatar_url=data.get("avatarUrl"),
            color=data.get("color"),
            has_account=bool(data.get("hasAccount", False)),
            linked_user_id=data.get("LinkedUserId") or data.get("linkedUserId"),
            os_username=data.get("osUsername"),
            last_used_at=data.get("lastUsedAt"),
        )

    def safe_copy(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "avatarUrl": self.avatar_url,
            "color": self.color,
            "hasAccount": self.has_account,
        }


@dataclass
class Credentials:
    uuid: str
    user_id: int
    pair_id: int
    pair_token: str
    children: list[Child] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "uuid": self.uuid,
            "userId": self.user_id,
            "pairId": self.pair_id,
            "pairToken": self.pair_token,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Credentials:
        children_raw = data.get("children", [])
        children = [
            Child.from_dict(c) if isinstance(c, dict) else c
            for c in children_raw
        ]
        return cls(
            uuid=data.get("uuid", ""),
            user_id=data.get("userId", 0),
            pair_id=data.get("pairId", 0),
            pair_token=data.get("pairToken", ""),
            children=children,
        )


@dataclass
class ActivityState:
    allowed: bool
    remaining: float = math.inf


@dataclass
class CheckResult:
    activities: dict[str, ActivityState] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class WarningThreshold:
    remaining: int
    level: WarningLevel


@dataclass
class PairingInfo:
    pin: str
    port: int
    url: str
    qr_url: str
    connected: bool


@dataclass
class RequestResult:
    request_id: str
    status_secret: str


@dataclass
class DeviceContext:
    device_name: str = "Allow2 Device"
    platform: str = "python"
    sdk_version: str = "2.0.0"
    product_name: str = "allow2"

    def to_dict(self) -> dict[str, Any]:
        return {
            "deviceName": self.device_name,
            "platform": self.platform,
            "sdkVersion": self.sdk_version,
            "productName": self.product_name,
        }
