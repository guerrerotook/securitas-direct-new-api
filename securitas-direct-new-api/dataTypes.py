from dataclasses import dataclass
from enum import Enum

@dataclass
class instalation:
    """Define an Securitas Direct instalation. """
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
    operationStatus: str
    message: str
    status: int
    instalationNumer: int
    protomResponse: str
    protomResponseData: str

@dataclass
class ArmStatus:
    operationStatus: str
    message : str
    status : int
    instalationNumer: int
    protomResponse: str
    protomResponseData: str
    requestId : str
    error : str

class ArmType(Enum):
    TOTAL = 1