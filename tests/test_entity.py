"""Tests for the shared entity helpers in entity.py."""

from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.securitas import DOMAIN
from custom_components.securitas import entity as entity_mod
from custom_components.securitas.entity import camera_device_info
from custom_components.securitas.verisure_owa_api.models import (
    CameraDevice,
    Installation,
)


def _make_installation():
    return Installation(
        number="100001",
        alias="Home",
        panel="SDVFAST",
        type="PLUS",
        address="123 St",
    )


def _make_camera_device():
    return CameraDevice(
        id="c1",
        code=1,
        zone_id="YR08",
        name="Hall",
        device_type="YR",
        serial_number="sn",
    )


def _register_installation_device(hass) -> tuple[dr.DeviceEntry, str]:
    """Register the installation parent device in the real registry."""
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    device = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={(DOMAIN, "v4_securitas_direct.100001")},
        manufacturer="Verisure",
    )
    return device, entry.entry_id


def test_securitas_device_info_uses_v5_schema():
    from custom_components.securitas.entity import securitas_device_info

    inst = _make_installation()
    info = securitas_device_info(inst)
    assert (DOMAIN, "v4_securitas_direct.100001") in info["identifiers"]
    assert info["manufacturer"] == "Verisure"


def test_camera_device_info_uses_v5_schema():
    inst = _make_installation()
    cam = _make_camera_device()
    info = camera_device_info(inst, cam)
    assert (DOMAIN, "v4_securitas_direct.100001_camera_YR08") in info["identifiers"]
    assert info["via_device"] == (DOMAIN, "v4_securitas_direct.100001")
    assert info["manufacturer"] == "Verisure"


def test_camera_device_info_uses_via_device_when_id_unsupported(monkeypatch):
    """On HA < 2026.8 (no via_device_id), the parent link stays via_device."""
    monkeypatch.setattr(entity_mod, "_SUPPORTS_VIA_DEVICE_ID", False)
    info = camera_device_info(_make_installation(), _make_camera_device())
    assert info["via_device"] == (DOMAIN, "v4_securitas_direct.100001")
    assert "via_device_id" not in info


async def test_camera_device_info_uses_via_device_id_when_supported(hass, monkeypatch):
    """On HA >= 2026.8, link the child by the parent's registry id."""
    monkeypatch.setattr(entity_mod, "_SUPPORTS_VIA_DEVICE_ID", True)
    parent, entry_id = _register_installation_device(hass)
    registry = dr.async_get(hass)
    monkeypatch.setattr(
        type(registry),
        "async_get_device_by_identifier",
        lambda _registry, identifier, owner_entry_id: (
            parent
            if identifier == (DOMAIN, "v4_securitas_direct.100001")
            and owner_entry_id == entry_id
            else None
        ),
        raising=False,
    )
    # via_device_id isn't a defined DeviceInfo key before HA 2026.8; read the
    # DeviceInfo as a plain dict so the assertion type-checks on any core.
    info = dict(
        camera_device_info(
            _make_installation(),
            _make_camera_device(),
            hass,
            config_entry_id=entry_id,
        )
    )
    assert info["via_device_id"] == parent.id
    assert "via_device" not in info


async def test_camera_device_info_falls_back_when_parent_missing(hass, monkeypatch):
    """via_device_id supported but the parent isn't registered yet → keep
    via_device so HA links it exactly as before (no first-setup regression)."""
    monkeypatch.setattr(entity_mod, "_SUPPORTS_VIA_DEVICE_ID", True)
    registry = dr.async_get(hass)
    monkeypatch.setattr(
        type(registry),
        "async_get_device_by_identifier",
        lambda _registry, _identifier, _entry_id: None,
        raising=False,
    )
    info = camera_device_info(
        _make_installation(),
        _make_camera_device(),
        hass,
        config_entry_id="missing-entry",
    )
    assert info["via_device"] == (DOMAIN, "v4_securitas_direct.100001")
    assert "via_device_id" not in info


def test_camera_device_info_without_hass_uses_via_device(monkeypatch):
    """No hass (can't resolve the registry) → keep via_device even on new HA."""
    monkeypatch.setattr(entity_mod, "_SUPPORTS_VIA_DEVICE_ID", True)
    info = camera_device_info(_make_installation(), _make_camera_device(), None)
    assert info["via_device"] == (DOMAIN, "v4_securitas_direct.100001")
    assert "via_device_id" not in info
