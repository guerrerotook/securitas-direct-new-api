"""Support for Securitas Direct alarms."""
from collections import OrderedDict
from datetime import timedelta
import logging
import secrets
from uuid import uuid4
from aiohttp import ClientSession
import asyncio

import voluptuous as vol

from homeassistant.const import (
    CONF_CODE,
    CONF_DEVICE_ID,
    CONF_ERROR,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_UNIQUE_ID,
    CONF_USERNAME,
    Platform,
)
from homeassistant.core import HomeAssistant, ServiceCall
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .securitas_direct_new_api.apimanager import ApiManager
from .securitas_direct_new_api.dataTypes import (
    CheckAlarmStatus,
    Installation,
    OtpPhone,
    SStatus,
    Service,
)

_LOGGER = logging.getLogger(__name__)

CONF_ALARM = "alarm"
CONF_COUNTRY = "country"
CONF_CHECK_ALARM_PANEL = "check_alarm_panel"
CONF_DEVICE_INDIGITALL = "idDeviceIndigitall"

DOMAIN = "securitas"
SENTINE_CONFORT = "SENTINEL CONFORT"

MIN_SCAN_INTERVAL = 20
DEFAULT_SCAN_INTERVAL = 40
PLATFORMS = [Platform.ALARM_CONTROL_PANEL, Platform.SENSOR]
HUB = None

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(
                    CONF_USERNAME,
                ): str,
                vol.Required(
                    CONF_PASSWORD,
                ): str,
                vol.Optional(CONF_COUNTRY, default="ES"): str,
                vol.Optional(CONF_ALARM, default=True): bool,
                vol.Optional(CONF_CODE, default=4): int,
                vol.Optional(CONF_CHECK_ALARM_PANEL, default=True): bool,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): int,
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)

ATTR_INSTALATION_ID = "instalation_id"
SERVICE_REFRESH_INSTALATION = "refresh_alarm_status"

REFRESH_ALARM_STATUS_SCHEMA = vol.Schema(
    {
        vol.Required(
            ATTR_INSTALATION_ID, description="Instalation number"
        ): cv.positive_int
    }
)


def generate_uuid() -> str:
    """Create a device id."""
    return str(uuid4()).replace("-", "")[0:16]


def generate_device_id(lang: str) -> str:
    """Create a device identifier for the API."""
    return secrets.token_urlsafe(16) + ":APA91b" + secrets.token_urlsafe(130)[0:134]


def add_device_information(config: OrderedDict) -> OrderedDict:
    if not CONF_DEVICE_ID in config:
        config[CONF_DEVICE_ID] = generate_device_id(config[CONF_COUNTRY])

    if not CONF_UNIQUE_ID in config:
        config[CONF_UNIQUE_ID] = generate_uuid()

    if not CONF_DEVICE_INDIGITALL in config:
        config[CONF_DEVICE_INDIGITALL] = str(uuid4())

    return config


