"""VerisureHub and VerisureDevice classes for Verisure OWA integration."""

import asyncio
import base64
import logging
from functools import partial
from typing import Any

from aiohttp import ClientSession
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_DEVICE_ID,
    CONF_PASSWORD,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_send

from .api_queue import ApiQueue
from .const import (
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    CONF_OPERATION_POLL_TIMEOUT,
    CONF_REFRESH_TOKEN,
    DEFAULT_OPERATION_POLL_TIMEOUT,
    DOMAIN,
    SIGNAL_CAMERA_STATE,
)
from .log_filter import SensitiveDataFilter
from .notification_translations import get_notification_strings
from .verisure_owa_api import (
    ApiDomains,
    AuthenticationError,
    CameraDevice,
    Installation,
    OperationStatus,
    OtpPhone,
    Service,
    SmartLock,
    SmartLockMode,
    ThumbnailResponse,
    VerisureOwaError,
)
from .verisure_owa_api.client import VerisureOwaClient
from .verisure_owa_api.http_transport import HttpTransport

_LOGGER = logging.getLogger(__name__)


async def _async_notify(
    hass: HomeAssistant,
    notification_id: str,
    translation_key: str,
    placeholders: dict[str, str] | None = None,
) -> None:
    """Send a translated persistent notification."""
    entry = get_notification_strings(hass, translation_key)
    title = entry.get("title", "")
    message = entry.get("message", "")
    if placeholders:
        for key, value in placeholders.items():
            token = "{" + key + "}"
            title = title.replace(token, str(value))
            message = message.replace(token, str(value))
    await hass.services.async_call(
        domain="persistent_notification",
        service="create",
        service_data={
            "title": title,
            "message": message,
            "notification_id": f"{DOMAIN}.{notification_id}",
        },
    )


def _notify(
    hass: HomeAssistant,
    notification_id: str,
    translation_key: str,
    placeholders: dict[str, str] | None = None,
) -> None:
    """Schedule a translated persistent notification (sync-callable)."""
    hass.async_create_task(
        _async_notify(hass, notification_id, translation_key, placeholders)
    )


class VerisureDevice:
    """Verisure OWA device instance."""

    def __init__(self, installation: Installation) -> None:
        """Construct a device wrapper."""
        self.installation = installation
        self.name = installation.alias

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    @property
    def device_id(self) -> str:
        """Return device ID."""
        return self.installation.number

    @property
    def address(self) -> str:
        """Return the address of the instalation."""
        return self.installation.address

    @property
    def city(self) -> str:
        """Return the city of the installation."""
        return self.installation.city

    @property
    def postal_code(self) -> str:
        """Return the postal code of the installation."""
        return self.installation.postal_code

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"v4_securitas_direct.{self.installation.number}")},
            manufacturer="Verisure",
            model=self.installation.panel,
            hw_version=self.installation.type,
            name=self.name,
        )


