"""Support for Securitas Direct alarms."""

import asyncio
from collections import OrderedDict
import logging
from uuid import uuid4

from aiohttp import ClientSession
import voluptuous as vol

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_ERROR,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo

from .log_filter import SensitiveDataFilter
from .securitas_direct_new_api import (
    ALARM_STATUS_POLL_DELAY,
    ApiDomains,
    ApiManager,
    CheckAlarmStatus,
    Installation,
    Login2FAError,
    LoginError,
    OtpPhone,
    PERI_DEFAULTS,
    SecuritasDirectError,
    Service,
    SStatus,
    STD_DEFAULTS,
    generate_device_id,
    generate_uuid,
)

_LOGGER = logging.getLogger(__name__)

DOMAIN = "securitas"

CONF_COUNTRY = "country"
CONF_CODE_ARM_REQUIRED = "code_arm_required"
CONF_CHECK_ALARM_PANEL = "check_alarm_panel"
CONF_USE_2FA = "use_2FA"
CONF_PERI_ALARM = "PERI_alarm"
CONF_DEVICE_INDIGITALL = "idDeviceIndigitall"
CONF_ENTRY_ID = "entry_id"
CONF_INSTALLATION_KEY = "instalation"
CONF_DELAY_CHECK_OPERATION = "delay_check_operation"
CONF_MAP_HOME = "map_home"
CONF_MAP_AWAY = "map_away"
CONF_MAP_NIGHT = "map_night"
CONF_MAP_CUSTOM = "map_custom"
CONF_NOTIFY_GROUP = "notify_group"

DEFAULT_USE_2FA = True
DEFAULT_SCAN_INTERVAL = 120
DEFAULT_CODE_ARM_REQUIRED = False
DEFAULT_CHECK_ALARM_PANEL = True
DEFAULT_DELAY_CHECK_OPERATION = 2
DEFAULT_CODE = ""
DEFAULT_PERI_ALARM = False
DEFAULT_COUNTRY = "ES"


PLATFORMS = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.SENSOR,
    Platform.LOCK,
]
HUB = None


CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_USERNAME): str,
                vol.Required(CONF_PASSWORD): str,
                vol.Optional(CONF_USE_2FA, default=DEFAULT_USE_2FA): bool,
                vol.Optional(CONF_COUNTRY, default=DEFAULT_COUNTRY): str,
                vol.Optional(CONF_CODE, default=DEFAULT_CODE): str,
                vol.Optional(CONF_PERI_ALARM, default=DEFAULT_PERI_ALARM): bool,
                vol.Optional(
                    CONF_CODE_ARM_REQUIRED, default=DEFAULT_CODE_ARM_REQUIRED
                ): bool,
                vol.Optional(
                    CONF_CHECK_ALARM_PANEL, default=DEFAULT_CHECK_ALARM_PANEL
                ): bool,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


