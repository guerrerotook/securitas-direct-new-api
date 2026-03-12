"""Public datatypes for the securitas direct API."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


@dataclass
class Installation:
    """Define an Securitas Direct Installation."""

    number: str = ""
    alias: str = ""
    panel: str = ""
    type: str = ""
    name: str = ""
    lastName: str = ""
    address: str = ""
    city: str = ""
    postalCode: str = ""
    province: str = ""
    email: str = ""
    phone: str = ""
    capabilities: str = ""
    capabilities_exp: datetime = datetime.min
    alarm_partitions: list[dict] = field(default_factory=list)


@dataclass
class OperationStatus:
    """Result of an alarm or lock operation (arm, disarm, check)."""

    operation_status: str = ""
    message: str = ""
    status: str = ""
    installation_number: str = ""
    protomResponse: str = ""
    protomResponseData: str = ""
    requestId: str = ""
    error: str | None = ""
    numinst: str = ""


class ArmType(Enum):
    """Define an Securitas Direct Arm Type."""

    TOTAL = 1


@dataclass
class SStatus:
    """Define the current status of the alarm."""

    status: str | None = ""
    timestampUpdate: str | None = ""
    wifi_connected: bool | None = None


@dataclass
class Attribute:
    """Attribute for the service."""

    name: str = ""
    value: str = ""
    active: bool = False


@dataclass
class Attributes:
    """Attribute collection."""

    name: str
    attributes: list[Attribute]


@dataclass
class Service:
    """Define a Securitas Direct service."""

    id: int
    id_service: int
    active: bool
    visible: bool
    bde: bool
    is_premium: bool
    cod_oper: bool
    total_device: int
    request: str
    multiple_req: bool
    num_devices_mr: int
    secret_word: bool
    min_wrapper_version: None
    description: str
    attributes: Attributes | list[Attribute]
    listdiy: list[Any]
    listprompt: list[Any]
    installation: Installation


@dataclass
class Sentinel:
    """Sentinel status."""

    alias: str
    air_quality: str
    humidity: int
    temperature: int
    zone: str = ""


@dataclass
class AirQuality:
    """Air Quality from xSAirQuality API."""

    value: int
    status_current: int = 0


@dataclass
class OtpPhone:
    """Otp Phone item."""

    id: int
    phone: str


@dataclass
class SmartLock:
    """Smart lock discovery response."""

    res: str | None = None
    location: str | None = None
    type: int | None = None
    deviceId: str = ""
    referenceId: str = ""
    zoneId: str = ""
    serialNumber: str = ""
    family: str = ""
    label: str = ""


@dataclass
class SmartLockMode:
    """Smart lock mode and status."""

    res: str | None = None
    lockStatus: str = ""
    deviceId: str = ""
    statusTimestamp: str = ""


@dataclass
class SmartLockModeStatus:
    """Smart lock mode change operation status."""

    requestId: str = ""
    message: str = ""
    protomResponse: str = ""
    status: str = ""


@dataclass
class DanalockAutolock:
    """Danalock auto-lock configuration."""

    active: bool | None = None
    timeout: int | None = None


@dataclass
class DanalockFeatures:
    """Danalock feature configuration."""

    holdBackLatchTime: int = 0
    calibrationType: int = 0
    autolock: DanalockAutolock | None = None


@dataclass
class DanalockConfig:
    """Full Danalock configuration from xSGetDanalockConfig."""

    action: str = ""
    deviceNumber: str = ""
    asyncCylinder: str | None = None
    batteryLowPercentage: str = ""
    lockBeforePartialArm: str = ""
    lockBeforeFullArm: str = ""
    unlockAfterDisarm: str = ""
    lockBeforePerimeterArm: str = ""
    periodicBitExtension: str = ""
    autoLockTime: str = ""
    features: DanalockFeatures | None = None


@dataclass
class CameraDevice:
    """A camera device from xSDeviceList (type YR for PIR cameras, QR in some regions)."""

    id: str = ""
    code: int = 0
    zone_id: str = ""
    name: str = ""
    serial_number: str | None = None


@dataclass
class ThumbnailResponse:
    """Response from xSGetThumbnail."""

    id_signal: str | None = None
    device_code: str | None = None
    device_alias: str | None = None
    timestamp: str | None = None
    signal_type: str | None = None
    image: str | None = None
