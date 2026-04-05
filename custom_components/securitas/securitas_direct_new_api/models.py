"""Pydantic domain models for the Securitas Direct API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .exceptions import UnexpectedStateError


# ── Enums ─────────────────────────────────────────────────────────────────────


class InteriorMode(StrEnum):
    """Interior alarm mode."""

    OFF = "off"
    DAY = "day"
    NIGHT = "night"
    TOTAL = "total"


class PerimeterMode(StrEnum):
    """Perimeter alarm mode."""

    OFF = "off"
    ON = "on"


class ProtoCode(StrEnum):
    """Protocol response codes from the Securitas Direct API."""

    DISARMED = "D"
    PERIMETER_ONLY = "E"
    PARTIAL_DAY = "P"
    PARTIAL_NIGHT = "Q"
    PARTIAL_DAY_PERIMETER = "B"
    PARTIAL_NIGHT_PERIMETER = "C"
    TOTAL = "T"
    TOTAL_PERIMETER = "A"


class ArmCommand(StrEnum):
    """Arm/disarm command strings sent to the API."""

    DISARM = "DARM1"
    DISARM_ALL = "DARM1DARMPERI"
    ARM_DAY = "ARMDAY1"
    ARM_NIGHT = "ARMNIGHT1"
    ARM_TOTAL = "ARM1"
    ARM_PERIMETER = "PERI1"
    ARM_DAY_PERIMETER = "ARMDAY1PERI1"
    ARM_NIGHT_PERIMETER = "ARMNIGHT1PERI1"
    ARM_TOTAL_PERIMETER = "ARM1PERI1"


# ── AlarmState ────────────────────────────────────────────────────────────────


class AlarmState(BaseModel):
    """Two-axis alarm state: interior mode + perimeter on/off."""

    model_config = ConfigDict(frozen=True)

    interior: InteriorMode
    perimeter: PerimeterMode

    def __hash__(self) -> int:
        return hash((self.interior, self.perimeter))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AlarmState):
            return NotImplemented
        return self.interior == other.interior and self.perimeter == other.perimeter


# ── parse_proto_code ──────────────────────────────────────────────────────────


def parse_proto_code(code: str) -> ProtoCode:
    """Parse a raw protocol code string into a ProtoCode enum.

    Raises UnexpectedStateError for unknown codes.
    """
    try:
        return ProtoCode(code)
    except ValueError as exc:
        raise UnexpectedStateError(code) from exc


# ── Mapping tables ────────────────────────────────────────────────────────────

PROTO_TO_STATE: dict[ProtoCode, AlarmState] = {
    ProtoCode.DISARMED: AlarmState(
        interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF
    ),
    ProtoCode.PERIMETER_ONLY: AlarmState(
        interior=InteriorMode.OFF, perimeter=PerimeterMode.ON
    ),
    ProtoCode.PARTIAL_DAY: AlarmState(
        interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF
    ),
    ProtoCode.PARTIAL_NIGHT: AlarmState(
        interior=InteriorMode.NIGHT, perimeter=PerimeterMode.OFF
    ),
    ProtoCode.PARTIAL_DAY_PERIMETER: AlarmState(
        interior=InteriorMode.DAY, perimeter=PerimeterMode.ON
    ),
    ProtoCode.PARTIAL_NIGHT_PERIMETER: AlarmState(
        interior=InteriorMode.NIGHT, perimeter=PerimeterMode.ON
    ),
    ProtoCode.TOTAL: AlarmState(
        interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF
    ),
    ProtoCode.TOTAL_PERIMETER: AlarmState(
        interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON
    ),
}

STATE_TO_PROTO: dict[AlarmState, ProtoCode] = {v: k for k, v in PROTO_TO_STATE.items()}

STATE_TO_COMMAND: dict[AlarmState, ArmCommand] = {
    AlarmState(
        interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF
    ): ArmCommand.DISARM,
    AlarmState(
        interior=InteriorMode.OFF, perimeter=PerimeterMode.ON
    ): ArmCommand.ARM_PERIMETER,
    AlarmState(
        interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF
    ): ArmCommand.ARM_DAY,
    AlarmState(
        interior=InteriorMode.NIGHT, perimeter=PerimeterMode.OFF
    ): ArmCommand.ARM_NIGHT,
    AlarmState(
        interior=InteriorMode.DAY, perimeter=PerimeterMode.ON
    ): ArmCommand.ARM_DAY_PERIMETER,
    AlarmState(
        interior=InteriorMode.NIGHT, perimeter=PerimeterMode.ON
    ): ArmCommand.ARM_NIGHT_PERIMETER,
    AlarmState(
        interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF
    ): ArmCommand.ARM_TOTAL,
    AlarmState(
        interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON
    ): ArmCommand.ARM_TOTAL_PERIMETER,
}


# ── Domain models ─────────────────────────────────────────────────────────────


class Installation(BaseModel):
    """A Securitas Direct installation (customer site)."""

    model_config = ConfigDict(populate_by_name=True)

    number: str = Field(default="", validation_alias="numinst")
    alias: str = ""
    panel: str = ""
    type: str = ""
    name: str = ""
    last_name: str = Field(default="", validation_alias="surname")
    address: str = ""
    city: str = ""
    postal_code: str = Field(default="", validation_alias="postcode")
    province: str = ""
    email: str = ""
    phone: str = ""
    capabilities: str = ""
    capabilities_exp: datetime = Field(default=datetime.min)
    alarm_partitions: list[dict[str, Any]] = Field(default_factory=list)


class OperationStatus(BaseModel):
    """Result of an alarm or lock operation (arm, disarm, check)."""

    model_config = ConfigDict(populate_by_name=True)

    operation_status: str = Field(default="", validation_alias="res")
    message: str = Field(default="", validation_alias="msg")
    status: str = ""
    installation_number: str = Field(default="", validation_alias="numinst")
    protom_response: str = Field(default="", validation_alias="protomResponse")
    protom_response_data: str = Field(default="", validation_alias="protomResponseDate")
    request_id: str = Field(default="", validation_alias="requestId")
    error: dict[str, Any] | None = None

    @field_validator("error", mode="before")
    @classmethod
    def _coerce_error(cls, v: Any) -> dict[str, Any] | None:
        """Coerce non-dict error values (e.g. empty string) to None."""
        if isinstance(v, dict):
            return v
        return None


class SStatus(BaseModel):
    """Current status of the alarm system."""

    model_config = ConfigDict(populate_by_name=True)

    status: str | None = None
    timestamp_update: str | None = Field(
        default=None, validation_alias="timestampUpdate"
    )
    wifi_connected: bool | None = Field(default=None, validation_alias="wifiConnected")


class OtpPhone(BaseModel):
    """OTP phone item for two-factor authentication."""

    id: int
    phone: str


class LockAutolock(BaseModel):
    """Lock auto-lock configuration."""

    active: bool | None = None
    timeout: str | int | None = None


class LockFeatures(BaseModel):
    """Lock feature configuration."""

    model_config = ConfigDict(populate_by_name=True)

    hold_back_latch_time: int = Field(default=0, validation_alias="holdBackLatchTime")
    calibration_type: int = Field(default=0, validation_alias="calibrationType")
    autolock: LockAutolock | None = None


class SmartLock(BaseModel):
    """Smart lock discovery response."""

    model_config = ConfigDict(populate_by_name=True)

    res: str | None = None
    location: str | None = None
    device_id: str = Field(default="", validation_alias="deviceId")
    reference_id: str = Field(default="", validation_alias="referenceId")
    zone_id: str = Field(default="", validation_alias="zoneId")
    serial_number: str = Field(default="", validation_alias="serialNumber")
    family: str = ""
    label: str = ""
    features: LockFeatures | None = None

    @model_validator(mode="before")
    @classmethod
    def _coerce_none_strings(cls, data: Any) -> Any:
        """Coerce None values to empty strings for required str fields."""
        if isinstance(data, dict):
            for key in (
                "deviceId",
                "device_id",
                "referenceId",
                "reference_id",
                "zoneId",
                "zone_id",
                "serialNumber",
                "serial_number",
                "family",
                "label",
            ):
                if key in data and data[key] is None:
                    data[key] = ""
        return data


class SmartLockMode(BaseModel):
    """Smart lock mode and status."""

    model_config = ConfigDict(populate_by_name=True)

    res: str | None = None
    lock_status: str = Field(default="", validation_alias="lockStatus")
    device_id: str = Field(default="", validation_alias="deviceId")
    status_timestamp: str = Field(default="", validation_alias="statusTimestamp")


class SmartLockModeStatus(BaseModel):
    """Smart lock mode change operation status."""

    model_config = ConfigDict(populate_by_name=True)

    request_id: str = Field(default="", validation_alias="requestId")
    message: str = Field(default="", validation_alias="msg")
    protom_response: str = Field(default="", validation_alias="protomResponse")
    status: str = ""


class CameraDevice(BaseModel):
    """A camera device from xSDeviceList (QR, YR, YP, or QP cameras)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    code: int = 0
    zone_id: str = Field(default="", validation_alias="zoneId")
    name: str = ""
    device_type: str = Field(default="", validation_alias="type")
    serial_number: str | None = Field(default=None, validation_alias="serialNumber")


