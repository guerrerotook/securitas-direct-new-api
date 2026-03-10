"""Constants for the Securitas Direct integration."""

import json
from pathlib import Path

from homeassistant.const import Platform

DOMAIN = "securitas"
SIGNAL_XSSTATUS_UPDATE = f"{DOMAIN}_xsstatus_update"
SIGNAL_CAMERA_UPDATE = f"{DOMAIN}_camera_update"
CARD_BASE_URL = "/securitas_panel/securitas-alarm-card.js"
_MANIFEST = json.loads((Path(__file__).parent / "manifest.json").read_text())
CARD_URL = f"{CARD_BASE_URL}?v={_MANIFEST['version']}"

CONF_ADVANCED = "advanced"
CONF_COUNTRY = "country"
CONF_CODE_ARM_REQUIRED = "code_arm_required"
CONF_HAS_PERI = "has_peri"
CONF_DEVICE_INDIGITALL = "idDeviceIndigitall"
CONF_ENTRY_ID = "entry_id"
CONF_DELAY_CHECK_OPERATION = "delay_check_operation"
CONF_MAP_HOME = "map_home"
CONF_MAP_AWAY = "map_away"
CONF_MAP_NIGHT = "map_night"
CONF_MAP_CUSTOM = "map_custom"
CONF_MAP_VACATION = "map_vacation"
CONF_NOTIFY_GROUP = "notify_group"
CONF_INSTALLATION = "installation"

DEFAULT_SCAN_INTERVAL = 120
DEFAULT_CODE_ARM_REQUIRED = False
DEFAULT_DELAY_CHECK_OPERATION = 2
DEFAULT_CODE = ""
DEFAULT_COUNTRY = "ES"
API_CACHE_TTL = 60  # seconds — sensor data changes hourly at most

COUNTRY_CODES: list[str] = ["AR", "BR", "CL", "ES", "FR", "GB", "IE", "IT", "PT"]

PLATFORMS = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.LOCK,
]