async def async_setup(hass: HomeAssistant, config_type: ConfigType) -> bool:
    """Establish connection with MELCloud."""
    if DOMAIN not in config_type:
        return True

    config: OrderedDict = config_type[DOMAIN]
    config = add_device_information(config)
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={
                CONF_USERNAME: config[CONF_USERNAME],
                CONF_PASSWORD: config[CONF_PASSWORD],
                CONF_COUNTRY: config[CONF_COUNTRY],
                CONF_CODE: config[CONF_CODE],
                CONF_CHECK_ALARM_PANEL: config[CONF_CHECK_ALARM_PANEL],
                CONF_SCAN_INTERVAL: config[CONF_SCAN_INTERVAL],
                CONF_DEVICE_ID: config[CONF_DEVICE_ID],
                CONF_UNIQUE_ID: config[CONF_UNIQUE_ID],
                CONF_DEVICE_INDIGITALL: config[CONF_DEVICE_INDIGITALL],
            },
        )
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Establish connection with Securitas Direct."""
    need_sign_in: bool = False
    config = OrderedDict()
    config[CONF_USERNAME] = entry.data[CONF_USERNAME]
    config[CONF_PASSWORD] = entry.data[CONF_PASSWORD]
    config[CONF_COUNTRY] = entry.data[CONF_COUNTRY]
    config[CONF_CODE] = entry.data[CONF_CODE]
    config[CONF_CHECK_ALARM_PANEL] = entry.data[CONF_CHECK_ALARM_PANEL]
    config[CONF_SCAN_INTERVAL] = 60
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
    if not need_sign_in:
        client: SecuritasHub = SecuritasHub(config, async_get_clientsession(hass), hass)
        result = await client.login()
        if result == "2FA":
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
        else:
            hass.data[DOMAIN] = {}
            hass.data[DOMAIN][SecuritasHub.__name__] = client
            instalations: list[
                SecuritasDirectDevice
            ] = await client.session.list_installations()
            devices: list[SecuritasDirectDevice] = []
            for instalation in instalations:
                devices.append(SecuritasDirectDevice(instalation))
            hass.data.setdefault(DOMAIN, {}).update({entry.entry_id: devices})
            await hass.async_add_executor_job(setup_hass_services, hass)
            hass.config_entries.async_setup_platforms(entry, PLATFORMS)
            # hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, lambda event: client.logout())
            return True
    else:
        config = add_device_information(entry.data.copy())
        config[CONF_SCAN_INTERVAL] = 60
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, context={"source": SOURCE_IMPORT}, data=config
            )
        )
        # hass.async_create_task(
        #     hass.config_entries.flow.async_init(
        #         DOMAIN, context={"source": SOURCE_IMPORT}, data=entry
        #     )
        # )
        return False


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    hass.data[DOMAIN].pop(config_entry.entry_id)
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return unload_ok


def setup_hass_services(hass: HomeAssistant) -> None:
    """Home Assistant services."""

    async def async_change_setting(call: ServiceCall) -> None:
        """Change an Abode system setting."""
        instalation_id: int = call.data[ATTR_INSTALATION_ID]

        client: SecuritasHub = hass.data[DOMAIN][SecuritasHub.__name__]
        for instalation in client.installations:
            if instalation.number == instalation_id:
                await client.update_overview(instalation)

    hass.services.register(
        DOMAIN,
        SERVICE_REFRESH_INSTALATION,
        async_change_setting,
        schema=REFRESH_ALARM_STATUS_SCHEMA,
    )


def _notify_error(hass, notification_id, title, message) -> None:
    """Notify user with persistent notification"""
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
    """MELCloud Device instance."""

    def __init__(self, instalation: Installation) -> None:
        """Construct a device wrapper."""
        self.instalation = instalation
        self.name = instalation.alias
        self._available = True

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return True

    @property
    def device_id(self) -> str:
        """Return device ID."""
        return self.instalation.number

    @property
    def address(self) -> str:
        """Return the address of the instalation."""
        return self.instalation.address

    @property
    def city(self) -> str:
        """Return the city of the instalation."""
        return self.instalation.city

    @property
    def postal_code(self) -> str:
        """Return the postalCode of the instalation."""
        return self.instalation.postalCode

    @property
    def device_info(self) -> DeviceInfo:
        """Return a device description for device registry."""
        return DeviceInfo(
            identifiers={(DOMAIN, f"{self.instalation.alias}")},
            manufacturer="Securitas Direct",
            model=self.instalation.type,
            hw_version=self.instalation.panel,
            name=self.name,
        )


class SecuritasHub:
    """A Securitas hub wrapper class."""

    def __init__(
        self,
        domain_config: OrderedDict,
        http_client: ClientSession,
        hass: HomeAssistant,
    ):
        """Initialize the Securitas hub."""
        self.overview: CheckAlarmStatus = {}
        self.config = domain_config
        self.sentinel_services: list[Service] = []
        self.check_alarm: bool = domain_config[CONF_CHECK_ALARM_PANEL]
        self.country: str = domain_config[CONF_COUNTRY].upper()
        self.lang: str = self.country.lower() if self.country != "UK" else "en"
        self.hass: HomeAssistant = hass
        self.session: ApiManager = ApiManager(
            domain_config[CONF_USERNAME],
            domain_config[CONF_PASSWORD],
            self.country,
            self.lang,
            http_client,
            domain_config[CONF_DEVICE_ID],
            domain_config[CONF_UNIQUE_ID],
            domain_config[CONF_DEVICE_INDIGITALL],
        )
        self.installations: list[Installation] = []

    async def login(self):
        """Login to Securitas."""
        succeed: tuple[bool, str] = await self.session.login()
        if not succeed[0] and succeed[1] == "2FA":
            # 2fa for securitas
            _LOGGER.info("2FA needed for the device")
            return succeed[1]

        _LOGGER.debug("Log in Securitas: %s", succeed[0])
        if not succeed[0]:
            _LOGGER.error("Could not log in to Securitas: %s", succeed[1])
            return False
        return True

    async def validate_device(self) -> tuple[str, list[OtpPhone]]:
        """Validate the current device."""
        return await self.session.validate_device(False, None, None)

    async def send_sms_code(
        self, auth_otp_hash: str, sms_code: str
    ) -> tuple[str, list[OtpPhone]]:
        """Send the SMS."""
        return await self.session.validate_device(True, auth_otp_hash, sms_code)

    async def refresh_token(self) -> tuple[str, list[OtpPhone]]:
        """Refresh the token."""
        return await self.session.refresh_token()

    async def sent_opt(self, challange: str, phone_index: int):
        """Calls for the SMS challange."""
        return await self.session.send_otp(phone_index, challange)

    async def get_services(self, instalation: Installation) -> list[Service]:
        """Gets the list of services from the instalation."""
        return await self.session.get_all_services(instalation)

    def get_authentication_token(self) -> str:
        """Gets the authentication token."""
        return self.session.authentication_token

    def set_authentication_token(self, value: str):
        """Sets the authentication token."""
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
            status: SStatus = await self.session.check_general_status(installation)
            return CheckAlarmStatus(
                status.status,
                None,
                status.status,
                installation.number,
                status.status,
                status.timestampUpdate,
            )

        reference_id: str = await self.session.check_alarm(installation)
        await asyncio.sleep(1)
        count: int = 1
        alarm_status: CheckAlarmStatus = await self.session.check_alarm_status(
            installation, reference_id, count
        )
        if hasattr(alarm_status, "operation_status"):
            while alarm_status.operation_status == "WAIT":
                await asyncio.sleep(1)
                count = count + 1
                alarm_status = await self.session.check_alarm_status(
                    installation, reference_id, count
                )
        return alarm_status