class VerisureHub:
    """A Verisure OWA hub wrapper class."""

    def __init__(
        self,
        domain_config: dict[str, Any],
        config_entry: ConfigEntry | None,
        http_client: ClientSession,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the Verisure OWA hub."""
        self.config = domain_config
        self.config_entry: ConfigEntry | None = config_entry
        self.country: str = domain_config[CONF_COUNTRY].upper()
        api_domains = ApiDomains()
        self.lang: str = api_domains.get_language(self.country)
        self.hass: HomeAssistant = hass
        self._services_cache: dict[str, list[Service]] = {}
        # Mirrors `installation.alarm_partitions` (a side-effect of
        # client.get_services) keyed by installation number so cache hits
        # in get_services can re-apply the partitions to a fresh
        # Installation instance — required by detect_peri's Italian
        # SDVECU signal.
        self._partitions_cache: dict[str, list[dict[str, Any]]] = {}
        self.log_filter: SensitiveDataFilter | None = hass.data.get(DOMAIN, {}).get(
            "log_filter"
        )
        transport = HttpTransport(
            session=http_client,
            base_url=api_domains.get_url(self.country),
        )
        self.client: VerisureOwaClient = VerisureOwaClient(
            transport=transport,
            country=self.country,
            language=self.lang,
            username=domain_config[CONF_USERNAME],
            password=domain_config.get(CONF_PASSWORD, ""),
            device_id=domain_config[CONF_DEVICE_ID],
            uuid=domain_config[CONF_UNIQUE_ID],
            id_device_indigitall=domain_config[CONF_DEVICE_INDIGITALL],
            poll_delay=domain_config[CONF_DELAY_CHECK_OPERATION],
            poll_timeout=domain_config.get(
                CONF_OPERATION_POLL_TIMEOUT, DEFAULT_OPERATION_POLL_TIMEOUT
            ),
            log_filter=self.log_filter,
            refresh_token=domain_config.get(CONF_REFRESH_TOKEN),
            on_refresh_token_changed=self._persist_refresh_token,
        )
        self._api_queue = ApiQueue(
            interval=domain_config[CONF_DELAY_CHECK_OPERATION],
        )
        self.camera_images: dict[str, bytes] = {}
        self.camera_timestamps: dict[str, str] = {}
        self._camera_devices_cache: dict[str, list[CameraDevice]] = {}
        self._camera_capturing: set[str] = set()  # keys of cameras currently capturing
        # Coalesce concurrent full-image fetches for the same id_signal — two
        # dashboard cards on the same camera share one API call.
        self._full_image_inflight: dict[str, asyncio.Future[bytes | None]] = {}

    async def login(self) -> None:
        """Authenticate, preferring a stored refresh token over a password login.

        With no password to fall back on, a rejected refresh token raises
        AuthenticationError so the caller can map it to ConfigEntryAuthFailed —
        sending an empty password to the API would just waste a round trip.
        """
        if self.client.refresh_token_value:
            try:
                if await self.client.refresh_token():
                    return
            except VerisureOwaError as err:
                _LOGGER.warning("Refresh failed: %s", err.log_detail())
            if not self.client.password:
                raise AuthenticationError(
                    "Refresh token rejected and no password available; reauth required"
                )
            _LOGGER.info("Falling back to password login after refresh failure")
        await self.client.login()

    async def validate_device(self) -> tuple[str | None, list[OtpPhone] | None]:
        """Validate the current device."""
        return await self.client.validate_device(False, "", "")

    async def send_sms_code(
        self, auth_otp_hash: str, sms_code: str
    ) -> tuple[str | None, list[OtpPhone] | None]:
        """Send the SMS."""
        return await self.client.validate_device(True, auth_otp_hash, sms_code)

    async def refresh_token(self) -> bool:
        """Refresh the token."""
        return await self.client.refresh_token()

    async def send_opt(self, challange: str, phone_index: int) -> None:
        """Call for the SMS challange."""
        await self.client.send_otp(phone_index, challange)

    async def get_services(
        self, instalation: Installation, priority: int | None = None
    ) -> list[Service]:
        """Get the list of services from the installation (cached).

        ``client.get_services`` mutates ``installation.alarm_partitions`` as
        a side effect — Italian SDVECU panels need that field for capability
        detection (it's the only signal that fires for them).  Cache the
        partitions alongside the services and re-apply them on cache hits
        so downstream detect_peri sees them no matter which Installation
        instance the caller passed in.
        """
        if priority is None:
            priority = ApiQueue.BACKGROUND
        key = instalation.number
        if key in self._services_cache:
            cached_partitions = self._partitions_cache.get(key)
            if cached_partitions is not None:
                instalation.alarm_partitions = list(cached_partitions)
            return self._services_cache[key]
        services = await self._api_queue.submit(
            self.client.get_services,
            instalation,
            priority=priority,
        )
        self._services_cache[key] = services
        # Snapshot the partitions populated by client.get_services so the
        # next caller with a fresh Installation can recover them.
        self._partitions_cache[key] = list(instalation.alarm_partitions)
        return services

    async def get_camera_devices(
        self, installation: Installation
    ) -> list[CameraDevice]:
        """Get camera devices for an installation (cached)."""
        key = installation.number
        if key in self._camera_devices_cache:
            return self._camera_devices_cache[key]
        devices = await self._api_queue.submit(
            self.client.get_camera_devices,
            installation,
            priority=ApiQueue.BACKGROUND,
        )
        self._camera_devices_cache[key] = devices
        return devices

    def is_capturing(self, installation_number: str, zone_id: str) -> bool:
        """Return True if a capture is in progress for this camera."""
        return f"{installation_number}_{zone_id}" in self._camera_capturing

    async def capture_image(
        self, installation: Installation, camera_device: CameraDevice
    ) -> tuple[bytes | None, ThumbnailResponse | None]:
        """Request a new image capture and fetch the result.

        The client handles all capture polling internally.  The hub keeps
        HA-specific dispatcher signals, image validation/storage, and the
        background full-image fetch.

        Returns the validated JPEG bytes (or None) AND the ThumbnailResponse
        (so callers can read the real ``id_signal`` / ``signal_type`` of the
        captured frame).
        """
        device = camera_device
        capture_key = f"{installation.number}_{device.zone_id}"
        self._camera_capturing.add(capture_key)
        async_dispatcher_send(
            self.hass, SIGNAL_CAMERA_STATE, installation.number, device.zone_id
        )

        try:
            # Delegate capture + polling entirely to the client.  The client
            # pre-fetches a baseline thumbnail right before submitting the
            # capture so it can poll for a strictly-newer frame afterwards —
            # cached or coordinator-held timestamps aren't safe baselines
            # because the CDN may already be serving a different stale frame.
            thumbnail = await self._api_queue.submit(
                partial(
                    self.client.capture_image,
                    installation,
                    device.code,
                    device.device_type,
                    device.zone_id,
                    wait_for_fresh=True,
                ),
                priority=ApiQueue.FOREGROUND,
            )

            image_bytes = self._validate_and_store_image(
                thumbnail, installation, device, log_warnings=True
            )

            # Clear the capturing flag BEFORE pushing the new thumbnail into
            # the coordinator — the entity's _handle_coordinator_update writes
            # state with the new (rotated) token, and the frontend card's
            # spinner-clear condition requires capturing=False at that moment.
            self._camera_capturing.discard(capture_key)

            # Push thumbnail into the camera coordinator so entities update
            self._update_camera_coordinator_thumbnail(device.zone_id, thumbnail)

            if image_bytes is None:
                async_dispatcher_send(
                    self.hass,
                    SIGNAL_CAMERA_STATE,
                    installation.number,
                    device.zone_id,
                )

            # Fetch full-resolution image in background
            if thumbnail is not None and thumbnail.id_signal and thumbnail.signal_type:
                self.hass.async_create_task(
                    self._fetch_and_store_full_image(installation, device, thumbnail)
                )

            return image_bytes, thumbnail
        finally:
            self._camera_capturing.discard(capture_key)

    async def fetch_full_image(
        self,
        installation: Installation,
        id_signal: str,
        signal_type: str,
        *,
        priority: int | None = None,
    ) -> bytes | None:
        """Fetch a full-resolution image, coalescing concurrent calls per signal.

        If another caller is already fetching this `id_signal`, waits on that
        in-flight task instead of issuing a duplicate API request.
        """
        if priority is None:
            priority = ApiQueue.BACKGROUND
        key = f"{installation.number}_{id_signal}"
        inflight = self._full_image_inflight.get(key)
        if inflight is not None:
            # Shield so a cancellation of *this* awaiter doesn't tear down
            # the shared task that other awaiters still depend on.
            return await asyncio.shield(inflight)

        task = self.hass.async_create_task(
            self._api_queue.submit(
                self.client.get_full_image,
                installation,
                id_signal,
                signal_type,
                priority=priority,
            ),
            name=f"verisure_owa_full_image_{key}",
        )
        self._full_image_inflight[key] = task
        task.add_done_callback(lambda _t: self._full_image_inflight.pop(key, None))
        return await asyncio.shield(task)

    async def _fetch_and_store_full_image(
        self,
        installation: Installation,
        camera_device: CameraDevice,
        thumbnail: ThumbnailResponse,
    ) -> None:
        """Fetch the full-resolution photo and store it, then notify the frontend."""
        if not thumbnail.id_signal or not thumbnail.signal_type:
            return
        try:
            full_bytes = await self.fetch_full_image(
                installation,
                thumbnail.id_signal,
                thumbnail.signal_type,
                priority=ApiQueue.BACKGROUND,
            )
        except Exception:  # pylint: disable=broad-exception-caught
            _LOGGER.warning(
                "Could not fetch full image for %s",
                camera_device.name,
                exc_info=True,
            )
            return

        if not full_bytes or not full_bytes.startswith(b"\xff\xd8"):
            return

        # Push full image into the camera coordinator so entities update
        self._update_camera_coordinator_full_image(camera_device.zone_id, full_bytes)

    def _validate_and_store_image(
        self,
        thumbnail: ThumbnailResponse | None,
        installation: Installation,
        camera_device: CameraDevice,
        *,
        log_warnings: bool = True,
    ) -> bytes | None:
        """Decode, validate JPEG, and cache a thumbnail image."""
        if thumbnail is None or thumbnail.image is None:
            return None
        image_bytes = base64.b64decode(thumbnail.image)
        if not image_bytes.startswith(b"\xff\xd8"):
            if log_warnings:
                _LOGGER.warning(
                    "Thumbnail for %s is not JPEG data (got %d bytes starting with %r)",
                    camera_device.name,
                    len(image_bytes),
                    image_bytes[:40],
                )
            return None
        key = f"{installation.number}_{camera_device.zone_id}"
        self.camera_images[key] = image_bytes
        if thumbnail.timestamp:
            self.camera_timestamps[key] = thumbnail.timestamp
        return image_bytes

    def _get_camera_coordinator(self) -> Any | None:
        """Return the CameraCoordinator for this entry, if available."""
        entry_id = self.config_entry.entry_id if self.config_entry else None
        if entry_id is None:
            return None
        entry_data = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is None:
            return None
        return entry_data.get("camera_coordinator")

    def _update_camera_coordinator_thumbnail(
        self, zone_id: str, thumbnail: ThumbnailResponse
    ) -> None:
        """Push a new thumbnail into the CameraCoordinator's data."""
        if thumbnail is None:
            return
        camera_coord = self._get_camera_coordinator()
        if camera_coord is None or camera_coord.data is None:
            return
        from .coordinators import CameraData

        new_thumbnails = {**camera_coord.data.thumbnails, zone_id: thumbnail}
        new_data = CameraData(
            thumbnails=new_thumbnails,
            full_images=dict(camera_coord.data.full_images),
        )
        camera_coord.async_set_updated_data(new_data)

    def _update_camera_coordinator_full_image(
        self, zone_id: str, full_bytes: bytes
    ) -> None:
        """Push a new full-resolution image into the CameraCoordinator's data."""
        camera_coord = self._get_camera_coordinator()
        if camera_coord is None or camera_coord.data is None:
            return
        from .coordinators import CameraData

        new_full_images = {**camera_coord.data.full_images, zone_id: full_bytes}
        new_data = CameraData(
            thumbnails=dict(camera_coord.data.thumbnails),
            full_images=new_full_images,
        )
        camera_coord.async_set_updated_data(new_data)

    def get_camera_image(self, installation_number: str, zone_id: str) -> bytes | None:
        """Return the last captured image for a camera."""
        return self.camera_images.get(f"{installation_number}_{zone_id}")

    def get_camera_timestamp(
        self, installation_number: str, zone_id: str
    ) -> str | None:
        """Return the timestamp of the last captured image."""
        return self.camera_timestamps.get(f"{installation_number}_{zone_id}")

    def get_authentication_token(self) -> str | None:
        """Get the authentication token."""
        return self.client.authentication_token

    def get_refresh_token(self) -> str:
        """Get the long-lived refresh token, or empty string if absent."""
        return self.client.refresh_token_value

    def _persist_refresh_token(self, value: str) -> None:
        """Write a rotated refresh token back to the config entry.

        Also scrubs any legacy CONF_PASSWORD on the first capture. No-op when
        the hub is detached from a config entry (config-flow construction).
        """
        if self.config_entry is None:
            return
        existing = self.config_entry.data
        if existing.get(CONF_REFRESH_TOKEN) == value and CONF_PASSWORD not in existing:
            return
        new_data = {**existing, CONF_REFRESH_TOKEN: value}
        new_data.pop(CONF_PASSWORD, None)
        self.hass.config_entries.async_update_entry(self.config_entry, data=new_data)

    async def get_lock_modes(
        self, installation: Installation, *, priority: int | None = None
    ) -> list[SmartLockMode]:
        """Get lock modes from the API via the queue."""
        if priority is None:
            priority = ApiQueue.BACKGROUND

        try:
            modes: list[SmartLockMode] = await self._api_queue.submit(
                self.client.get_lock_modes,
                installation,
                priority=priority,
            )
        except VerisureOwaError as err:
            _LOGGER.warning(
                "Error fetching lock modes for %s: %s",
                installation.number,
                err.log_detail(),
            )
            modes = []

        return modes

    async def arm_alarm(
        self, installation: Installation, command: str, **force_params: str
    ) -> Any:
        """Arm the alarm via the client (polling handled internally)."""
        force_id = force_params.get("force_arming_remote_id")
        suid = force_params.get("suid")

        async def _arm() -> OperationStatus:
            return await self.client.arm(
                installation, command, force_id=force_id, suid=suid
            )

        return await self._api_queue.submit(
            _arm,
            priority=ApiQueue.FOREGROUND,
        )

    async def refresh_alarm_status(self, installation: Installation) -> OperationStatus:
        """Full alarm status refresh via CheckAlarm + poll (through queue).

        Used by the refresh button for an authoritative protom round-trip.
        """
        return await self._api_queue.submit(
            self.client.check_alarm,
            installation,
            priority=ApiQueue.FOREGROUND,
        )

    async def disarm_alarm(self, installation: Installation, command: str) -> Any:
        """Disarm the alarm via the client (polling handled internally)."""
        return await self._api_queue.submit(
            self.client.disarm,
            installation,
            command,
            priority=ApiQueue.FOREGROUND,
        )

    async def change_lock_mode(
        self, installation: Installation, lock_state: bool, device_id: str
    ) -> None:
        """Send lock/unlock command and wait for completion.

        The client handles all polling internally.
        """
        await self._api_queue.submit(
            self.client.change_lock_mode,
            installation,
            lock_state,
            device_id,
            priority=ApiQueue.FOREGROUND,
        )

    async def get_lock_config(
        self,
        installation: Installation,
        device_id: str,
        *,
        priority: int = ApiQueue.FOREGROUND,
    ) -> SmartLock | None:
        """Fetch lock config, auto-detecting Smartlock vs Danalock API.

        The client handles auto-detection and Danalock polling internally.
        Returns SmartLock or None if both paths fail.
        """
        result = await self._api_queue.submit(
            self.client.get_lock_config,
            installation,
            device_id,
            priority=priority,
        )
        return result if result and result.res == "OK" else None

    @property
    def api_queue(self) -> ApiQueue:
        """Return the API queue."""
        return self._api_queue

    @api_queue.setter
    def api_queue(self, value: ApiQueue) -> None:
        """Set the API queue."""
        self._api_queue = value

    @property
    def services_cache(self) -> dict[str, list[Service]]:
        """Return the services cache."""
        return self._services_cache

    @property
    def get_config_entry(self) -> ConfigEntry | None:
        """Return the config entry."""
        return self.config_entry
