"""Public datatypes for the securitas direct API."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, List


@dataclass
class Installation:
    """Define an Securitas Direct Installation."""

    number: int
    alias: str
    panel: str
    type: str
    name: str
    lastName: str
    address: str
    city: str
    postalCode: int
    province: str
    email: str
    phone: str


@dataclass
class CheckAlarmStatus:
    """Define an Securitas Direct Alarm Check Status Operation."""

    operation_status: str
    message: str
    status: str
    InstallationNumer: int
    protomResponse: str
    protomResponseData: str


@dataclass
class ArmStatus:
    """Define a Securitas Direct Arm Alarm Status Operation."""

    operation_status: str
    message: str
    status: int
    InstallationNumer: int
    protomResponse: str
    protomResponseData: str
    requestId: str
    error: str


@dataclass
class DisarmStatus:
    """Define a Securitas Direct Disarm Alarm Status Operation."""

    error: str
    message: str
    numinst: str
    protomResponse: str
    protomResponseData: str
    requestId: str
    operation_status: str
    status: str


@dataclass
class ArmType(Enum):
    """Define an Securitas Direct Arm Type."""

    TOTAL = 1


@dataclass
class SStatus:
    """Define the current status of the alarm."""

    status: str
    timestampUpdate: str


@dataclass
class Attribute:
    """Attribute for the service."""

    name: str
    value: str
    active: bool


@dataclass
class Attributes:
    """Attribute collection."""

    name: str
    attributes: List[Attribute]


@dataclass
class Service:
    """Define a securitas direct service."""

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
    loc: str
    unprotect_active: bool
    unprotect_device_status: None
    devices: List[Any]
    cameras_arlo: List[Any]
    attributes: Attributes
    listdiy: List[Any]
    listprompt: List[Any]
    installation: Installation


@dataclass
class Sentinel:
    """Sentinel status."""

    alias: str
    air_quality: str
    humidity: int
    temperature: int


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
