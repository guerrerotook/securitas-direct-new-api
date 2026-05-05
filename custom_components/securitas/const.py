"""Constants for the Securitas Direct integration."""

import hashlib
from pathlib import Path

from homeassistant.const import Platform

DOMAIN = "securitas"
SIGNAL_CAMERA_STATE = f"{DOMAIN}_camera_state"  # state-only update, no token rotation


def _file_hash(path: Path) -> str:
    """Return a short content hash for cache-busting."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


_WWW = Path(__file__).parent / "www"
CARD_BASE_URL = "/securitas_panel/securitas-alarm-card.js"
CARD_URL = f"{CARD_BASE_URL}?v={_file_hash(_WWW / 'securitas-alarm-card.js')}"
CAMERA_CARD_BASE_URL = "/securitas_panel/securitas-camera-card.js"
CAMERA_CARD_URL = (
    f"{CAMERA_CARD_BASE_URL}?v={_file_hash(_WWW / 'securitas-camera-card.js')}"
)
EVENTS_CARD_BASE_URL = "/securitas_panel/securitas-events-card.js"
EVENTS_CARD_URL = (
    f"{EVENTS_CARD_BASE_URL}?v={_file_hash(_WWW / 'securitas-events-card.js')}"
)

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
CONF_FORCE_ARM_NOTIFICATIONS = "force_arm_notifications"
CONF_INSTALLATION = "installation"

DEFAULT_SCAN_INTERVAL = 120
DEFAULT_CODE_ARM_REQUIRED = False
DEFAULT_FORCE_ARM_NOTIFICATIONS = True
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

SENTINEL_SERVICE_NAMES: frozenset[str] = frozenset({"CONFORT", "COMFORTO", "COMFORT"})
