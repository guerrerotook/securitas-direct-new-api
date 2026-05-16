"""Migration logic from the legacy 'securitas' domain to 'verisure_owa'.

Run by the shim integration (custom_components/securitas/__init__.py) on
first load after the user upgrades to v5. Idempotent: re-running it on an
already-migrated entry is a no-op.
"""

from __future__ import annotations

import inspect
import logging
from types import MappingProxyType
from typing import Any

from homeassistant.config_entries import ConfigEntry, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import device_registry as dr, entity_registry as er

_LOGGER = logging.getLogger(__name__)

LEGACY_DOMAIN = "securitas"
NEW_DOMAIN = "verisure_owa"

V4_PREFIX = "v4_"
V4_PREFIX_BRANDED = "v4_securitas_direct."
V5_PREFIX = "v5_verisure_owa."

_MIGRATION_FLAG = "migrated_from_securitas"
_SCHEMA_FLAG = "unique_id_schema"
_SCHEMA_VALUE = "v5_verisure_owa"


def old_to_new_unique_id(old: str) -> str:
    """Map a legacy unique_id to the v5_verisure_owa.* form.

    Handles all entity formats from v4. Idempotent on already-v5 inputs.
    Raises ValueError on inputs that don't match any known format.
    """
    if old.startswith(V5_PREFIX):
        return old

    if old.startswith(V4_PREFIX_BRANDED):
        # v4_securitas_direct.{rest} → v5_verisure_owa.{rest}
        return V5_PREFIX + old[len(V4_PREFIX_BRANDED) :]

    # v4_refresh_button_{numinst} → v5_verisure_owa.{numinst}_refresh_button
    if old.startswith("v4_refresh_button_"):
        numinst = old[len("v4_refresh_button_") :]
        return f"{V5_PREFIX}{numinst}_refresh_button"

    if old.startswith(V4_PREFIX):
        # v4_{rest} → v5_verisure_owa.{rest}
        return V5_PREFIX + old[len(V4_PREFIX) :]

    raise ValueError(f"Unrecognized legacy unique_id format: {old!r}")


def old_to_new_identifier(identifier: tuple[str, str]) -> tuple[str, str]:
    """Map a device-registry identifier tuple to the new domain + new id.

    Identifiers under an unrelated domain are returned unchanged.
    """
    domain, id_ = identifier
    if domain == NEW_DOMAIN:
        return identifier  # already migrated
    if domain != LEGACY_DOMAIN:
        return identifier  # not ours
    return (NEW_DOMAIN, old_to_new_unique_id(id_))


