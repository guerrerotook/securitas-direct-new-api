"""Magnetic contact domain models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ..pydantic_utils import NullSafeBase


class ContactDevice(BaseModel):
    """A magnetic opening contact from xSDeviceList (MG or MR)."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    code: int = 0
    zone_id: str = Field(default="", validation_alias="zoneId")
    name: str = ""
    device_type: str = Field(default="", validation_alias="type")


class TimedValue(BaseModel):
    """A DSR value paired with the panel timestamp that produced it."""

    value: str | int | float | bool | None = None
    timestamp: str | None = None


class ContactState(NullSafeBase):
    """Latest DSR state for a magnetic contact."""

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    zone_id: str = Field(default="", validation_alias="zoneId")
    version: str | int | None = None
    battery_voltage: TimedValue | None = Field(
        default=None, validation_alias="batteryVoltage"
    )
    rssi_rf: TimedValue | None = Field(default=None, validation_alias="rssiRf")
    firmware_version: TimedValue | None = Field(
        default=None, validation_alias="firmwareVersion"
    )
    magnetic_state: TimedValue | None = Field(
        default=None, validation_alias="magneticState"
    )
    timestamp: str | None = None

    @property
    def is_open(self) -> bool | None:
        """Return the normalized magnetic state, or None when unknown."""
        if self.magnetic_state is None or self.magnetic_state.value is None:
            return None
        value = str(self.magnetic_state.value).strip().lower()
        if value == "open":
            return True
        if value == "closed":
            return False
        return None
