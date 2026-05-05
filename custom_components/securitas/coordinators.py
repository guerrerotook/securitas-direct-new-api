"""DataUpdateCoordinators for Securitas Direct HA integration.

Four coordinators replace per-entity independent polling:
- AlarmCoordinator: alarm status polling
- SentinelCoordinator: environmental sensor data
- LockCoordinator: smart lock mode status
- CameraCoordinator: camera thumbnails
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api_queue import ApiQueue
from .securitas_direct_new_api.capabilities import detect_annex, detect_peri
from .securitas_direct_new_api.client import SecuritasClient
from .securitas_direct_new_api.command_resolver import (
    PROTO_TO_ALARM_STATE,
    AlarmState,
    InteriorMode,
    PerimeterMode,
)
from .securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
    SessionExpiredError,
    WAFBlockedError,
)
from .securitas_direct_new_api.models import (
    AirQuality,
    CameraDevice,
    Installation,
    Sentinel,
    Service,
    SmartLockMode,
    SStatus,
    ThumbnailResponse,
)

_LOGGER = logging.getLogger(__name__)

_DEFAULT_SENTINEL_INTERVAL = timedelta(minutes=30)
_DEFAULT_CAMERA_INTERVAL = timedelta(minutes=30)


# ── Data models ──────────────────────────────────────────────────────────────


@dataclass
class AlarmStatusData:
    """Data returned by AlarmCoordinator."""

    status: SStatus
    protom_response: str = ""


@dataclass
class SentinelData:
    """Data returned by SentinelCoordinator."""

    sentinel: Sentinel | None = None
    air_quality: AirQuality | None = None


@dataclass
class LockData:
    """Data returned by LockCoordinator."""

    modes: list[SmartLockMode] = field(default_factory=list)


@dataclass
class CameraData:
    """Data returned by CameraCoordinator."""

    thumbnails: dict[str, ThumbnailResponse] = field(default_factory=dict)
    full_images: dict[str, bytes] = field(default_factory=dict)


# ── Error handling ───────────────────────────────────────────────────────────


async def _handle_session_expired(client: SecuritasClient) -> None:
    """Attempt to re-login after a SessionExpiredError.

    Raises ConfigEntryAuthFailed if re-login fails.
    """
    try:
        await client.login()
    except SecuritasDirectError as err:
        raise ConfigEntryAuthFailed(f"Re-authentication failed: {err}") from err


# ── AlarmCoordinator ─────────────────────────────────────────────────────────


class AlarmCoordinator(DataUpdateCoordinator[AlarmStatusData]):
    """Coordinator for alarm status polling."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SecuritasClient,
        queue: ApiQueue,
        installation: Installation,
        *,
        update_interval: timedelta,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="securitas_alarm",
            update_interval=update_interval,
        )
        self._client = client
        self._queue = queue
        self._installation = installation
        # Capability-detection state — populated lazily on first refresh
        self._capabilities: frozenset[str] = frozenset()
        self._has_peri: bool = False
        self._has_annex: bool = False
        self._capabilities_populated: bool = False

    @property
    def has_peri(self) -> bool:
        """Return True if perimeter mode is supported."""
        return self._has_peri

    @property
    def has_annex(self) -> bool:
        """Return True if annex mode is supported."""
        return self._has_annex

    @property
    def capabilities(self) -> frozenset[str]:
        """Return the supported command capability set."""
        return self._capabilities

    @property
    def alarm_state(self) -> AlarmState:
        """Return the current AlarmState derived from coordinator data.

        Used by sub-panels to read the joint state for axis-preserving
        transitions. Falls back to all-OFF if no data is available yet.
        """
        _default = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        if self.data is None:
            return _default
        proto_code = self.data.status.status if self.data.status else None
        if proto_code is None:
            return _default
        return PROTO_TO_ALARM_STATE.get(proto_code, _default)

    def populate_capabilities_from_data(
        self,
        services: list,
        capabilities: frozenset[str],
    ) -> None:
        """Populate capability fields from already-fetched data.

        Called from async_setup_entry where services and capabilities are
        already in hand, avoiding a redundant API call during first refresh.
        Marks the coordinator as populated so _populate_capabilities is a no-op.
        """
        if self._capabilities_populated:
            return
        self._capabilities = capabilities
        self._has_peri = detect_peri(self._installation, services, capabilities)
        self._has_annex = detect_annex(capabilities)
        self._capabilities_populated = True
        self._log_capability_detection()

    async def _populate_capabilities(self) -> None:
        """Detect peri/annex via API.  Runs once per coordinator lifetime.

        This is a fallback path for cases where populate_capabilities_from_data
        was not called (e.g. unit tests that construct the coordinator directly).
        In normal operation, async_setup_entry calls populate_capabilities_from_data
        before any refresh, so this method is a no-op.
        """
        if self._capabilities_populated:
            return
        try:
            services = await self._client.get_services(self._installation)
        except SecuritasDirectError:
            services = []
        self._capabilities = self._client.get_supported_commands(
            self._installation.number
        )
        self._has_peri = detect_peri(self._installation, services, self._capabilities)
        self._has_annex = detect_annex(self._capabilities)
        self._capabilities_populated = True
        self._log_capability_detection()

    def _log_capability_detection(self) -> None:
        _LOGGER.debug(
            "capability detection for %s: has_peri=%s has_annex=%s caps=%s",
            self._installation.number,
            self._has_peri,
            self._has_annex,
            sorted(self._capabilities),
        )

    async def _async_update_data(self) -> AlarmStatusData:
        """Fetch alarm status via the API queue."""
        await self._populate_capabilities()
        try:
            status = await self._queue.submit(
                self._client.get_general_status,
                self._installation,
                priority=ApiQueue.BACKGROUND,
            )
            return AlarmStatusData(
                status=status,
                protom_response=self._client.protom_response,
            )
        except SessionExpiredError:
            await _handle_session_expired(self._client)
            # Retry once after re-login
            try:
                status = await self._queue.submit(
                    self._client.get_general_status,
                    self._installation,
                    priority=ApiQueue.BACKGROUND,
                )
                return AlarmStatusData(
                    status=status,
                    protom_response=self._client.protom_response,
                )
            except SecuritasDirectError as err:
                raise UpdateFailed(f"Alarm status update failed: {err}") from err
        except WAFBlockedError as err:
            raise UpdateFailed(f"WAF blocked alarm status request: {err}") from err
        except SecuritasDirectError as err:
            raise UpdateFailed(f"Alarm status update failed: {err}") from err


