"""Camera domain: device list, capture, thumbnail, full image."""

from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

from aiohttp import ClientConnectorError

from ..exceptions import APIConnectionError, OperationTimeoutError, VerisureOwaError
from ..graphql_queries import (
    GET_PHOTO_IMAGES_QUERY,
    GET_THUMBNAIL_QUERY,
    REQUEST_IMAGES_MUTATION,
    REQUEST_IMAGES_STATUS_QUERY,
)
from ..models import CameraDevice, Installation, ThumbnailResponse
from ..responses import (
    PhotoImagesEnvelope,
    RequestImagesEnvelope,
    RequestImagesStatusEnvelope,
    ThumbnailEnvelope,
)
from ._device import CAMERA_DEVICE_TYPES, _DeviceMixin, filter_camera_devices

_LOGGER = logging.getLogger(__name__)

__all__ = ["CAMERA_DEVICE_TYPES", "_CameraMixin"]

IMAGE_RESOLUTION = 0
IMAGE_MEDIA_TYPE = 1
IMAGE_DEVICE_TYPE_MAP: dict[str, int] = {"QR": 106, "YR": 106, "YP": 103, "QP": 107}


class _CameraMixin(_DeviceMixin):
    """Camera discovery and image fetch."""

    async def get_camera_devices(
        self, installation: Installation
    ) -> list[CameraDevice]:
        """Get list of camera devices (QR, YR, YP, QP) for an installation.

        A thin filter over the whole-inventory ``get_devices`` fetch so camera
        and zone discovery share one xSDeviceList round-trip.

        Returns:
            A list of CameraDevice instances for active camera devices.
        """
        return filter_camera_devices(await self.get_devices(installation))

    async def capture_image(
        self,
        installation: Installation,
        device_code: int,
        device_type: str,
        zone_id: str,
        *,
        capture_timeout: float = 90.0,
        status_poll_delay: float = 5.0,
        wait_for_fresh: bool = False,
        freshness_timeout: float = 30.0,
        freshness_poll_interval: float = 5.0,
    ) -> ThumbnailResponse:
        """Request a new image capture, then fetch the resulting thumbnail.

        Submits a RequestImages mutation and polls RequestImagesStatus until
        the panel reports a non-processing result (or capture_timeout
        elapses), then fetches the latest thumbnail.

        The "photo-request.success" status only means the alarm-manager
        accepted the capture request — the CDN may serve the previous frame
        for tens of seconds after.  Comparing against a cached timestamp
        isn't safe: the CDN may have a newer-but-still-stale frame whose
        timestamp differs from the cache but still predates our request.
        When `wait_for_fresh=True`, this method pre-fetches a thumbnail
        immediately before submitting the capture so the baseline is "what
        the CDN was serving at click time", then polls until something
        strictly newer arrives.

        Timestamps are compared lexicographically as strings, which is
        equivalent to chronological order for the server's ISO-8601-style
        ``YYYY-MM-DD HH:MM:SS`` format — no timezone math needed because
        both sides come from the same server clock.

        Args:
            installation: The installation containing the camera.
            device_code: Camera device code.
            device_type: Camera device type (e.g. "QR", "YR").
            zone_id: Camera zone ID.
            capture_timeout: Wall-clock timeout for the status poll
                (default 90s).
            status_poll_delay: Delay between xSRequestImagesStatus polls
                (default 5s).  Image captures take 30-90s server-side, so
                the integration-wide poll_delay (typically 2s, tuned for
                arm/disarm) over-polls and risks rate-limiting.
            wait_for_fresh: When True, pre-fetch a baseline thumbnail and
                poll until a strictly newer one is published.  When False,
                returns the first post-status fetch (legacy behaviour).
            freshness_timeout: Wall-clock budget for waiting for the CDN
                to publish a fresh frame after status reports success.
            freshness_poll_interval: Delay between freshness retries
                (default 5s).

        Returns:
            The latest ThumbnailResponse — the freshly captured frame
            when the CDN catches up in time, otherwise the most recent
            (possibly stale) one.
        """
        baseline_timestamp: str | None = None
        if wait_for_fresh:
            try:
                baseline_thumb = await self.get_thumbnail(
                    installation, device_type, zone_id
                )
                baseline_timestamp = baseline_thumb.timestamp
            except VerisureOwaError as err:
                _LOGGER.warning(
                    "Pre-capture baseline fetch failed for %s; "
                    "will accept the first published frame as fresh: %s",
                    zone_id,
                    err,
                )
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
            await self._poll_operation(
                _check, timeout=capture_timeout, delay=status_poll_delay
            )
        except OperationTimeoutError:
            _LOGGER.warning(
                "Image capture timed out after %.0f seconds for %s",
                capture_timeout,
                zone_id,
            )

        # Whether status finished or polling timed out, fetch the latest
        # thumbnail — the CDN may have caught up while we were polling.
        thumbnail = await self.get_thumbnail(installation, device_type, zone_id)
        if not wait_for_fresh:
            return thumbnail

        # Freshness poll: retry until timestamp is strictly newer than the
        # pre-capture baseline (lexicographic string compare on the server's
        # ISO format).  Null timestamps are treated as stale.  A null
        # baseline (the CDN stops serving thumbnails for cameras idle for
        # days, and the pre-capture fetch may fail outright) must NOT skip
        # the wait — compare against "" so any real timestamp counts as
        # strictly newer and we keep polling through the empty responses.
        baseline = baseline_timestamp or ""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + freshness_timeout
        while thumbnail.timestamp is None or thumbnail.timestamp <= baseline:
            remaining = deadline - loop.time()
            if remaining <= 0:
                _LOGGER.warning(
                    "Fresh thumbnail for %s not available after %.0fs; "
                    "returning stale (timestamp=%s, baseline=%s)",
                    zone_id,
                    freshness_timeout,
                    thumbnail.timestamp,
                    baseline_timestamp,
                )
                break
            await asyncio.sleep(min(freshness_poll_interval, remaining))
            try:
                thumbnail = await self.get_thumbnail(installation, device_type, zone_id)
            except (TimeoutError, ClientConnectorError, APIConnectionError) as err:
                # A transient network/CDN blip on one poll must not drop the
                # whole capture — retry until the deadline, same as the status
                # poll (_poll_operation).  `thumbnail` keeps its previous value
                # so the loop still sees it as stale and re-polls.
                _LOGGER.warning(
                    "Transient error fetching thumbnail during freshness "
                    "wait for %s, retrying: %s",
                    zone_id,
                    err,
                )
            except VerisureOwaError as err:
                if err.http_status != 409:
                    raise
                _LOGGER.warning(
                    "Transient error (409) fetching thumbnail during "
                    "freshness wait for %s, retrying: %s",
                    zone_id,
                    err.log_detail(),
                )
        return thumbnail

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
