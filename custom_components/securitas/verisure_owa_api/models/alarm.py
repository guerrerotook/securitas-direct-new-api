"""Alarm-domain models: state axes, proto codes, command strings, and
operation/status envelopes."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..exceptions import UnexpectedStateError
from ..pydantic_utils import NullSafeBase as _NullSafeBase


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


class AnnexMode(StrEnum):
    """Annex alarm mode."""

    OFF = "off"
    ON = "on"


class ProtoCode(StrEnum):
    """Protocol response codes from the Verisure OWA API."""

    DISARMED = "D"
    PERIMETER_ONLY = "E"
    PARTIAL_DAY = "P"
    PARTIAL_NIGHT = "Q"
    PARTIAL_DAY_PERIMETER = "B"
    PARTIAL_NIGHT_PERIMETER = "C"
    TOTAL = "T"
    TOTAL_PERIMETER = "A"
    # Annex variants (interior + annex, no peri). The 8 perimeter+annex
    # combinations are not yet known and fall through to Custom Override.
    ANNEX_ONLY = "X"
    PARTIAL_DAY_ANNEX = "R"
    PARTIAL_NIGHT_ANNEX = "S"
    TOTAL_ANNEX = "O"


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


class AlarmState(BaseModel):
    """Three-axis alarm state: interior + perimeter + annex."""

    model_config = ConfigDict(frozen=True)

    interior: InteriorMode
    perimeter: PerimeterMode
    annex: AnnexMode = AnnexMode.OFF

    def __hash__(self) -> int:
        return hash((self.interior, self.perimeter, self.annex))

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, AlarmState):
            return NotImplemented
        return (
            self.interior == other.interior
            and self.perimeter == other.perimeter
            and self.annex == other.annex
        )


def parse_proto_code(code: str) -> ProtoCode:
    """Parse a raw protocol code string into a ProtoCode enum.

    Raises UnexpectedStateError for unknown codes.
    """
    try:
        return ProtoCode(code)
    except ValueError as exc:
        raise UnexpectedStateError(code) from exc


def is_proto_letter(value: object) -> bool:
    """Return True iff value has the proto-code wire shape (single uppercase letter).

    Looser than ``ProtoCode(value)`` — admits well-formed codes we don't yet
    model so callers can distinguish "alarm in a state we don't recognise"
    (refuse cleanly) from "API noise like 'ARMED_TOTAL'" (drop on the floor).
    """
    return isinstance(value, str) and len(value) == 1 and "A" <= value <= "Z"


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
    ProtoCode.ANNEX_ONLY: AlarmState(
        interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF, annex=AnnexMode.ON
    ),
    ProtoCode.PARTIAL_DAY_ANNEX: AlarmState(
        interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF, annex=AnnexMode.ON
    ),
    ProtoCode.PARTIAL_NIGHT_ANNEX: AlarmState(
        interior=InteriorMode.NIGHT, perimeter=PerimeterMode.OFF, annex=AnnexMode.ON
    ),
    ProtoCode.TOTAL_ANNEX: AlarmState(
        interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF, annex=AnnexMode.ON
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


class OperationStatus(_NullSafeBase):
    """Result of an alarm or lock operation (arm, disarm, check)."""

    model_config = ConfigDict(populate_by_name=True)

    operation_status: str = Field(default="", validation_alias="res")
    message: str = Field(default="", validation_alias="msg")
    status: str = ""
    installation_number: str = Field(default="", validation_alias="numinst")
    protom_response: str = Field(default="", validation_alias="protomResponse")
    protom_response_date: str = Field(default="", validation_alias="protomResponseDate")
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
    exceptions: list[dict[str, Any]] | None = None
