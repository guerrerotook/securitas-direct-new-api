"""Public datatypes for the securitas direct API."""
from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass
class Installation:
    """Define an Securitas Direct Installation."""

    number: int = 0
    alias: str = ""
    panel: str = ""
    type: str = ""
    name: str = ""
    lastName: str = ""
    address: str = ""
    city: str = ""
    postalCode: int = 0
    province: str = ""
    email: str = ""
    phone: str = ""
    capabilities: str = ""


@dataclass
class CheckAlarmStatus:
    """Define an Securitas Direct Alarm Check Status Operation."""

    operation_status: str = ""
    message: str = ""
    status: str = ""
    InstallationNumer: int = 0
    protomResponse: str = ""
    protomResponseData: str = ""


@dataclass
class ArmStatus:
    """Define a Securitas Direct Arm Alarm Status Operation."""

    operation_status: str = ""
    message: str = ""
    status: int = ""
    InstallationNumer: int = 0
    protomResponse: str = ""
    protomResponseData: str = ""
    requestId: str = ""
    error: str = ""


@dataclass
class DisarmStatus:
    """Define a Securitas Direct Disarm Alarm Status Operation."""

    error: str = ""
    message: str = ""
    numinst: str = ""
    protomResponse: str = ""
    protomResponseData: str = ""
    requestId: str = ""
    operation_status: str = ""
    status: str = ""


@dataclass
class ArmType(Enum):
    """Define an Securitas Direct Arm Type."""

    TOTAL = 1


@dataclass
class SStatus:
    """Define the current status of the alarm."""

    status: str = ""
    timestampUpdate: str = ""


@dataclass
class Attribute:
    """Attribute for the service."""

    name: str = ""
    value: str = ""
    active: bool = False


@dataclass
class Attributes:
    """Attribute collection."""

    name: str = ""
    attributes: list[Attribute] = []


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
    attributes: Attributes
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
