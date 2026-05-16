"""Camera GraphQL response envelopes."""

# pylint: disable=missing-class-docstring

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from ..models import ThumbnailResponse
from ..pydantic_utils import NullSafeBase as _NullSafeBase
from ._base import _ResMsgRef


class DeviceListEnvelope(BaseModel):
    """Response envelope for xSDeviceList."""

    class _Inner(_NullSafeBase):
        res: str = ""
        devices: list[dict[str, Any]] | None = None

    class Data(BaseModel):
        xSDeviceList: "DeviceListEnvelope._Inner"  # noqa: N815

    data: Data


class RequestImagesEnvelope(BaseModel):
    """Response envelope for xSRequestImages."""

    class Data(BaseModel):
        xSRequestImages: _ResMsgRef  # noqa: N815

    data: Data


class RequestImagesStatusEnvelope(BaseModel):
    """Response envelope for xSRequestImagesStatus."""

    class _Inner(_NullSafeBase):
        res: str = ""
        msg: str | None = None
        numinst: str | None = None
        status: str | None = None

    class Data(BaseModel):
        xSRequestImagesStatus: "RequestImagesStatusEnvelope._Inner"  # noqa: N815

    data: Data


class ThumbnailEnvelope(BaseModel):
    """Response envelope for xSGetThumbnail."""

    class Data(BaseModel):
        xSGetThumbnail: ThumbnailResponse  # noqa: N815

    data: Data


class PhotoImagesEnvelope(BaseModel):
    """Response envelope for xSGetPhotoImages."""

    class _Inner(_NullSafeBase):
        devices: list[dict[str, Any]] | None = None

    class Data(BaseModel):
        xSGetPhotoImages: "PhotoImagesEnvelope._Inner"  # noqa: N815

    data: Data