async def migrate_legacy_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Migrate a legacy 'securitas' config entry to 'verisure_owa'.

    Steps:
    1. Idempotency check — early-exit if a verisure_owa entry already
       exists for this entry's unique_id.
    2. Pre-validate — compute every old→new mapping up-front and abort
       cleanly (without touching any registry) if any input is in an
       unrecognised format.  Without this, a mid-loop ValueError would
       leave registries partially mutated and the rollback below
       (which only unregisters the new config entry) couldn't restore
       them.
    3. Create a new ConfigEntry under 'verisure_owa' with the same data,
       options, title, unique_id, version, plus migration-marker flags.
    4. Re-platform entity registry FIRST: apply the pre-validated
       unique_id rewrites and re-attach entities to the new entry.
       Done before step 5 because async_update_device fires
       device_registry_updated whose listener removes entities still
       tied to the old entry id.
    5. Re-platform device registry: apply the pre-validated identifier
       rewrites and re-attach devices to the new entry.
    """
    if entry.domain != LEGACY_DOMAIN:
        _LOGGER.error(
            "migrate_legacy_entry called with non-legacy entry %s (domain=%s)",
            entry.entry_id,
            entry.domain,
        )
        return

    # 1. Idempotency: skip if a verisure_owa entry already exists for same unique_id
    existing = [
        e
        for e in hass.config_entries.async_entries(NEW_DOMAIN)
        if e.unique_id == entry.unique_id
    ]
    if existing:
        _LOGGER.info(
            "Skipping migration for %s — verisure_owa entry %s already exists",
            entry.entry_id,
            existing[0].entry_id,
        )
        return

    # 2. Pre-validate.  If any unique_id or device-identifier in this entry's
    # registries has an unrecognised format, old_to_new_unique_id raises
    # ValueError.  Failing here — before any registry mutation — leaves
    # registries untouched, so the user can fix the bad entry, retry, and
    # nothing has been corrupted.  Without this pass, a mid-loop ValueError
    # would leave entities/devices partially migrated; the rollback below
    # only unregisters the new config entry and can't restore the registry
    # mutations that already happened.
    pre_ent_reg = er.async_get(hass)
    pre_dev_reg = dr.async_get(hass)
    entity_id_map: dict[str, str] = {}
    for ent in pre_ent_reg.entities.values():
        if ent.config_entry_id != entry.entry_id:
            continue
        try:
            entity_id_map[ent.entity_id] = old_to_new_unique_id(ent.unique_id)
        except ValueError as exc:
            raise ConfigEntryError(
                f"Cannot migrate entry {entry.entry_id}: entity {ent.entity_id} "
                f"has unique_id {ent.unique_id!r} in an unrecognised format. "
                f"No registry changes have been applied."
            ) from exc
    device_id_map: dict[str, set[tuple[str, str]]] = {}
    for device in pre_dev_reg.devices.values():
        if entry.entry_id not in device.config_entries:
            continue
        old_ids = {(d, i) for d, i in device.identifiers if d == LEGACY_DOMAIN}
        if not old_ids:
            continue
        try:
            device_id_map[device.id] = {
                old_to_new_identifier(ident) if ident in old_ids else ident
                for ident in device.identifiers
            }
        except ValueError as exc:
            raise ConfigEntryError(
                f"Cannot migrate entry {entry.entry_id}: device {device.id} "
                f"has identifiers {device.identifiers!r} in an unrecognised format. "
                f"No registry changes have been applied."
            ) from exc

    # 3. Create new entry under verisure_owa with migration flags in data
    new_data = {
        **dict(entry.data),
        _MIGRATION_FLAG: True,
        _SCHEMA_FLAG: _SCHEMA_VALUE,
    }
    # discovery_keys on a real entry is a MappingProxyType; on a MockConfigEntry it
    # may be a plain dict — normalise to MappingProxyType for the constructor.
    raw_discovery_keys = getattr(entry, "discovery_keys", None) or {}
    if not isinstance(raw_discovery_keys, MappingProxyType):
        raw_discovery_keys = MappingProxyType(raw_discovery_keys)

    # subentries_data was added in HA 2025.x; older HA cores reject it as
    # an unexpected kwarg.  Only pass it when the running HA version accepts it.
    config_entry_kwargs: dict[str, Any] = {
        "version": entry.version,
        "minor_version": getattr(entry, "minor_version", 1),
        "domain": NEW_DOMAIN,
        "title": entry.title,
        "data": new_data,
        "options": dict(entry.options),
        "source": getattr(entry, "source", SOURCE_USER),
        "unique_id": entry.unique_id,
        "discovery_keys": raw_discovery_keys,
    }
    if "subentries_data" in inspect.signature(ConfigEntry).parameters:
        config_entry_kwargs["subentries_data"] = None
    # pylint thinks subentries_data is mandatory (since we test against a HA
    # version that defines it), but it's added conditionally above for older
    # HA versions that don't accept it.  Disable just for this call.
    new_entry = ConfigEntry(**config_entry_kwargs)  # pylint: disable=missing-kwoa
    # Register the new entry directly, without triggering async_setup.
    # Using _entries is intentional: async_add() calls async_setup(), which
    # would attempt to authenticate immediately during migration — before the
    # shim has finished and before HA has a chance to fully start the new
    # domain.  We want HA to discover and set up the new entry naturally on the
    # next boot, exactly as it does after a fresh config-flow installation.
    # MockConfigEntry.add_to_hass() uses the same pattern (it writes to
    # _entries directly), so this is the accepted HA test-infrastructure idiom.
    # pylint: disable=protected-access
    hass.config_entries._entries[new_entry.entry_id] = new_entry  # noqa: SLF001
    hass.config_entries._async_schedule_save()  # noqa: SLF001
    # pylint: enable=protected-access

    try:
        # 4. Re-platform entity registry FIRST.
        # Entities must be moved to the new config entry BEFORE the device update
        # (step 5), because async_update_device fires a device_registry_updated
        # event. The entity-registry listener on that event removes entities whose
        # config_entry_id is in `changes["config_entries"]` (the old value) but
        # no longer in the device's current config_entries. Moving entities first
        # ensures they are already under new_entry.entry_id when the event fires,
        # so the listener correctly keeps them.
        ent_reg = er.async_get(hass)
        for entity_id, new_unique_id in entity_id_map.items():
            # async_update_entity_platform atomically updates platform, config_entry_id,
            # and unique_id while preserving all user customizations (name, area_id, etc.)
            ent_reg.async_update_entity_platform(
                entity_id,
                NEW_DOMAIN,
                new_config_entry_id=new_entry.entry_id,
                new_unique_id=new_unique_id,
            )

        # 5. Re-platform device registry
        dev_reg = dr.async_get(hass)
        for device_id, new_ids in device_id_map.items():
            dev_reg.async_update_device(
                device_id,
                new_identifiers=new_ids,
                add_config_entry_id=new_entry.entry_id,
                remove_config_entry_id=entry.entry_id,
            )

    except Exception as exc:  # noqa: BLE001
        _LOGGER.error(
            "Migration of entry %s (unique_id=%s) failed — rolling back: %s",
            entry.entry_id,
            entry.unique_id,
            exc,
            exc_info=True,
        )
        # Roll back: remove the partially-registered new entry so subsequent
        # runs don't see it and early-exit via the idempotency check.
        # pylint: disable=protected-access
        hass.config_entries._entries.pop(new_entry.entry_id, None)  # noqa: SLF001
        hass.config_entries._async_schedule_save()  # noqa: SLF001
        # pylint: enable=protected-access
        raise ConfigEntryError(
            f"Migration from securitas entry {entry.entry_id} failed: {exc}"
        ) from exc

    _LOGGER.info(
        "Migrated legacy entry %s to verisure_owa entry %s",
        entry.entry_id,
        new_entry.entry_id,
    )
