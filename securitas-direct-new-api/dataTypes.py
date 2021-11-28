from dataclasses import dataclass

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