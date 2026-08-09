"""Panel peripheral inventory model."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PanelDevice(BaseModel):
    """One row of ``xSDeviceList`` — any peripheral paired with the panel.

    The panel returns its whole inventory here: cameras (QR/YR/YP/QP),
    magnetic contacts (MG), smart locks (DR), keypads (VV).  Camera discovery
    used to be the only consumer and narrowed the response to camera rows, so
    everything else was parsed and thrown away.  Keeping every row lets zone
    binary sensors reuse the same single fetch instead of repeating the call.

    ``zone_id`` is normalised at parse time (see ``_parse_device``) so it is
    never empty — the panel returns ``zoneId: null`` for some device types.
    """

    model_config = ConfigDict(populate_by_name=True)

    id: str = ""
    code: int = 0
    zone_id: str = Field(default="", validation_alias="zoneId")
    name: str = ""
    device_type: str = Field(default="", validation_alias="type")
    is_active: bool | None = Field(default=None, validation_alias="isActive")
    serial_number: str | None = Field(default=None, validation_alias="serialNumber")
