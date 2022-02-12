"""Support for Securitas Direct alarms."""
from datetime import timedelta
from gettext import install
import logging
from time import sleep
from aiohttp import ClientSession

import voluptuous as vol

from homeassistant.const import (
    CONF_CODE,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_TOKEN,
    CONF_USERNAME,
    EVENT_HOMEASSISTANT_STOP,
    Platform,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import discovery
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.helpers.typing import ConfigType
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .securitas_direct_new_api.apimanager import ApiManager
from .securitas_direct_new_api.dataTypes import (
    CheckAlarmStatus,
    Installation,
    SStatus,
    Service,
)

_LOGGER = logging.getLogger(__name__)

CONF_ALARM = "alarm"
CONF_CODE_DIGITS = "code_digits"
CONF_COUNTRY = "country"
CONF_CHECK_ALARM_PANEL = "check_alarm_panel"

DOMAIN = "securitas"
SENTINE_CONFORT = "SENTINEL CONFORT"

MIN_SCAN_INTERVAL = timedelta(seconds=20)
DEFAULT_SCAN_INTERVAL = timedelta(seconds=40)
PLATFORMS = [Platform.ALARM_CONTROL_PANEL, Platform.SENSOR]
HUB = None

CONFIG_SCHEMA = vol.Schema(
    {
        DOMAIN: vol.Schema(
            {
                vol.Required(CONF_PASSWORD): cv.string,
                vol.Required(CONF_USERNAME): cv.string,
                vol.Optional(CONF_COUNTRY, default="ES"): cv.string,
                vol.Optional(CONF_ALARM, default=True): cv.boolean,
                vol.Optional(CONF_CODE_DIGITS, default=4): cv.positive_int,
                vol.Optional(CONF_CODE, default=""): cv.string,
                vol.Optional(CONF_CHECK_ALARM_PANEL, default=True): cv.boolean,
                vol.Optional(CONF_SCAN_INTERVAL, default=DEFAULT_SCAN_INTERVAL): (
                    vol.All(cv.time_period, vol.Clamp(min=MIN_SCAN_INTERVAL))
                ),
            }
        )
    },
    extra=vol.ALLOW_EXTRA,
)


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Establish connection with MELCloud."""
    if DOMAIN not in config:
        return True
    hass.async_create_task(
        hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_IMPORT},
            data={
                CONF_USERNAME: config[DOMAIN][CONF_USERNAME],
                CONF_PASSWORD: config[DOMAIN][CONF_PASSWORD],
                CONF_COUNTRY: config[DOMAIN][CONF_COUNTRY],
                CONF_CODE: config[DOMAIN][CONF_CODE],
                CONF_CHECK_ALARM_PANEL: config[DOMAIN][CONF_CHECK_ALARM_PANEL],
                CONF_SCAN_INTERVAL: config[DOMAIN][CONF_SCAN_INTERVAL],
            },
        )
    )

    # hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, lambda event: HUB.logout())
    # # for Installation in HUB.Installations:
    # #    HUB.update_overview(Installation)
    # for component in ("alarm_control_panel", "sensor"):
    #     discovery.load_platform(hass, component, DOMAIN, {}, config)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Establish connection with MELCloud."""
    config = dict()
    config[CONF_USERNAME] = entry.data[CONF_USERNAME]
    config[CONF_PASSWORD] = entry.data[CONF_PASSWORD]
    config[CONF_COUNTRY] = entry.data[CONF_COUNTRY]
    config[CONF_CODE] = entry.data[CONF_CODE]
    config[CONF_CHECK_ALARM_PANEL] = entry.data[CONF_CHECK_ALARM_PANEL]
    client: SecuritasHub = SecuritasHub(config, async_get_clientsession(hass))
    client.set_authentication_token(entry.data[CONF_TOKEN])
    instalations: list[
        SecuritasDirectDevice
    ] = await client.session.list_installations()
    devices: list[SecuritasDirectDevice] = []
    for instalation in instalations:
        devices.append(SecuritasDirectDevice(instalation))
    hass.data.setdefault(DOMAIN, {}).update({entry.entry_id: devices})
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)
    # hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, lambda event: client.logout())
    return True


async def async_unload_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(
        config_entry, PLATFORMS
    )
    hass.data[DOMAIN].pop(config_entry.entry_id)
    if not hass.data[DOMAIN]:
        hass.data.pop(DOMAIN)
    return unload_ok


# def setup(hass: HomeAssistant, config):
#     """Set up the Securitas component."""
#     global HUB
#     HUB = SecuritasHub(config[DOMAIN])
#     HUB.update_overview = Throttle(config[DOMAIN][CONF_SCAN_INTERVAL])(
#         HUB.update_overview
#     )
#     if not HUB.login():
#         return False
#     hass.bus.listen_once(EVENT_HOMEASSISTANT_STOP, lambda event: HUB.logout())
#     # for Installation in HUB.Installations:
#     #    HUB.update_overview(Installation)
#     for component in ("alarm_control_panel", "sensor"):
#         discovery.load_platform(hass, component, DOMAIN, {}, config)
#     return True


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

    def __init__(self, domain_config, http_client: ClientSession):
        """Initialize the Securitas hub."""
        self.overview: CheckAlarmStatus = {}
        self.config = domain_config
        self.sentinel_services: list[Service] = []
        self.check_alarm: bool = domain_config[CONF_CHECK_ALARM_PANEL]
        self.country: str = domain_config[CONF_COUNTRY].upper()
        self.lang: str = self.country.lower() if self.country != "UK" else "en"
        self.session: ApiManager = ApiManager(
            domain_config[CONF_USERNAME],
            domain_config[CONF_PASSWORD],
            country=self.country,
            language=self.lang,
            http_client=http_client,
        )
        self.installations: list[Installation] = []

    async def login(self):
        """Login to Securitas."""
        succeed: tuple[bool, str] = await self.session.login()
        _LOGGER.debug("Log in Securitas: %s", succeed[0])
        if not succeed[0]:
            _LOGGER.error("Could not log in to Securitas: %s", succeed[1])
            return False
        return True

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
        if self.check_alarm is True:
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
        sleep(1)
        alarm_status: CheckAlarmStatus = await self.session.check_alarm_status(
            installation, reference_id
        )
        if hasattr(alarm_status, "operationStatus"):
            while alarm_status.operationStatus == "WAIT":
                sleep(1)
                alarm_status = await self.session.check_alarm_status(
                    installation, reference_id
                )
        return alarm_status
