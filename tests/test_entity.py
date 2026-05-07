"""Tests for the shared entity helpers in entity.py."""

from custom_components.verisure_owa.verisure_owa_api.models import (
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


def test_securitas_device_info_uses_v5_schema():
    from custom_components.verisure_owa import DOMAIN
    from custom_components.verisure_owa.entity import securitas_device_info

    inst = _make_installation()
    info = securitas_device_info(inst)
    assert (DOMAIN, "v5_verisure_owa.100001") in info["identifiers"]
    assert info["manufacturer"] == "Verisure"


def test_camera_device_info_uses_v5_schema():
    from custom_components.verisure_owa import DOMAIN
    from custom_components.verisure_owa.entity import camera_device_info

    inst = _make_installation()
    cam = _make_camera_device()
    info = camera_device_info(inst, cam)
    assert (DOMAIN, "v5_verisure_owa.100001_camera_YR08") in info["identifiers"]
    assert info["via_device"] == (DOMAIN, "v5_verisure_owa.100001")
    assert info["manufacturer"] == "Verisure"