# ── SentinelCoordinator ──────────────────────────────────────────────────────


class SentinelCoordinator(DataUpdateCoordinator[SentinelData]):
    """Coordinator for sentinel environmental sensor data."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SecuritasClient,
        queue: ApiQueue,
        installation: Installation,
        *,
        service: Service,
        zone: str,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="securitas_sentinel",
            update_interval=_DEFAULT_SENTINEL_INTERVAL,
        )
        self._client = client
        self._queue = queue
        self.installation = installation
        self.service = service
        self._zone = zone

    async def _fetch_data(self) -> SentinelData:
        """Fetch sentinel and air quality data sequentially."""
        sentinel = await self._queue.submit(
            self._client.get_sentinel_data,
            self.installation,
            self.service,
            priority=ApiQueue.BACKGROUND,
        )
        air_quality = await self._queue.submit(
            self._client.get_air_quality_data,
            self.installation,
            self._zone,
            priority=ApiQueue.BACKGROUND,
        )
        return SentinelData(sentinel=sentinel, air_quality=air_quality)

    async def _async_update_data(self) -> SentinelData:
        """Fetch sentinel data via the API queue."""
        try:
            return await self._fetch_data()
        except SessionExpiredError:
            await _handle_session_expired(self._client)
            try:
                return await self._fetch_data()
            except SecuritasDirectError as err:
                raise UpdateFailed(f"Sentinel update failed: {err}") from err
        except WAFBlockedError as err:
            raise UpdateFailed(f"WAF blocked sentinel request: {err}") from err
        except SecuritasDirectError as err:
            raise UpdateFailed(f"Sentinel update failed: {err}") from err


# ── LockCoordinator ──────────────────────────────────────────────────────────


class LockCoordinator(DataUpdateCoordinator[LockData]):
    """Coordinator for smart lock mode status."""

    def __init__(
        self,
        hass: HomeAssistant,
        client: SecuritasClient,
        queue: ApiQueue,
        installation: Installation,
        *,
        update_interval: timedelta,
        config_entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="securitas_lock",
            update_interval=update_interval,
        )
        self._client = client
        self._queue = queue
        self._installation = installation

    async def _async_update_data(self) -> LockData:
        """Fetch lock modes via the API queue."""
        try:
            modes = await self._queue.submit(
                self._client.get_lock_modes,
                self._installation,
                priority=ApiQueue.BACKGROUND,
            )
            return LockData(modes=modes)
        except SessionExpiredError:
            await _handle_session_expired(self._client)
            try:
                modes = await self._queue.submit(
                    self._client.get_lock_modes,
                    self._installation,
                    priority=ApiQueue.BACKGROUND,
                )
                return LockData(modes=modes)
            except SecuritasDirectError as err:
                raise UpdateFailed(f"Lock update failed: {err}") from err
        except WAFBlockedError as err:
            raise UpdateFailed(f"WAF blocked lock request: {err}") from err
        except SecuritasDirectError as err:
            raise UpdateFailed(f"Lock update failed: {err}") from err


# ── CameraCoordinator ────────────────────────────────────────────────────────


class CameraCoordinator(DataUpdateCoordinator[CameraData]):
    """Coordinator for camera thumbnails.

    Individual camera failures are logged but don't fail the whole update.
    Previous thumbnails and full images are preserved across refreshes.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        client: SecuritasClient,
        queue: ApiQueue,
        installation: Installation,
        *,
        cameras: list[CameraDevice],
        config_entry: ConfigEntry | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name="securitas_camera",
            update_interval=_DEFAULT_CAMERA_INTERVAL,
        )
        self._client = client
        self._queue = queue
        self._installation = installation
        self._cameras = cameras

    async def _fetch_thumbnails(
        self, previous: CameraData | None
    ) -> dict[str, ThumbnailResponse]:
        """Fetch thumbnails for all cameras, preserving previous on failure.

        SessionExpiredError and WAFBlockedError are re-raised so the caller
        can handle auth/WAF issues at the coordinator level.  Other
        SecuritasDirectError instances are treated as individual camera
        failures — logged and skipped.
        """
        thumbnails: dict[str, ThumbnailResponse] = {}
        for camera in self._cameras:
            try:
                thumb = await self._queue.submit(
                    self._client.get_thumbnail,
                    self._installation,
                    camera.device_type,
                    camera.zone_id,
                    priority=ApiQueue.BACKGROUND,
                )
                thumbnails[camera.zone_id] = thumb
            except (SessionExpiredError, WAFBlockedError):
                raise
            except SecuritasDirectError as err:
                _LOGGER.warning(
                    "Failed to fetch thumbnail for camera %s (zone %s): %s",
                    camera.name,
                    camera.zone_id,
                    err,
                )
                # Preserve previous thumbnail if available
                if previous and camera.zone_id in previous.thumbnails:
                    thumbnails[camera.zone_id] = previous.thumbnails[camera.zone_id]
        return thumbnails

    @staticmethod
    def _thumbnail_is_recent(
        thumbnail: ThumbnailResponse, max_age_hours: int = 1
    ) -> bool:
        """Check if a thumbnail is recent enough to have a full image available."""
        if not thumbnail.timestamp:
            return False
        try:
            # Timestamp format: "2026-04-09 13:08:16"
            thumb_time = datetime.strptime(
                thumbnail.timestamp, "%Y-%m-%d %H:%M:%S"
            ).replace(tzinfo=timezone.utc)
            age = datetime.now(tz=timezone.utc) - thumb_time
            return age < timedelta(hours=max_age_hours)
        except (ValueError, TypeError):
            return False

    async def _fetch_full_image(
        self,
        thumbnail: ThumbnailResponse,
        zone_id: str,
    ) -> bytes | None:
        """Fetch full-resolution image for a thumbnail, return bytes or None."""
        if not thumbnail.id_signal or not thumbnail.signal_type:
            return None
        if not self._thumbnail_is_recent(thumbnail):
            _LOGGER.debug(
                "Skipping full image for zone %s — thumbnail too old (%s)",
                zone_id,
                thumbnail.timestamp,
            )
            return None
        try:
            full_bytes = await self._queue.submit(
                self._client.get_full_image,
                self._installation,
                thumbnail.id_signal,
                thumbnail.signal_type,
                priority=ApiQueue.BACKGROUND,
            )
        except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
            _LOGGER.warning(
                "Failed to fetch full image for camera zone %s",
                zone_id,
                exc_info=True,
            )
            return None
        if not full_bytes or not full_bytes.startswith(b"\xff\xd8"):
            _LOGGER.debug(
                "Full image for zone %s is not valid JPEG (%d bytes)",
                zone_id,
                len(full_bytes) if full_bytes else 0,
            )
            return None
        return full_bytes

    async def _async_update_data(self) -> CameraData:
        """Fetch camera thumbnails and full images for any that changed."""
        previous = self.data
        try:
            thumbnails = await self._fetch_thumbnails(previous)
        except SessionExpiredError:
            await _handle_session_expired(self._client)
            try:
                thumbnails = await self._fetch_thumbnails(previous)
            except WAFBlockedError as err:
                raise UpdateFailed(f"WAF blocked camera request: {err}") from err
            except SecuritasDirectError as err:
                raise UpdateFailed(f"Camera update failed: {err}") from err
        except WAFBlockedError as err:
            raise UpdateFailed(f"WAF blocked camera request: {err}") from err

        # Carry forward previous full images
        full_images: dict[str, bytes] = {}
        if previous:
            full_images = dict(previous.full_images)

        # Fetch full images for thumbnails whose id_signal changed
        prev_thumbnails = previous.thumbnails if previous else {}
        for zone_id, thumb in thumbnails.items():
            prev_thumb = prev_thumbnails.get(zone_id)
            prev_signal = prev_thumb.id_signal if prev_thumb else None
            if thumb.id_signal and thumb.id_signal != prev_signal:
                _LOGGER.debug(
                    "Thumbnail changed for zone %s (id_signal %s -> %s), "
                    "fetching full image",
                    zone_id,
                    prev_signal,
                    thumb.id_signal,
                )
                full_bytes = await self._fetch_full_image(thumb, zone_id)
                if full_bytes:
                    full_images[zone_id] = full_bytes

        return CameraData(thumbnails=thumbnails, full_images=full_images)
