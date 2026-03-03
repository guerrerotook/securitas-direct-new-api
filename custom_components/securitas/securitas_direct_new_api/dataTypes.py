"""Public datatypes for the securitas direct API."""

from dataclasses import dataclass
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


@dataclass
class CheckAlarmStatus:
    """Define an Securitas Direct Alarm Check Status Operation."""

    operation_status: str = ""
    message: str = ""
    status: str = ""
    InstallationNumer: str = ""
    protomResponse: str = ""
    protomResponseData: str = ""


@dataclass
class ArmStatus:
    """Define a Securitas Direct Arm Alarm Status Operation."""

    operation_status: str = ""
    message: str = ""
    status: str = ""
    InstallationNumer: str = ""
    protomResponse: str = ""
    protomResponseData: str = ""
    requestId: str = ""
    error: str = ""


@dataclass
class DisarmStatus:
    """Define a Securitas Direct Disarm Alarm Status Operation."""

    error: str | None = ""
    message: str = ""
    numinst: str = ""
    protomResponse: str = ""
    protomResponseData: str = ""
    requestId: str = ""
    operation_status: str = ""
    status: str = ""


class ArmType(Enum):
    """Define an Securitas Direct Arm Type."""

    TOTAL = 1


@dataclass
class SStatus:
    """Define the current status of the alarm."""

    status: str | None = ""
    timestampUpdate: str | None = ""
    wifi_connected: bool | None = None
    keep_alive_day: int | None = None
    confort_message: str | None = None


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
    """Air Quality."""

    value: int
    message: str


@dataclass
class OtpPhone:
    """Otp Phone item."""

    id: int
    phone: str


@dataclass
class SmartLock:
    res: str | None = None
    location: str | None = None
    type: int | None = None


@dataclass
class SmartLockMode:
    res: str | None = None
    lockStatus: str = ""
    deviceId: str = ""


@dataclass
class SmartLockModeStatus:
    requestId: str = ""
    message: str = ""
    protomResponse: str = ""
    status: str = ""
