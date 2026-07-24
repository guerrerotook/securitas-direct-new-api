"""Pydantic domain models for the Verisure OWA API.

Re-exports every public model so existing call sites that import from
``verisure_owa_api.models`` keep working after the per-domain split.
"""

from .activity import (
    ActivityCategory,
    ActivityEvent,
    ActivityException,
)
from .alarm import (
    PROTO_TO_STATE,
    STATE_TO_COMMAND,
    STATE_TO_PROTO,
    AlarmState,
    AnnexMode,
    ArmCommand,
    InteriorMode,
    OperationStatus,
    PerimeterMode,
    ProtoCode,
    SStatus,
    is_proto_letter,
    parse_proto_code,
)
from .auth import OtpPhone
from .camera import CameraDevice, ThumbnailResponse
from .contact import ContactDevice, ContactState, TimedValue
from .installation import Installation
from .lock import (
    LockAutolock,
    LockFeatures,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
)
from .sentinel import AirQuality, Sentinel
from .services import Attribute, Service

__all__ = [
    "PROTO_TO_STATE",
    "STATE_TO_COMMAND",
    "STATE_TO_PROTO",
    "ActivityCategory",
    "ActivityEvent",
    "ActivityException",
    "AirQuality",
    "AlarmState",
    "AnnexMode",
    "ArmCommand",
    "Attribute",
    "CameraDevice",
    "ContactDevice",
    "ContactState",
    "Installation",
    "InteriorMode",
    "LockAutolock",
    "LockFeatures",
    "OperationStatus",
    "OtpPhone",
    "PerimeterMode",
    "ProtoCode",
    "SStatus",
    "Sentinel",
    "Service",
    "SmartLock",
    "SmartLockMode",
    "SmartLockModeStatus",
    "ThumbnailResponse",
    "TimedValue",
    "is_proto_letter",
    "parse_proto_code",
]
