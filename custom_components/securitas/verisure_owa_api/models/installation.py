"""Installation model — a Verisure OWA customer site."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from ..pydantic_utils import NullSafeBase as _NullSafeBase


class Installation(_NullSafeBase):
    """A Verisure OWA installation (customer site)."""

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
