"""Auth-domain models."""

from __future__ import annotations

from pydantic import BaseModel


class OtpPhone(BaseModel):
    """OTP phone item for two-factor authentication."""

    id: int
    phone: str
