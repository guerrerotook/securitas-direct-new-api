"""Lovelace card resource registration for the Verisure OWA cards.

The integration ships three custom Lovelace cards under www/. Each one is
registered as a Lovelace resource (preferred) so it survives HA restarts,
or — if the resources storage isn't available — falls back to
add_extra_js_url for the lifetime of the running session.
"""

from __future__ import annotations

import logging

from homeassistant.components import frontend
from homeassistant.core import HomeAssistant

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
    except (KeyError, Exception):  # pylint: disable=broad-exception-caught
        _LOGGER.debug("[setup] Could not register %s via add_extra_js_url", base_url)


async def _unregister_card_resource(
    hass: HomeAssistant,
    card_url: str,
    storage_key: str,
) -> None:
    """Remove a card Lovelace resource on unload."""
    resource_id = hass.data.get(DOMAIN, {}).get(storage_key)
    if not resource_id:
        try:
            frontend.remove_extra_js_url(hass, card_url)
        except Exception:  # pylint: disable=broad-exception-caught
            pass
        return
    try:
        lovelace_data = hass.data.get("lovelace")
        if lovelace_data and hasattr(lovelace_data, "resources"):
            resources = lovelace_data.resources
            if hasattr(resources, "async_delete_item"):
                await resources.async_delete_item(resource_id)
    except Exception:  # pylint: disable=broad-exception-caught
        _LOGGER.debug("[teardown] Could not remove Lovelace resource %s", resource_id)
