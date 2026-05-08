"""Top-level GraphQL error response models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class GraphQLErrorData(BaseModel):
    """Structured data payload inside a GraphQL error."""

    model_config = ConfigDict(populate_by_name=True)

    reason: str | None = None
    status: int | None = None
    need_device_authorization: bool | None = Field(
        None, validation_alias="needDeviceAuthorization"
    )
    auth_otp_hash: str | None = Field(default=None, validation_alias="auth-otp-hash")
    auth_phones: list[dict[str, Any]] | None = Field(
        None, validation_alias="auth-phones"
    )


class GraphQLError(BaseModel):
    """A single GraphQL error object."""

    message: str
    data: GraphQLErrorData | None = None


class ErrorResponse(BaseModel):
    """Top-level GraphQL error response."""

    errors: list[GraphQLError]
