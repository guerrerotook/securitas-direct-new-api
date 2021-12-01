"""Public datatypes for the securitas direct API."""
from dataclasses import dataclass
from enum import Enum


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

    operationStatus: str
    message: str
    status: str
    InstallationNumer: int
    protomResponse: str
    protomResponseData: str


@dataclass
class ArmStatus:
    """Define a Securitas Direct Arm Alarm Status Operation."""

    operationStatus: str
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
    operationStatus: str
    status: str


class ArmType(Enum):
    """Define an Securitas Direct Arm Type."""

    TOTAL = 1
