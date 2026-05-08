"""Camera domain: device list, capture, thumbnail, full image."""

from __future__ import annotations

import base64
import logging
from typing import Any

from ..exceptions import OperationTimeoutError
from ..graphql_queries import (
    DEVICE_LIST_QUERY,
    GET_PHOTO_IMAGES_QUERY,
    GET_THUMBNAIL_QUERY,
    REQUEST_IMAGES_MUTATION,
    REQUEST_IMAGES_STATUS_QUERY,
)
from ..models import CameraDevice, Installation, ThumbnailResponse
from ..responses import (
    DeviceListEnvelope,
    PhotoImagesEnvelope,
    RequestImagesEnvelope,
    RequestImagesStatusEnvelope,
    ThumbnailEnvelope,
)
from ._base import (
    CAMERA_DEVICE_TYPES,
    IMAGE_DEVICE_TYPE_MAP,
    IMAGE_MEDIA_TYPE,
    IMAGE_RESOLUTION,
    _ClientBase,
)

_LOGGER = logging.getLogger(__name__)


class _CameraMixin(_ClientBase):
    """Camera discovery and image fetch."""

    async def get_camera_devices(
        self, installation: Installation
    ) -> list[CameraDevice]:
        """Get list of camera devices (QR, YR, YP, QP) for an installation.

        Returns:
            A list of CameraDevice instances for active camera devices.
        """
        content = {
            "operationName": "xSDeviceList",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
            },
            "query": DEVICE_LIST_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "xSDeviceList",
            DeviceListEnvelope,
            installation=installation,
        )
        devices = envelope.data.xSDeviceList.devices or []
        # Annex installations can return the same physical camera twice in
        # xSDeviceList (once per panel-view: main + annex sub-panel). The two
        # rows share name + type + code; only the row index `id` differs.
        # Without dedup HA's entity registry rejects the second row as a
        # duplicate unique_id and silently drops the camera + capture button.
        # See https://github.com/guerrerotook/securitas-direct-new-api/issues/441.
        seen: set[tuple[str, str]] = set()
        result: list[CameraDevice] = []
        for d in devices:
            if d.get("type") not in CAMERA_DEVICE_TYPES or d.get("isActive") is False:
                continue
            dedup_key = (d.get("type") or "", str(d.get("code") or ""))
            if dedup_key in seen:
                continue
            seen.add(dedup_key)
            code = int(d["code"]) if str(d.get("code", "")).isdigit() else None
            result.append(
                CameraDevice(
                    id=d["id"],
                    code=code or 0,
                    zone_id=d["zoneId"]
                    or (f"{d['type']}{code:02d}" if code is not None else d["id"]),
                    name=d["name"],
                    device_type=d["type"],
                    serial_number=d.get("serialNumber"),
                )
            )
        return result

    async def capture_image(
        self,
        installation: Installation,
        device_code: int,
        device_type: str,
        zone_id: str,
        *,
        capture_timeout: float = 90.0,
    ) -> ThumbnailResponse:
        """Request a new image capture and poll until the thumbnail updates.

        Follows the flow: get baseline thumbnail -> submit capture request ->
        poll capture status until not processing -> poll thumbnail until
        idSignal changes from baseline.

        Args:
            installation: The installation containing the camera.
            device_code: Camera device code.
            device_type: Camera device type (e.g. "QR", "YR").
            zone_id: Camera zone ID.
            capture_timeout: Wall-clock timeout for the entire flow (default 30s).

        Returns:
            The new ThumbnailResponse (or baseline if timed out).
        """
        # Submit capture request
        submit_content = {
            "operationName": "RequestImages",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "devices": [device_code],
                "resolution": IMAGE_RESOLUTION,
                "mediaType": IMAGE_MEDIA_TYPE,
                "deviceType": IMAGE_DEVICE_TYPE_MAP.get(device_type, 106),
            },
            "query": REQUEST_IMAGES_MUTATION,
        }
        submit_envelope = await self._execute_graphql(
            submit_content,
            "RequestImages",
            RequestImagesEnvelope,
            installation=installation,
        )
        reference_id = submit_envelope.data.xSRequestImages.reference_id

        counter = 0

        async def _check() -> dict[str, Any]:
            nonlocal counter
            counter += 1
            status_content = {
                "operationName": "RequestImagesStatus",
                "variables": {
                    "numinst": installation.number,
                    "panel": installation.panel,
                    "devices": [device_code],
                    "referenceId": reference_id,
                    "counter": counter,
                },
                "query": REQUEST_IMAGES_STATUS_QUERY,
            }
            status_envelope = await self._execute_graphql(
                status_content,
                "RequestImagesStatus",
                RequestImagesStatusEnvelope,
                installation=installation,
            )
            inner = status_envelope.data.xSRequestImagesStatus
            msg = inner.msg or ""
            # _poll_operation continues while res=="WAIT"; remap the
            # "processing" message into WAIT so the same machinery applies.
            res = "WAIT" if "processing" in msg else inner.res
            return {"res": res, "msg": msg}

        try:
            await self._poll_operation(_check, timeout=capture_timeout)
        except OperationTimeoutError:
            _LOGGER.warning(
                "Image capture timed out after %.0f seconds for %s",
                capture_timeout,
                zone_id,
            )

        # Whether status finished or polling timed out, fetch the latest
        # thumbnail — the CDN may have caught up while we were polling.
        return await self.get_thumbnail(installation, device_type, zone_id)

    async def get_thumbnail(
        self,
        installation: Installation,
        device_type: str,
        zone_id: str,
    ) -> ThumbnailResponse:
        """Fetch the latest thumbnail image for a camera device.

        Args:
            installation: The installation to query.
            device_type: Camera device type string (e.g. "QR").
            zone_id: Camera zone ID.

        Returns:
            ThumbnailResponse with image data and metadata.
        """
        content = {
            "operationName": "mkGetThumbnail",
            "variables": {
                "numinst": installation.number,
                "panel": installation.panel,
                "device": device_type,
                "zoneId": zone_id,
            },
            "query": GET_THUMBNAIL_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "mkGetThumbnail",
            ThumbnailEnvelope,
            installation=installation,
        )
        return envelope.data.xSGetThumbnail

    async def get_full_image(
        self,
        installation: Installation,
        id_signal: str,
        signal_type: str,
    ) -> bytes | None:
        """Fetch full-resolution images for a completed capture.

        Selects the largest BINARY image and base64-decodes it.  Format
        validation (e.g. JPEG magic bytes) is left to callers — the camera
        path requires JPEG, but the activity-card path accepts any image.

        Args:
            installation: The installation to query.
            id_signal: The idSignal from a ThumbnailResponse.
            signal_type: The signalType from a ThumbnailResponse.

        Returns:
            Decoded image bytes, or None if no BINARY image was returned.
        """
        content = {
            "operationName": "mkGetPhotoImages",
            "variables": {
                "numinst": installation.number,
                "idSignal": id_signal,
                "signalType": signal_type,
                "panel": installation.panel,
            },
            "query": GET_PHOTO_IMAGES_QUERY,
        }
        envelope = await self._execute_graphql(
            content,
            "mkGetPhotoImages",
            PhotoImagesEnvelope,
            installation=installation,
        )
        devices = envelope.data.xSGetPhotoImages.devices or []
        if not devices:
            return None
        images = devices[0].get("images") or []
        binary_images = [
            img for img in images if img.get("type") == "BINARY" and img.get("image")
        ]
        if not binary_images:
            return None
        best = max(binary_images, key=lambda img: len(img["image"]))
        try:
            decoded = base64.b64decode(best["image"])
        except (ValueError, TypeError):
            return None
        if decoded:
            _LOGGER.debug(
                "get_full_image idSignal=%s: %d bytes, magic=%s",
                id_signal,
                len(decoded),
                decoded[:8].hex(),
            )
        return decoded or None
