"""Constants for the Verisure OWA integration."""

import hashlib
import json
from pathlib import Path

from homeassistant.const import Platform

DOMAIN = "securitas"
SIGNAL_CAMERA_STATE = f"{DOMAIN}_camera_state"  # state-only update, no token rotation


def _file_hash(path: Path) -> str:
    """Return a short content hash for cache-busting."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def _integration_version() -> str:
    """Read the integration version from manifest.json.

    Bundled into card URLs so every release shifts the cache key even
    when a card's bytes are unchanged — protects against
    browser/Lovelace-resource caches that latched the previous URL.
    """
    with open(Path(__file__).parent / "manifest.json", encoding="utf-8") as f:
        return json.load(f)["version"]


_WWW = Path(__file__).parent / "www"
_VERSION = _integration_version()


def _card_url(filename: str) -> str:
    return f"/verisure-owa-panel/{filename}?v={_file_hash(_WWW / filename)}-{_VERSION}"


CARD_BASE_URL = "/verisure-owa-panel/verisure-owa-alarm-card.js"
CARD_URL = _card_url("verisure-owa-alarm-card.js")
CAMERA_CARD_BASE_URL = "/verisure-owa-panel/verisure-owa-camera-card.js"
CAMERA_CARD_URL = _card_url("verisure-owa-camera-card.js")
ACTIVITY_LOG_CARD_BASE_URL = "/verisure-owa-panel/verisure-owa-activity-log-card.js"
ACTIVITY_LOG_CARD_URL = _card_url("verisure-owa-activity-log-card.js")

CONF_ADVANCED = "advanced"
CONF_COUNTRY = "country"
CONF_REFRESH_TOKEN = "refresh_token"
CONF_CODE_ARM_REQUIRED = "code_arm_required"
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
CONF_ENABLE_INTERIOR_PANEL = "enable_interior_panel"
CONF_ENABLE_PERIMETER_PANEL = "enable_perimeter_panel"
CONF_ENABLE_ANNEX_PANEL = "enable_annex_panel"
# Opt-in to continuous background polling of the activity timeline. When off
# (the default) the ActivityCoordinator runs on-demand only — the activity-log
# card drives refreshes while it's on screen, so the integration makes no
# per-minute API calls when nobody's viewing it. When on, the coordinator polls
# every _DEFAULT_ACTIVITY_INTERVAL, which also keeps verisure_owa_activity event
# automations firing even with no card open.
CONF_ENABLE_ACTIVITY_POLLING = "enable_activity_polling"
# Persisted list of API command strings (e.g. "ARMNIGHT1") the panel has
# already rejected at runtime. Hydrated into the CommandResolver on setup
# so a sub-panel mode disabled by a 400 response stays disabled across
# HA restarts — otherwise the user would re-encounter the same failure
# until they manually edited storage.
CONF_UNSUPPORTED_COMMANDS = "unsupported_commands"

DEFAULT_SCAN_INTERVAL = 120
DEFAULT_CODE_ARM_REQUIRED = False
DEFAULT_ENABLE_ACTIVITY_POLLING = False
DEFAULT_FORCE_ARM_NOTIFICATIONS = True
DEFAULT_DELAY_CHECK_OPERATION = 2
DEFAULT_CODE = ""
DEFAULT_COUNTRY = "ES"
API_CACHE_TTL = 60  # seconds — sensor data changes hourly at most

COUNTRY_CODES: list[str] = ["AR", "BR", "CL", "ES", "FR", "GB", "IE", "IT", "PE", "PT"]

PLATFORMS = [
    Platform.ALARM_CONTROL_PANEL,
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.SENSOR,
    Platform.LOCK,
]

SENTINEL_SERVICE_NAMES: frozenset[str] = frozenset({"CONFORT", "COMFORTO", "COMFORT"})

# Lock automations (issue #449) — per-lock auto-lock-on-arm and
# auto-disarm-on-unlock configuration.
CONF_LOCK_AUTOMATIONS = "lock_automations"
CIRCUIT_INTERIOR = "interior"
CIRCUIT_PERIMETER = "perimeter"
CIRCUIT_ANNEX = "annex"
LOCK_CIRCUITS: tuple[str, ...] = (CIRCUIT_INTERIOR, CIRCUIT_PERIMETER, CIRCUIT_ANNEX)