def add_device_information(config: dict) -> dict:
    """Add device information to the configuration."""
    if CONF_DEVICE_ID not in config:
        config[CONF_DEVICE_ID] = generate_device_id(config[CONF_COUNTRY])

    if CONF_UNIQUE_ID not in config:
        config[CONF_UNIQUE_ID] = generate_uuid()

    if CONF_DEVICE_INDIGITALL not in config:
        config[CONF_DEVICE_INDIGITALL] = str(uuid4())

    return config


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    if any(
        entry.data.get(attrib) != entry.options.get(attrib)
        for attrib in (
            CONF_CODE,
            CONF_CODE_ARM_REQUIRED,
            CONF_SCAN_INTERVAL,
            CONF_CHECK_ALARM_PANEL,
            CONF_PERI_ALARM,
            CONF_MAP_HOME,
            CONF_MAP_AWAY,
            CONF_MAP_NIGHT,
            CONF_MAP_CUSTOM,
            CONF_NOTIFY_GROUP,
        )
    ):
        # update entry replacing data with new options
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, **entry.options}
        )
        await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Establish connection with Securitas Direct."""
    need_sign_in: bool = False

    config = OrderedDict()
    config[CONF_USERNAME] = entry.data[CONF_USERNAME]
    config[CONF_PASSWORD] = entry.data[CONF_PASSWORD]
    config[CONF_USE_2FA] = entry.data.get(CONF_USE_2FA, DEFAULT_USE_2FA)
    config[CONF_COUNTRY] = entry.data.get(CONF_COUNTRY, None)
    config[CONF_CODE] = entry.data.get(CONF_CODE, DEFAULT_CODE)
    config[CONF_PERI_ALARM] = entry.data.get(CONF_PERI_ALARM, DEFAULT_PERI_ALARM)
    config[CONF_CODE_ARM_REQUIRED] = entry.data.get(
        CONF_CODE_ARM_REQUIRED, DEFAULT_CODE_ARM_REQUIRED
    )
    config[CONF_CHECK_ALARM_PANEL] = entry.data.get(
        CONF_CHECK_ALARM_PANEL, DEFAULT_CHECK_ALARM_PANEL
    )
    config[CONF_SCAN_INTERVAL] = entry.data.get(
        CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
    )
    config[CONF_DELAY_CHECK_OPERATION] = entry.data.get(
        CONF_DELAY_CHECK_OPERATION, DEFAULT_DELAY_CHECK_OPERATION
    )
    config[CONF_ENTRY_ID] = entry.entry_id
    config[CONF_NOTIFY_GROUP] = entry.data.get(CONF_NOTIFY_GROUP, "")
    config = add_device_information(config)

    # Read mapping config from entry data
    config[CONF_MAP_HOME] = entry.data.get(CONF_MAP_HOME)
    config[CONF_MAP_AWAY] = entry.data.get(CONF_MAP_AWAY)
    config[CONF_MAP_NIGHT] = entry.data.get(CONF_MAP_NIGHT)
    config[CONF_MAP_CUSTOM] = entry.data.get(CONF_MAP_CUSTOM)

    # Migrate old config: derive per-button mappings from PERI_alarm checkbox
    if config[CONF_MAP_HOME] is None:
        is_peri = config.get(CONF_PERI_ALARM, DEFAULT_PERI_ALARM)
        defaults = PERI_DEFAULTS if is_peri else STD_DEFAULTS
        config[CONF_MAP_HOME] = defaults[CONF_MAP_HOME]
        config[CONF_MAP_AWAY] = defaults[CONF_MAP_AWAY]
        config[CONF_MAP_NIGHT] = defaults[CONF_MAP_NIGHT]
        config[CONF_MAP_CUSTOM] = defaults[CONF_MAP_CUSTOM]
        hass.config_entries.async_update_entry(
            entry,
            data={
                **entry.data,
                CONF_MAP_HOME: config[CONF_MAP_HOME],
                CONF_MAP_AWAY: config[CONF_MAP_AWAY],
                CONF_MAP_NIGHT: config[CONF_MAP_NIGHT],
                CONF_MAP_CUSTOM: config[CONF_MAP_CUSTOM],
            },
        )

    if CONF_DEVICE_ID in entry.data:
        config[CONF_DEVICE_ID] = entry.data[CONF_DEVICE_ID]
    else:
        need_sign_in = True
    if CONF_UNIQUE_ID in entry.data:
        config[CONF_UNIQUE_ID] = entry.data[CONF_UNIQUE_ID]
    else:
        need_sign_in = True
    if CONF_DEVICE_INDIGITALL in entry.data:
        config[CONF_DEVICE_INDIGITALL] = entry.data[CONF_DEVICE_INDIGITALL]
    else:
        need_sign_in = True

    hass.data[DOMAIN] = {}

    # Set up log sanitization filter — must be on handlers, not the logger,
    # because logger-level filters don't apply to child logger records.
    log_filter = SensitiveDataFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(log_filter)
    hass.data[DOMAIN]["log_filter"] = log_filter

    # Register credentials immediately
    log_filter.update_secret("username", config[CONF_USERNAME])
    log_filter.update_secret("password", config[CONF_PASSWORD])

    hass.data[DOMAIN][CONF_ENTRY_ID] = entry.entry_id
    if not need_sign_in:
        client: SecuritasHub = SecuritasHub(
            config, entry, async_get_clientsession(hass), hass
        )
        entry.async_on_unload(entry.add_update_listener(async_update_options))
        hass.data.setdefault(DOMAIN, {})[entry.entry_id] = client
        try:
            await client.login()
        except Login2FAError:
            msg = (
                "Securitas Direct need a 2FA SMS code."
                "Please login again with your phone"
            )
            _notify_error(hass, "2fa_error", "Securitas Direct", msg)
            config[CONF_ERROR] = "2FA"
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=config
                )
            )
            return False
        except LoginError as err:
            _notify_error(hass, "login_error", "Securitas Direct", str(err))
            config[CONF_ERROR] = "login"
            hass.async_create_task(
                hass.config_entries.flow.async_init(
                    DOMAIN, context={"source": SOURCE_IMPORT}, data=config
                )
            )
            _LOGGER.error("Could not log in to Securitas %s", err.args)
            return False
        except SecuritasDirectError as err:
            _LOGGER.error("Unable to connect to Securitas Direct: %s", err.args[0])
            raise ConfigEntryNotReady("Unable to connect to Securitas Direct") from None
        else:
            hass.data[DOMAIN][SecuritasHub.__name__] = client
            try:
                installations: list[
                    Installation
                ] = await client.session.list_installations()
                devices: list[SecuritasDirectDevice] = []
                for installation in installations:
                    await client.get_services(installation)
                    devices.append(SecuritasDirectDevice(installation))
            except SecuritasDirectError as err:
                _LOGGER.error("Unable to connect to Securitas Direct: %s", err.args[0])
                raise ConfigEntryNotReady(
                    "Unable to connect to Securitas Direct"
                ) from None

            hass.data.setdefault(DOMAIN, {})[entry.unique_id] = config
            hass.data.setdefault(DOMAIN, {})[CONF_INSTALLATION_KEY] = devices
            await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
            return True
    else:
        config = add_device_information(entry.data.copy())
        config[CONF_SCAN_INTERVAL] = entry.data.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
        )
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config
            )
        )
        return False


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    log_filter = hass.data[DOMAIN].get("log_filter")
    if log_filter:
        for handler in logging.getLogger().handlers:
            handler.removeFilter(log_filter)

    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    hass.data[DOMAIN].pop(config_entry.entry_id, None)
    hass.data[DOMAIN].pop("log_filter", None)
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return unload_ok


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
        self._available = True

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
            identifiers={(DOMAIN, f"{self.installation.alias}")},
            manufacturer="Securitas Direct",
            model=self.installation.type,
            hw_version=self.installation.panel,
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
        self.overview: CheckAlarmStatus | dict = {}
        self.config = domain_config
        self.config_entry: ConfigEntry | None = config_entry
        self.sentinel_services: list[Service] = []
        self.check_alarm: bool = domain_config[CONF_CHECK_ALARM_PANEL]
        self.country: str = domain_config[CONF_COUNTRY].upper()
        self.lang: str = ApiDomains().get_language(self.country)
        self.hass: HomeAssistant = hass
        self.services: dict[int, list[Service]] = {1: []}
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

    async def get_services(self, instalation: Installation) -> list[Service]:
        """Get the list of services from the instalation."""
        return await self.session.get_all_services(instalation)

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

    async def update_overview(self, installation: Installation) -> CheckAlarmStatus:
        """Update the overview."""

        if self.check_alarm is not True:
            status: SStatus = SStatus()
            try:
                status = await self.session.check_general_status(installation)
            except SecuritasDirectError as err:
                _LOGGER.warning("Error checking general status: %s", err.args)

            return CheckAlarmStatus(
                status.status or "",
                "",
                status.status or "",
                installation.number,
                status.status or "",
                status.timestampUpdate or "",
            )

        alarm_status = CheckAlarmStatus()
        try:
            reference_id: str = await self.session.check_alarm(installation)
            await asyncio.sleep(ALARM_STATUS_POLL_DELAY)
            alarm_status = await self.session.check_alarm_status(
                installation, reference_id
            )
        except SecuritasDirectError as err:
            _LOGGER.error(err.args)

        return alarm_status

    @property
    def get_config_entry(self) -> ConfigEntry | None:
        return self.config_entry
