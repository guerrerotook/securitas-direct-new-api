"""SecuritasHub and SecuritasDirectDevice classes."""

import base64
import logging
import time
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
    API_CACHE_TTL,
    CONF_COUNTRY,
    CONF_DELAY_CHECK_OPERATION,
    CONF_DEVICE_INDIGITALL,
    DOMAIN,
    SIGNAL_CAMERA_STATE,
)
from .log_filter import SensitiveDataFilter
from .securitas_direct_new_api import (
    ApiDomains,
    CameraDevice,
    Installation,
    OperationStatus,
    OtpPhone,
    SmartLock,
    SecuritasDirectError,
    Service,
)
from .securitas_direct_new_api.client import SecuritasClient
from .securitas_direct_new_api.http_transport import HttpTransport

_LOGGER = logging.getLogger(__name__)


def _notify_error(
    hass: HomeAssistant, notification_id, title: str, message: str
) -> None:
    """Notify user with persistent notification."""
    hass.async_create_task(
        hass.services.async_call(
            domain="persistent_notification",
            service="create",
            service_data={
                "title": title,
                "message": message,
                "notification_id": f"{DOMAIN}.{notification_id}",
            },
        )
    )


class SecuritasDirectDevice:
    """Securitas direct device instance."""

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
            manufacturer="Securitas Direct",
            model=self.installation.panel,
            hw_version=self.installation.type,
            name=self.name,
        )