class ThumbnailResponse(BaseModel):
    """Response from xSGetThumbnail."""

    model_config = ConfigDict(populate_by_name=True)

    id_signal: str | None = Field(default=None, validation_alias="idSignal")
    device_code: str | None = Field(default=None, validation_alias="deviceCode")
    device_alias: str | None = Field(default=None, validation_alias="deviceAlias")
    timestamp: str | None = None
    signal_type: str | None = Field(default=None, validation_alias="signalType")
    image: str | None = None


class Sentinel(BaseModel):
    """Sentinel environmental sensor status."""

    alias: str
    air_quality: str
    humidity: int
    temperature: int
    zone: str = ""


class AirQuality(BaseModel):
    """Air quality reading from xSAirQuality API."""

    value: int | None
    status_current: int = 0


class Attribute(BaseModel):
    """A single service attribute key/value pair."""

    name: str = ""
    value: str = ""
    active: bool = False


class Service(BaseModel):
    """A Securitas Direct service offering."""

    model_config = ConfigDict(populate_by_name=True)

    id: int = 0
    id_service: int = Field(default=0, validation_alias="idService")
    active: bool = False
    visible: bool = False
    bde: bool = False
    is_premium: bool = Field(default=False, validation_alias="isPremium")
    cod_oper: bool = Field(default=False, validation_alias="codOper")
    total_device: int = Field(default=0, validation_alias="totalDevice")
    request: str = ""
    multiple_req: bool = False
    num_devices_mr: int = 0
    secret_word: bool = False
    min_wrapper_version: Any = Field(default=None, validation_alias="minWrapperVersion")
    description: str = ""
    attributes: list[Attribute] = Field(default_factory=list)
    listdiy: list[Any] = Field(default_factory=list)
    listprompt: list[Any] = Field(default_factory=list)
    installation: Installation | None = None
