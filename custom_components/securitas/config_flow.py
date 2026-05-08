"""Placeholder flow handler for the legacy 'securitas' shim.

HA's loader requires a registered ConfigFlow for any persisted entry
(homeassistant/config_entries.py:752-764). Never invoked — `config_flow: false`
hides it from the UI and the shim removes the entry on migration.
Removed in v6.0.0 with the rest of the shim.
"""

from homeassistant import config_entries

from . import DOMAIN


class LegacySecuritasFlowHandler(config_entries.ConfigFlow, domain=DOMAIN):
    """Never invoked; registered only so HA's loader resolves a versioned handler."""

    VERSION = 3
    MINOR_VERSION = 1
