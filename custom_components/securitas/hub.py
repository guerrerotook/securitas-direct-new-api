"""SecuritasHub and SecuritasDirectDevice classes."""

import asyncio
import base64
import functools
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
    SIGNAL_CAMERA_UPDATE,
    SIGNAL_XSSTATUS_UPDATE,
)
from .log_filter import SensitiveDataFilter
from .securitas_direct_new_api import (
    ApiDomains,
    ApiManager,
    CameraDevice,
    Installation,
    OperationStatus,
    OtpPhone,
    SStatus,
    SecuritasDirectError,
    Service,
)

_LOGGER = logging.getLogger(__name__)

# API error messages that indicate the lock hasn't responded yet (transient)
_ERR_NO_RESPONSE = "alarm-manager.error_no_response_to_request"
_ERR_STATUS_NOT_FOUND = "alarm-manager.error_status_not_found"


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
        """Return the city of the instalation."""
        return self.installation.city

    @property
    def postal_code(self) -> str:
        """Return the postalCode of the instalation."""
        return self.installation.postalCode

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
        self.overview: OperationStatus | dict = {}
        self.xsstatus: dict[str, SStatus] = {}
        self.config = domain_config
        self.config_entry: ConfigEntry | None = config_entry
        self.sentinel_services: list[Service] = []
        self.country: str = domain_config[CONF_COUNTRY].upper()
        self.lang: str = ApiDomains().get_language(self.country)
        self.hass: HomeAssistant = hass
        self._services_cache: dict[str, list[Service]] = {}
        self.log_filter: SensitiveDataFilter | None = hass.data.get(DOMAIN, {}).get(
            "log_filter"
        )
        self.session: ApiManager = ApiManager(
            domain_config[CONF_USERNAME],
            domain_config[CONF_PASSWORD],
            self.country,
            http_client,
            domain_config[CONF_DEVICE_ID],
            domain_config[CONF_UNIQUE_ID],
            domain_config[CONF_DEVICE_INDIGITALL],
            domain_config[CONF_DELAY_CHECK_OPERATION],
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
        self._api_cache: dict[str, Any] = {}  # generic cache: key -> result
        self._api_cache_time: dict[str, float] = {}  # generic cache: key -> timestamp
        self.camera_images: dict[str, bytes] = {}
        self.camera_timestamps: dict[str, str] = {}
        self._camera_devices_cache: dict[str, list[CameraDevice]] = {}
        self._camera_capturing: set[str] = set()  # keys of cameras currently capturing

    async def login(self):
        """Login to Securitas."""
        await self.session.login()

    async def validate_device(self) -> tuple[str | None, list[OtpPhone] | None]:
        """Validate the current device."""
        return await self.session.validate_device(False, "", "")

    async def send_sms_code(
        self, auth_otp_hash: str, sms_code: str
    ) -> tuple[str | None, list[OtpPhone] | None]:
        """Send the SMS."""
        return await self.session.validate_device(True, auth_otp_hash, sms_code)

    async def refresh_token(self) -> bool:
        """Refresh the token."""
        return await self.session.refresh_token()

    async def send_opt(self, challange: str, phone_index: int):
        """Call for the SMS challange."""
        return await self.session.send_otp(phone_index, challange)

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
            self.session.get_all_services,
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
            self.session.get_device_list,
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
        """Request a new image capture and fetch the result."""
        device = camera_device
        capture_key = f"{installation.number}_{device.zone_id}"
        self._camera_capturing.add(capture_key)
        async_dispatcher_send(
            self.hass, SIGNAL_CAMERA_STATE, installation.number, device.zone_id
        )

        # Get the baseline thumbnail idSignal so we can detect when it changes
        baseline = await self._api_queue.submit(
            self.session.get_thumbnail,
            installation,
            device.device_type,
            device.zone_id,
            priority=ApiQueue.FOREGROUND,
        )
        baseline_id = baseline.id_signal

        # If the baseline image differs from what we have stored, we missed a previous
        # update — show it now while waiting for the new capture to arrive.
        # The baseline is fetched before the new capture is requested, so it can never
        # be the photo we're about to take.
        key = f"{installation.number}_{device.zone_id}"
        stored_timestamp = self.camera_timestamps.get(key)
        if baseline.image and baseline.timestamp != stored_timestamp:
            _LOGGER.debug(
                "[hub] Storing missed image for %s (server: %s, stored: %s)",
                device.name,
                baseline.timestamp,
                stored_timestamp,
            )
            self._validate_and_store_image(
                baseline, installation, device, log_warnings=False
            )
            async_dispatcher_send(
                self.hass, SIGNAL_CAMERA_UPDATE, installation.number, device.zone_id
            )

        reference_id = await self._api_queue.submit(
            self.session.request_images,
            installation,
            device.code,
            device.device_type,
            priority=ApiQueue.FOREGROUND,
        )

        # Poll for capture completion then wait for the thumbnail to update.
        # Both loops together are bounded by a hard 30-second wall-clock timeout.
        thumbnail = None

        async def _poll_capture_result() -> None:
            nonlocal thumbnail
            attempt = 0

            # Wait until the image request stops being "processing"
            while True:
                attempt += 1
                raw = await self._api_queue.submit(
                    self.session.check_request_images_status,
                    installation,
                    device.code,
                    reference_id,
                    attempt,
                    priority=ApiQueue.FOREGROUND,
                )
                msg = raw.get("msg", "")
                if "processing" not in msg and raw.get("res") != "WAIT":
                    break
                await asyncio.sleep(self.session.delay_check_operation)

            # Wait until the thumbnail idSignal changes (CDN propagation delay)
            while True:
                thumbnail = await self._api_queue.submit(
                    self.session.get_thumbnail,
                    installation,
                    device.device_type,
                    device.zone_id,
                    priority=ApiQueue.FOREGROUND,
                )
                if thumbnail.id_signal != baseline_id:
                    return
                await asyncio.sleep(max(5, self.session.delay_check_operation))

        try:
            await asyncio.wait_for(_poll_capture_result(), timeout=30)
        except TimeoutError:
            _LOGGER.warning(
                "Image capture timed out for %s after 30 seconds",
                device.name,
            )
            if thumbnail is None:
                thumbnail = await self._api_queue.submit(
                    self.session.get_thumbnail,
                    installation,
                    device.device_type,
                    device.zone_id,
                    priority=ApiQueue.FOREGROUND,
                )

        image_bytes = self._validate_and_store_image(
            thumbnail, installation, device, log_warnings=True
        )

        self._camera_capturing.discard(capture_key)
        if image_bytes is not None:
            async_dispatcher_send(
                self.hass, SIGNAL_CAMERA_UPDATE, installation.number, device.zone_id
            )
        else:
            # Even if no image arrived, clear the capturing state on the frontend
            async_dispatcher_send(
                self.hass, SIGNAL_CAMERA_STATE, installation.number, device.zone_id
            )
        return image_bytes

    async def fetch_latest_thumbnail(
        self, installation: Installation, camera_device: CameraDevice
    ) -> None:
        """Fetch the current thumbnail from the API and store it."""
        try:
            thumbnail = await self._api_queue.submit(
                self.session.get_thumbnail,
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
            async_dispatcher_send(
                self.hass,
                SIGNAL_CAMERA_UPDATE,
                installation.number,
                camera_device.zone_id,
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

    def get_camera_image(self, installation_number: str, zone_id: str) -> bytes | None:
        """Return the last captured image for a camera."""
        return self.camera_images.get(f"{installation_number}_{zone_id}")

    def get_camera_timestamp(
        self, installation_number: str, zone_id: str
    ) -> str | None:
        """Return the timestamp of the last captured image."""
        return self.camera_timestamps.get(f"{installation_number}_{zone_id}")

    def _max_poll_attempts(self, timeout_seconds: int = 30) -> int:
        """Calculate max polling attempts for a given timeout."""
        return max(
            10, round(timeout_seconds / max(1, self.session.delay_check_operation))
        )

    def get_authentication_token(self) -> str | None:
        """Get the authentication token."""
        return self.session.authentication_token

    def set_authentication_token(self, value: str):
        """Set the authentication token."""
        self.session.authentication_token = value

    async def logout(self):
        """Logout from Securitas."""
        ret = await self.session.logout()
        if not ret:
            _LOGGER.error("Could not log out from Securitas: %s", ret)
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
                self.session.get_lock_current_mode,
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

    async def _cached_api_call(self, cache_key: str, coro_fn, *args, priority=None):
        """Execute an API call with caching, submitted via queue.

        The cache is checked twice: once before queuing (fast path) and once
        inside the queue-submitted wrapper (after serialization).  This
        prevents duplicate API calls when multiple entities concurrently
        request the same cached data — they all miss the cache, queue up,
        but only the first actually calls the API; the rest see the freshly
        populated cache.
        """
        if priority is None:
            priority = ApiQueue.BACKGROUND
        _CACHE_TTL = API_CACHE_TTL
        now = time.monotonic()
        if (
            now - self._api_cache_time.get(cache_key, 0) < _CACHE_TTL
            and cache_key in self._api_cache
        ):
            return self._api_cache[cache_key]

        _sentinel = object()

        async def _call_with_cache_recheck(*call_args):
            # Re-check cache after queue serialization — another caller
            # may have populated it while we were waiting.
            now_inner = time.monotonic()
            if (
                now_inner - self._api_cache_time.get(cache_key, 0) < _CACHE_TTL
                and cache_key in self._api_cache
            ):
                return _sentinel  # signal: used cache, no API call made
            return await coro_fn(*call_args)

        result = await self._api_queue.submit(
            _call_with_cache_recheck,
            *args,
            priority=priority,
            label=f"{getattr(coro_fn, '__name__', coro_fn)}[{cache_key}]",
        )

        if result is _sentinel:
            return self._api_cache[cache_key]

        if result is not None:
            self._api_cache[cache_key] = result
            self._api_cache_time[cache_key] = time.monotonic()
        return result

    async def get_sentinel(self, installation: Installation, service: Service) -> Any:
        """Get sentinel data with rate-limit serialization and caching."""
        cache_key = f"sentinel_{installation.number}_{service.id}"
        return await self._cached_api_call(
            cache_key,
            self.session.get_sentinel_data,
            installation,
            service,
        )

    async def get_air_quality(self, installation: Installation, zone: str) -> Any:
        """Get air quality data with rate-limit serialization and caching."""
        cache_key = f"air_quality_{installation.number}_{zone}"
        return await self._cached_api_call(
            cache_key,
            self.session.get_air_quality_data,
            installation,
            zone,
        )

    async def arm_alarm(
        self, installation: Installation, command: str, **force_params: str
    ) -> Any:
        """Arm the alarm via queue-submitted API calls."""
        reference_id = await self._api_queue.submit(
            functools.partial(
                self.session.submit_arm_request, installation, command, **force_params
            ),
            priority=ApiQueue.FOREGROUND,
        )

        max_attempts = self._max_poll_attempts(timeout_seconds=30)
        for attempt in range(1, max_attempts + 1):
            raw = await self._api_queue.submit(
                self.session.check_arm_status,
                installation,
                reference_id,
                command,
                attempt,
                priority=ApiQueue.FOREGROUND,
            )
            if raw.get("res") != "WAIT":
                return await self.session.process_arm_result(raw, installation)

        raise TimeoutError("Arm status poll timed out")

    async def disarm_alarm(self, installation: Installation, command: str) -> Any:
        """Disarm the alarm via queue-submitted API calls."""
        # Capture protom_response at request time so status polls use the
        # correct currentStatus even if protom_response changes concurrently.
        current_status = self.session.protom_response
        reference_id = await self._api_queue.submit(
            self.session.submit_disarm_request,
            installation,
            command,
            priority=ApiQueue.FOREGROUND,
        )

        max_attempts = self._max_poll_attempts(timeout_seconds=30)
        for attempt in range(1, max_attempts + 1):
            raw = await self._api_queue.submit(
                self.session.check_disarm_status,
                installation,
                reference_id,
                command,
                attempt,
                current_status,
                priority=ApiQueue.FOREGROUND,
            )
            if raw.get("res") != "WAIT":
                return self.session.process_disarm_result(raw)

        raise TimeoutError("Disarm status poll timed out")

    async def refresh_alarm_status(self, installation: Installation) -> OperationStatus:
        """Full alarm status refresh via CheckAlarm + poll (through queue).

        Used by the refresh button for an authoritative protom round-trip.
        """
        reference_id = await self._api_queue.submit(
            self.session.check_alarm,
            installation,
            priority=ApiQueue.FOREGROUND,
        )

        max_attempts = self._max_poll_attempts(timeout_seconds=30)
        for _attempt in range(1, max_attempts + 1):
            status = await self._api_queue.submit(
                self.session.check_alarm_status,
                installation,
                reference_id,
                priority=ApiQueue.FOREGROUND,
            )
            if hasattr(status, "protomResponse") and status.protomResponse:
                return status
            # check_alarm_status returns OperationStatus with empty
            # protomResponse when still waiting
            raw = getattr(status, "operation_status", "")
            if raw != "WAIT":
                return status

        raise TimeoutError("Alarm status refresh timed out")

    async def update_overview(self, installation: Installation) -> OperationStatus:
        """Poll alarm status via check_general_status (single API call).

        Periodic polling always uses xSStatus for efficiency.  The more
        expensive CheckAlarm path (protom round-trip) is used only for
        arm/disarm operations and the manual refresh button.
        """
        try:
            status = await self._api_queue.submit(
                self.session.check_general_status,
                installation,
                priority=ApiQueue.BACKGROUND,
            )
        except SecuritasDirectError as err:
            _LOGGER.warning(
                "Error checking general status for %s: %s",
                installation.number,
                err.log_detail(),
            )
            if getattr(err, "http_status", None) == 403:
                raise
            return OperationStatus()
        self.xsstatus[installation.number] = status
        async_dispatcher_send(self.hass, SIGNAL_XSSTATUS_UPDATE, installation.number)
        return OperationStatus(
            operation_status=status.status or "",
            message="",
            status=status.status or "",
            installation_number=installation.number,
            protomResponse=status.status or "",
            protomResponseData=status.timestampUpdate or "",
        )

    async def change_lock_mode(
        self, installation: Installation, lock_state: bool, device_id: str
    ) -> Any:
        """Change lock mode via queue-submitted API calls.

        Returns the SmartLockModeStatus on success, or None if the command
        was accepted but the backend did not confirm the new state in time.
        """
        reference_id = await self._api_queue.submit(
            self.session.submit_change_lock_mode_request,
            installation,
            lock_state,
            device_id,
            priority=ApiQueue.FOREGROUND,
        )

        max_attempts = self._max_poll_attempts(timeout_seconds=30)
        last_err: SecuritasDirectError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                raw = await self._api_queue.submit(
                    self.session.check_change_lock_mode,
                    installation,
                    reference_id,
                    attempt,
                    device_id,
                    priority=ApiQueue.FOREGROUND,
                )
            except SecuritasDirectError as err:
                if err.message != _ERR_NO_RESPONSE:
                    raise
                _LOGGER.warning(
                    "Lock mode change for %s device %s: panel has not received "
                    "lock response yet (attempt %d/%d): %s",
                    installation.number,
                    device_id,
                    attempt,
                    max_attempts,
                    err.log_detail(),
                )
                last_err = err
                continue

            msg = raw.get("msg", "")
            if msg == _ERR_STATUS_NOT_FOUND:
                # The backend accepted the command but hasn't processed it
                # yet — keep polling.
                _LOGGER.debug(
                    "Lock mode change for %s device %s: status not found "
                    "yet (attempt %d/%d)",
                    installation.number,
                    device_id,
                    attempt,
                    max_attempts,
                )
                continue

            if raw.get("res") != "WAIT":
                # Invalidate cached lock status so the next periodic poll
                # fetches fresh state instead of returning stale data.
                self._lock_modes_time.pop(installation.number, None)
                return self.session.process_lock_mode_result(raw)

        # Polling exhausted without confirmation.  Invalidate the cache so
        # the caller (and background polls) fetch fresh state.
        self._lock_modes_time.pop(installation.number, None)

        if last_err is not None:
            raise last_err

        # Command was accepted but status never confirmed — return None so
        # the lock entity can fall back to optimistic state and let the
        # periodic poll pick up the real state later.
        _LOGGER.debug(
            "Lock mode change for %s device %s: command accepted but status "
            "not confirmed after %d attempts; using optimistic state",
            installation.number,
            device_id,
            max_attempts,
        )
        return None

    async def get_smart_lock_config(
        self, installation: Installation, device_id: str
    ) -> Any:
        """Fetch smart lock config via queue-submitted API calls."""
        return await self._api_queue.submit(
            self.session.get_smart_lock_config,
            installation,
            device_id,
            priority=ApiQueue.FOREGROUND,
        )

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
