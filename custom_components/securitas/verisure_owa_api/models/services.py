"""Service-catalog domain models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .installation import Installation


class Attribute(BaseModel):
    """A single service attribute key/value pair."""

    name: str = ""
    value: str = ""
    active: bool = False


class Service(BaseModel):
    """A Verisure OWA service offering."""

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