class SecuritasHub:
    """A Securitas hub wrapper class."""

    def __init__(
        self,
        domain_config: dict,
        config_entry: ConfigEntry | None,
        http_client: ClientSession,
        hass: HomeAssistant,
    ) -> None:
        """Initialize the Securitas hub."""
        self.config = domain_config
        self.config_entry: ConfigEntry | None = config_entry
        self.country: str = domain_config[CONF_COUNTRY].upper()
        api_domains = ApiDomains()
        self.lang: str = api_domains.get_language(self.country)
        self.hass: HomeAssistant = hass
        self._services_cache: dict[str, list[Service]] = {}
        self.log_filter: SensitiveDataFilter | None = hass.data.get(DOMAIN, {}).get(
            "log_filter"
        )
        transport = HttpTransport(
            session=http_client,
            base_url=api_domains.get_url(self.country),
        )
        self.client: SecuritasClient = SecuritasClient(
            transport=transport,
            country=self.country,
            language=self.lang,
            username=domain_config[CONF_USERNAME],
            password=domain_config[CONF_PASSWORD],
            device_id=domain_config[CONF_DEVICE_ID],
            uuid=domain_config[CONF_UNIQUE_ID],
            id_device_indigitall=domain_config[CONF_DEVICE_INDIGITALL],
            poll_delay=domain_config[CONF_DELAY_CHECK_OPERATION],
            log_filter=self.log_filter,
        )
        self.installations: list[Installation] = []
        self._api_queue = ApiQueue(
            interval=domain_config[CONF_DELAY_CHECK_OPERATION],
        )
        self._lock_modes: dict[
            str, list
        ] = {}  # installation.number -> SmartLockMode list
        self._lock_modes_time: dict[str, float] = {}  # last fetch time per installation
        self.camera_images: dict[str, bytes] = {}
        self.camera_timestamps: dict[str, str] = {}
        self._camera_devices_cache: dict[str, list[CameraDevice]] = {}
        self._camera_capturing: set[str] = set()  # keys of cameras currently capturing
        self._full_images: dict[str, bytes] = {}
        self._full_timestamps: dict[str, str] = {}

    async def login(self):
        """Login to Securitas."""
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

    async def send_opt(self, challange: str, phone_index: int):
        """Call for the SMS challange."""
        return await self.client.send_otp(phone_index, challange)

    async def get_services(
        self, instalation: Installation, priority=None
    ) -> list[Service]:
        """Get the list of services from the installation (cached)."""
        if priority is None:
            priority = ApiQueue.BACKGROUND
        key = instalation.number
        if key in self._services_cache:
            return self._services_cache[key]
        services = await self._api_queue.submit(
            self.client.get_services,
            instalation,
            priority=priority,
        )
        self._services_cache[key] = services
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
    ) -> bytes | None:
        """Request a new image capture and fetch the result.

        The client handles all capture polling internally.  The hub keeps
        HA-specific dispatcher signals, image validation/storage, and the
        background full-image fetch.
        """
        device = camera_device
        capture_key = f"{installation.number}_{device.zone_id}"
        self._camera_capturing.add(capture_key)
        async_dispatcher_send(
            self.hass, SIGNAL_CAMERA_STATE, installation.number, device.zone_id
        )

        try:
            # Delegate capture + polling entirely to the client
            thumbnail = await self._api_queue.submit(
                self.client.capture_image,
                installation,
                device.code,
                device.device_type,
                device.zone_id,
                priority=ApiQueue.FOREGROUND,
            )

            image_bytes = self._validate_and_store_image(
                thumbnail, installation, device, log_warnings=True
            )

            # Push thumbnail into the camera coordinator so entities update
            self._update_camera_coordinator_thumbnail(
                installation, device.zone_id, thumbnail
            )

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

            return image_bytes
        finally:
            self._camera_capturing.discard(capture_key)

    async def fetch_latest_thumbnail(
        self, installation: Installation, camera_device: CameraDevice
    ) -> None:
        """Fetch the current thumbnail from the API and store it."""
        try:
            thumbnail = await self._api_queue.submit(
                self.client.get_thumbnail,
                installation,
                camera_device.device_type,
                camera_device.zone_id,
                priority=ApiQueue.BACKGROUND,
            )
        except Exception:  # pylint: disable=broad-exception-caught  # API call may raise anything
            _LOGGER.debug(
                "[hub] Could not fetch thumbnail for %s on startup",
                camera_device.name,
            )
            return

        image_bytes = self._validate_and_store_image(
            thumbnail, installation, camera_device, log_warnings=False
        )
        if image_bytes is not None:
            self._update_camera_coordinator_thumbnail(
                installation, camera_device.zone_id, thumbnail
            )

        if thumbnail.id_signal and thumbnail.signal_type:
            self.hass.async_create_task(
                self._fetch_and_store_full_image(installation, camera_device, thumbnail)
            )

    async def _fetch_and_store_full_image(
        self,
        installation: Installation,
        camera_device: CameraDevice,
        thumbnail,
    ) -> None:
        """Fetch the full-resolution photo and store it, then notify the frontend."""
        try:
            full_bytes = await self._api_queue.submit(
                self.client.get_full_image,
                installation,
                thumbnail.id_signal,
                thumbnail.signal_type,
                priority=ApiQueue.BACKGROUND,
            )
        except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
            _LOGGER.warning(
                "[hub] Could not fetch full image for %s",
                camera_device.name,
                exc_info=True,
            )
            return

        if not full_bytes or not full_bytes.startswith(b"\xff\xd8"):
            _LOGGER.debug(
                "[hub] Full image for %s is not valid JPEG", camera_device.name
            )
            return

        key = f"{installation.number}_{camera_device.zone_id}"
        self._full_images[key] = full_bytes
        if thumbnail.timestamp:
            self._full_timestamps[key] = thumbnail.timestamp

        # Push full image into the camera coordinator so entities update
        self._update_camera_coordinator_full_image(
            installation, camera_device.zone_id, full_bytes
        )

    def _validate_and_store_image(
        self,
        thumbnail,
        installation: Installation,
        camera_device,
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

    def _get_camera_coordinator(
        self,
        installation: Installation,  # pylint: disable=unused-argument
    ):
        """Return the CameraCoordinator for an installation, if available."""
        entry_id = self.config_entry.entry_id if self.config_entry else None
        if entry_id is None:
            return None
        entry_data = self.hass.data.get(DOMAIN, {}).get(entry_id)
        if entry_data is None:
            return None
        return entry_data.get("camera_coordinator")

    def _update_camera_coordinator_thumbnail(
        self, installation: Installation, zone_id: str, thumbnail
    ) -> None:
        """Push a new thumbnail into the CameraCoordinator's data."""
        if thumbnail is None:
            return
        camera_coord = self._get_camera_coordinator(installation)
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
        self, installation: Installation, zone_id: str, full_bytes: bytes
    ) -> None:
        """Push a new full-resolution image into the CameraCoordinator's data."""
        camera_coord = self._get_camera_coordinator(installation)
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

    def get_full_image(self, installation_number: str, zone_id: str) -> bytes | None:
        """Return the last full-resolution image for a camera."""
        return self._full_images.get(f"{installation_number}_{zone_id}")

    def get_full_timestamp(self, installation_number: str, zone_id: str) -> str | None:
        """Return the timestamp of the last full-resolution image."""
        return self._full_timestamps.get(f"{installation_number}_{zone_id}")

    def get_authentication_token(self) -> str | None:
        """Get the authentication token."""
        return self.client.authentication_token

    def set_authentication_token(self, value: str):
        """Set the authentication token."""
        self.client.authentication_token = value

    async def logout(self):
        """Logout from Securitas."""
        try:
            await self.client.logout()
        except Exception:  # pylint: disable=broad-exception-caught  # noqa: BLE001
            _LOGGER.error("Could not log out from Securitas", exc_info=True)
            return False
        return True

    async def get_lock_modes(
        self, installation: Installation, *, priority: int | None = None
    ) -> list:
        """Get lock modes with caching, submitted via queue."""
        from .securitas_direct_new_api import SmartLockMode

        if priority is None:
            priority = ApiQueue.BACKGROUND

        _CACHE_TTL = API_CACHE_TTL
        now = time.monotonic()
        cached_time = self._lock_modes_time.get(installation.number, 0)
        if now - cached_time < _CACHE_TTL and installation.number in self._lock_modes:
            return self._lock_modes[installation.number]

        try:
            modes: list[SmartLockMode] = await self._api_queue.submit(
                self.client.get_lock_modes,
                installation,
                priority=priority,
            )
        except SecuritasDirectError as err:
            _LOGGER.warning(
                "Error fetching lock modes for %s: %s",
                installation.number,
                err.log_detail(),
            )
            modes = []

        self._lock_modes[installation.number] = modes
        self._lock_modes_time[installation.number] = time.monotonic()
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

        The client handles all polling internally.  After the client returns,
        the lock modes cache is invalidated so the caller fetches fresh state.
        """
        await self._api_queue.submit(
            self.client.change_lock_mode,
            installation,
            lock_state,
            device_id,
            priority=ApiQueue.FOREGROUND,
        )
        # Invalidate the cache so the caller fetches fresh state.
        self._lock_modes_time.pop(installation.number, None)

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
