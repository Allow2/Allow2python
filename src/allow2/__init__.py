"""Allow2 Device SDK -- Parental Freedom for apps and devices."""

from allow2.daemon import DeviceDaemon
from allow2.child_shield import ChildShield
from allow2.api import Allow2Api, Allow2ApiError
from allow2.events import EventEmitter
from allow2.models import (
    Activity,
    Child,
    Credentials,
    DaemonState,
    DeviceContext,
    FeedbackCategory,
    PairingInfo,
    RequestResult,
    VerificationLevel,
    WarningLevel,
    WarningThreshold,
)
from allow2.credentials.plaintext import PlaintextBackend

__version__ = "2.0.0a1"

__all__ = [
    "DeviceDaemon",
    "ChildShield",
    "Allow2Api",
    "Allow2ApiError",
    "EventEmitter",
    "PlaintextBackend",
    "Activity",
    "Child",
    "Credentials",
    "DaemonState",
    "DeviceContext",
    "FeedbackCategory",
    "PairingInfo",
    "RequestResult",
    "VerificationLevel",
    "WarningLevel",
    "WarningThreshold",
]
