"""Pydantic domain models for the Securitas Direct API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from .exceptions import UnexpectedStateError
from .pydantic_utils import NullSafeBase as _NullSafeBase


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


class Installation(_NullSafeBase):
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


class OperationStatus(_NullSafeBase):
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


class SmartLock(_NullSafeBase):
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


class SmartLockMode(_NullSafeBase):
    """Smart lock mode and status."""

    model_config = ConfigDict(populate_by_name=True)

    res: str | None = None
    lock_status: str = Field(default="", validation_alias="lockStatus")
    device_id: str = Field(default="", validation_alias="deviceId")
    status_timestamp: str = Field(default="", validation_alias="statusTimestamp")


class SmartLockModeStatus(_NullSafeBase):
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


class ActivityException(_NullSafeBase):
    """Sensor exception attached to an armed-with-exceptions / arming-failed event.

    Reported when the panel arms despite a zone being unable to fully participate
    (door open, battery flat, etc.) or when the panel rejects the arm command
    because of those exceptions.
    """

    model_config = ConfigDict(populate_by_name=True)

    status: str = ""
    device_type: str = Field(default="", validation_alias="deviceType")
    alias: str = ""

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_key(self) -> str:
        """Translation key for the exception's status code.

        Mapping is conservative — only the values confirmed in real installations
        are translated; unmapped codes fall through to "unknown" rather than
        guessing.
        """
        if self.status == "0":
            return "open"
        if self.status == "2":
            return "battery_low"
        return "unknown"


class ActivityCategory(StrEnum):
    """High-level grouping of xSActV2 event type codes for UI / i18n.

    Type codes from the panel are granular (Armed-perimeter vs Armed-night vs
    Activation-indoor+outdoor all map to ARMED).  Categories give cards a
    stable key to localise / icon against without enumerating every code.
    """

    ARMED = "armed"
    ARMED_WITH_EXCEPTIONS = "armed_with_exceptions"
    ARMING_FAILED = "arming_failed"
    DISARMED = "disarmed"
    ALARM = "alarm"
    ALARM_RESOLVED = "alarm_resolved"
    TAMPERING = "tampering"
    SABOTAGE = "sabotage"
    IMAGE_REQUEST = "image_request"
    POWER_CUT = "power_cut"
    POWER_RESTORED = "power_restored"
    STATUS_CHECK = "status_check"
    UNKNOWN = "unknown"


# Numeric type → category map. Codes seen in real fixture data.
#
# Note on the 800-series: in Verisure parlance "connessione/connection" means
# the alarm being *armed* (not network connectivity).  802/821/823/824 are
# panel-emitted arm-state signals; 822 is the corresponding disarm signal.
_ACTIVITY_TYPE_TO_CATEGORY: dict[int, ActivityCategory] = {
    # Armed — user-initiated arm commands and the panel-emitted arm signals
    2: ActivityCategory.ARMED,
    37: ActivityCategory.ARMED,
    40: ActivityCategory.ARMED,
    46: ActivityCategory.ARMED,
    701: ActivityCategory.ARMED,
    721: ActivityCategory.ARMED,
    802: ActivityCategory.ARMED,  # "Connection Main partial"
    821: ActivityCategory.ARMED,  # "Connection Exterior"
    823: ActivityCategory.ARMED,  # "Connection Exterior + Main total"
    824: ActivityCategory.ARMED,  # "Connection Exterior + Main partial"
    # Force-armed with sensor exceptions bypassed (NOT an alarm — the panel
    # armed despite open zones or dead batteries; bypassed zones in `exceptions[]`)
    850: ActivityCategory.ARMED_WITH_EXCEPTIONS,
    # Arm attempts the panel rejected because of exceptions.  The 5xxx range
    # mirrors the corresponding 8xx connection-success codes (5802 → 802 Main
    # partial; 5824 → 824 Exterior + Main partial).  Add more codes here as
    # they're observed.
    5802: ActivityCategory.ARMING_FAILED,
    5824: ActivityCategory.ARMING_FAILED,
    # Disarmed — user-initiated disarm commands and the panel-emitted disarm signal
    1: ActivityCategory.DISARMED,
    32: ActivityCategory.DISARMED,
    107: ActivityCategory.DISARMED,
    700: ActivityCategory.DISARMED,
    720: ActivityCategory.DISARMED,
    822: ActivityCategory.DISARMED,  # "Disconnection Exterior + Main"
    # Alarms
    13: ActivityCategory.ALARM,
    24: ActivityCategory.TAMPERING,
    241: ActivityCategory.SABOTAGE,
    331: ActivityCategory.ALARM_RESOLVED,
    # Other
    16: ActivityCategory.IMAGE_REQUEST,
    25: ActivityCategory.POWER_CUT,
    26: ActivityCategory.POWER_RESTORED,
    27: ActivityCategory.STATUS_CHECK,
}


class ActivityEvent(_NullSafeBase):
    """A single entry from the alarm panel's xSActV2 timeline."""

    model_config = ConfigDict(populate_by_name=True)

    alias: str = ""
    type: int = 0
    device: str | None = None
    source: str | None = None
    id_signal: str = Field(default="", validation_alias="idSignal")
    scheduler_type: str | None = Field(default=None, validation_alias="schedulerType")
    verisure_user: str | None = Field(default=None, validation_alias="myVerisureUser")
    time: str = ""
    img: int = 0
    incidence_id: str | None = Field(default=None, validation_alias="incidenceId")
    signal_type: int = Field(default=0, validation_alias="signalType")
    interface: str | None = None
    device_name: str | None = Field(default=None, validation_alias="deviceName")
    keyname: str | None = None
    tag_id: str | None = Field(default=None, validation_alias="tagId")
    user_auth: str | None = Field(default=None, validation_alias="userAuth")
    exceptions: list[ActivityException] | None = None
    media_platform: dict[str, Any] | None = Field(
        default=None, validation_alias="mediaPlatform"
    )
    # True when the event was synthesized by this integration (e.g. an
    # arm/disarm injected at the moment HA issued the command).  Polled
    # entries from the panel default to False.
    injected: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def category(self) -> ActivityCategory:
        """High-level UI grouping derived from the numeric type code."""
        return _ACTIVITY_TYPE_TO_CATEGORY.get(self.type, ActivityCategory.UNKNOWN)


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
