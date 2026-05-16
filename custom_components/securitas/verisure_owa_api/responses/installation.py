"""Installation-list and service-catalog response envelopes."""

# pylint: disable=missing-class-docstring

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ..models import Installation
from ..pydantic_utils import NullSafeBase as _NullSafeBase


class InstallationListEnvelope(BaseModel):
    """Response envelope for xSInstallations."""

    class _Inner(_NullSafeBase):
        installations: list[Installation]

    class Data(BaseModel):
        xSInstallations: "InstallationListEnvelope._Inner"  # noqa: N815

    data: Data


class ServicesEnvelope(BaseModel):
    """Response envelope for xSSrv."""

    class _Installation(BaseModel):
        model_config = ConfigDict(populate_by_name=True)

        numinst: str | None = None
        capabilities: str | None = None
        services: list[dict[str, Any]] = Field(default_factory=list)
        config_repo_user: dict[str, Any] | None = Field(
            None, validation_alias="configRepoUser"
        )

    class _Inner(_NullSafeBase):
        res: str = ""
        msg: str | None = None
        installation: "ServicesEnvelope._Installation | None" = None

    class Data(BaseModel):
        xSSrv: "ServicesEnvelope._Inner"  # noqa: N815

    data: Data
