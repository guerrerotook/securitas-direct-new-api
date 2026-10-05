"""Lovelace card resource registration for the Verisure OWA cards.

The integration ships several custom Lovelace card modules under www/ (the
alarm card, the lightweight alarm chip/badge/Tile feature, the camera card, and the
activity-log card). Each one is
registered as a Lovelace resource (preferred) so it survives HA restarts,
or — if the resources storage isn't available — falls back to
add_extra_js_url for the lifetime of the running session. The More Info
module is instead loaded on every page with add_extra_js_url (by
_register_page_module, which also deletes the Lovelace resource earlier
versions registered for it), because HA loads Lovelace resources only on
dashboards.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # HA 2026.9+ runs voluptuous as probatio; 2026.10+ types its APIs with probatio's classes.
    import probatio as vol
else:
    import voluptuous as vol
from homeassistant.components import frontend
from homeassistant.components.websocket_api import async_register_command
from homeassistant.components.websocket_api.connection import ActiveConnection
from homeassistant.components.websocket_api.decorators import websocket_command
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def _register_card_resource(
    hass: HomeAssistant,
    base_url: str,
    card_url: str,
    storage_key: str,
) -> None:
    """Register a card JS file as a Lovelace resource.

    Falls back to add_extra_js_url if Lovelace resources are unavailable.
    ``storage_key`` is used to track the resource ID in hass.data[DOMAIN].
    """
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data and hasattr(lovelace_data, "resources"):
            resources = lovelace_data.resources
            if hasattr(resources, "async_create_item"):
                if not resources.loaded:
                    await resources.async_load()
                    resources.loaded = True
                for item in resources.async_items():
                    url = item.get("url", "")
                    if url == card_url:
                        return  # Already current version
                    if url.startswith(base_url):
                        await resources.async_update_item(item["id"], {"url": card_url})
                        hass.data.setdefault(DOMAIN, {})[storage_key] = item["id"]
                        return
                item = await resources.async_create_item(
                    {"res_type": "module", "url": card_url}
                )
                hass.data.setdefault(DOMAIN, {})[storage_key] = item["id"]
                return
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGGER.debug(
            "[setup] Could not register %s as Lovelace resource, falling back to add_extra_js_url",
            base_url,
        )
    try:
        frontend.add_extra_js_url(hass, card_url)
    except Exception:  # pylint: disable=broad-exception-caught
        # Both the Lovelace-resource registration AND this fallback failed, so
        # the module never loads and the UI silently breaks — surface it.
        _LOGGER.warning("[setup] Could not register %s via add_extra_js_url", base_url)


async def _register_page_module(
    hass: HomeAssistant, base_url: str, module_url: str
) -> None:
    """Load a module on every frontend page, not only on dashboards.

    Also removes the Lovelace resource earlier versions registered for it.
    The module must define its elements only once HA's own ``home-assistant``
    element exists: it can run before HA replaces ``window.customElements``.
    """
    try:
        resources = getattr(hass.data.get("lovelace"), "resources", None)
        if resources is not None and hasattr(resources, "async_delete_item"):
            if not resources.loaded:
                await resources.async_load()
                resources.loaded = True
            for item in resources.async_items():
                if item.get("url", "").startswith(base_url):
                    await resources.async_delete_item(item["id"])
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGGER.debug("[setup] Could not remove the Lovelace resource %s", base_url)
    try:
        frontend.add_extra_js_url(hass, module_url)
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGGER.warning("[setup] Could not register %s via add_extra_js_url", base_url)


def _unregister_page_module(hass: HomeAssistant, module_url: str) -> None:
    """Stop loading a module registered by ``_register_page_module``."""
    with contextlib.suppress(Exception):
        frontend.remove_extra_js_url(hass, module_url)


async def _unregister_card_resource(
    hass: HomeAssistant,
    card_url: str,
    storage_key: str,
) -> None:
    """Remove a card Lovelace resource on unload."""
    resource_id = hass.data.get(DOMAIN, {}).get(storage_key)
    if not resource_id:
        with contextlib.suppress(Exception):
            frontend.remove_extra_js_url(hass, card_url)
        return
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data and hasattr(lovelace_data, "resources"):
            resources = lovelace_data.resources
            if hasattr(resources, "async_delete_item"):
                await resources.async_delete_item(resource_id)
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGGER.debug("[teardown] Could not remove Lovelace resource %s", resource_id)


DEPRECATION_DOCS_URL = (
    "https://github.com/guerrerotook/securitas-direct-new-api"
    "#replacing-the-deprecated-alarm-card-badge-and-chip"
)
_DEPRECATED_ELEMENTS = {
    "card": (
        "alarm card",
        "Home Assistant's Tile card with the Verisure OWA Open Sensors feature, "
        "or its Alarm panel card",
    ),
    "badge": ("alarm badge", "Home Assistant's own Entity badge"),
    "chip": ("Mushroom alarm chip", "Mushroom's own alarm control panel chip"),
}
# Kept outside ``hass.data[DOMAIN]``, which the clean-up discards, so the
# once-per-run record survives it.
_REPORTED_KEY = f"{DOMAIN}_deprecated_elements_reported"


@callback
def async_register_deprecation_command(hass: HomeAssistant) -> None:
    """Let the deprecated dashboard elements report where they are used."""
    async_register_command(hass, _ws_deprecated_element)


@websocket_command(
    {
        vol.Required("type"): "verisure_owa/deprecated_element",
        vol.Required("element"): vol.In(_DEPRECATED_ELEMENTS),
        vol.Optional("dashboard", default=""): vol.All(str, vol.Length(max=100)),
    }
)
@callback
def _ws_deprecated_element(
    hass: HomeAssistant,
    connection: ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Log a warning once per element and dashboard that it is deprecated."""
    reported: set[tuple[str, str]] = hass.data.setdefault(_REPORTED_KEY, set())
    key = (msg["element"], msg["dashboard"])
    if key not in reported:
        reported.add(key)
        name, replacement = _DEPRECATED_ELEMENTS[msg["element"]]
        where = f"dashboard /{msg['dashboard']}" if msg["dashboard"] else "a dashboard"
        _LOGGER.warning(
            "The Verisure OWA %s used on %s is deprecated and will be removed in "
            "a future release. Replace it with %s: %s",
            name,
            where,
            replacement,
            DEPRECATION_DOCS_URL,
        )
    connection.send_result(msg["id"])
