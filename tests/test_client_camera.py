"""Tests for SecuritasClient camera methods."""

from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from custom_components.securitas.securitas_direct_new_api.client import (
    SecuritasClient,
)
from custom_components.securitas.securitas_direct_new_api.http_transport import (
    HttpTransport,
)
from custom_components.securitas.securitas_direct_new_api.models import (
    CameraDevice,
    Installation,
    ThumbnailResponse,
)

pytestmark = pytest.mark.asyncio

# ── JWT helpers ──────────────────────────────────────────────────────────────

SECRET = "test-secret"


def make_jwt(exp_minutes: int = 15, **extra_claims) -> str:
    """Create a real HS256 JWT with a known expiry."""
    exp = datetime.now(tz=timezone.utc) + timedelta(minutes=exp_minutes)
    payload = {"exp": exp, "sub": "test-user", **extra_claims}
    return jwt.encode(payload, SECRET, algorithm="HS256")


FAKE_JWT = make_jwt(exp_minutes=15)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_installation(**overrides) -> Installation:
    """Factory for Installation with sensible defaults."""
    defaults = {
        "number": "123456",
        "alias": "Home",
        "panel": "SDVFAST",
        "type": "PLUS",
        "name": "John",
        "last_name": "Doe",
        "address": "123 St",
        "city": "Madrid",
        "postal_code": "28001",
        "province": "Madrid",
        "email": "test@example.com",
        "phone": "555-1234",
    }
    defaults.update(overrides)
    return Installation(**defaults)


def _pre_auth(client: SecuritasClient) -> None:
    """Set up a valid auth token so _ensure_auth is a no-op."""
    client.authentication_token = FAKE_JWT
    client._authentication_token_exp = datetime.now() + timedelta(hours=1)
    client.get_services = AsyncMock(return_value=[])


# ── Response builders ────────────────────────────────────────────────────────


def device_list_response(devices: list[dict] | None = None) -> dict:
    """Build a mock xSDeviceList response."""
    return {
        "data": {
            "xSDeviceList": {
                "res": "OK",
                "devices": devices,
            }
        }
    }


def request_images_response(reference_id: str = "ref-img-001") -> dict:
    """Build a mock xSRequestImages response."""
    return {
        "data": {
            "xSRequestImages": {
                "res": "OK",
                "msg": "",
                "referenceId": reference_id,
            }
        }
    }


def request_images_status_response(
    *, res: str = "OK", msg: str = "", status: str = "COMPLETED"
) -> dict:
    """Build a mock xSRequestImagesStatus response."""
    return {
        "data": {
            "xSRequestImagesStatus": {
                "res": res,
                "msg": msg,
                "numinst": "123456",
                "status": status,
            }
        }
    }


def thumbnail_response(
    *,
    id_signal: str | None = "sig-001",
    device_code: str = "01",
    device_alias: str = "Camera 1",
    timestamp: str = "2024-01-01T12:00:00",
    signal_type: str = "IMG",
    image: str | None = "base64imagedata",
) -> dict:
    """Build a mock xSGetThumbnail response."""
    return {
        "data": {
            "xSGetThumbnail": {
                "idSignal": id_signal,
                "deviceCode": device_code,
                "deviceAlias": device_alias,
                "timestamp": timestamp,
                "signalType": signal_type,
                "image": image,
                "type": "THUMBNAIL",
                "quality": "HIGH",
            }
        }
    }


def photo_images_response(
    devices: list[dict] | None = None,
) -> dict:
    """Build a mock xSGetPhotoImages response."""
    return {
        "data": {
            "xSGetPhotoImages": {
                "devices": devices,
            }
        }
    }


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def transport():
    """Create a mock HttpTransport."""
    mock = MagicMock(spec=HttpTransport)
    mock.execute = AsyncMock()
    return mock


@pytest.fixture
def client(transport):
    """Create a SecuritasClient with test credentials, mocked transport, fast polling."""
    c = SecuritasClient(
        transport=transport,
        country="ES",
        language="es",
        username="test@example.com",
        password="test-password",
        device_id="test-device-id",
        uuid="test-uuid",
        id_device_indigitall="test-indigitall",
        poll_delay=0.0,
        poll_timeout=2.0,
    )
    _pre_auth(c)
    return c


# ── get_camera_devices tests ─────────────────────────────────────────────────


class TestGetCameraDevices:
    async def test_returns_filtered_camera_list(self, client, transport):
        """Only QR, YR, YP, QP active devices are returned."""
        transport.execute.return_value = device_list_response(
            devices=[
                {
                    "id": "1",
                    "code": "1",
                    "zoneId": "QR01",
                    "name": "Front Camera",
                    "type": "QR",
                    "isActive": True,
                    "serialNumber": "SN001",
                },
                {
                    "id": "2",
                    "code": "2",
                    "zoneId": "YR02",
                    "name": "Back Camera",
                    "type": "YR",
                    "isActive": True,
                    "serialNumber": "SN002",
                },
                {
                    "id": "3",
                    "code": "3",
                    "zoneId": "DR01",
                    "name": "Front Door Lock",
                    "type": "DR",
                    "isActive": True,
                    "serialNumber": "SN003",
                },
                {
                    "id": "4",
                    "code": "4",
                    "zoneId": "QR04",
                    "name": "Inactive Camera",
                    "type": "QR",
                    "isActive": False,
                    "serialNumber": "SN004",
                },
            ]
        )

        inst = _make_installation()
        result = await client.get_camera_devices(inst)

        assert len(result) == 2
        assert all(isinstance(d, CameraDevice) for d in result)
        assert result[0].name == "Front Camera"
        assert result[0].device_type == "QR"
        assert result[1].name == "Back Camera"
        assert result[1].device_type == "YR"

    async def test_empty_devices_list(self, client, transport):
        """Returns empty list when no devices match."""
        transport.execute.return_value = device_list_response(devices=[])

        inst = _make_installation()
        result = await client.get_camera_devices(inst)

        assert result == []

    async def test_none_devices(self, client, transport):
        """Returns empty list when devices is None."""
        transport.execute.return_value = device_list_response(devices=None)

        inst = _make_installation()
        result = await client.get_camera_devices(inst)

        assert result == []


# ── capture_image tests ──────────────────────────────────────────────────────


class TestCaptureImage:
    async def test_full_flow(self, client, transport):
        """baseline -> submit -> poll status -> poll thumbnail -> new thumbnail."""
        transport.execute.side_effect = [
            # 1. Baseline thumbnail
            thumbnail_response(id_signal="old-sig"),
            # 2. Submit capture request
            request_images_response("ref-img-001"),
            # 3. Poll status: still processing
            request_images_status_response(res="WAIT", msg="processing image"),
            # 4. Poll status: done
            request_images_status_response(res="OK", msg="completed"),
            # 5. Poll thumbnail: still old
            thumbnail_response(id_signal="old-sig"),
            # 6. Poll thumbnail: updated!
            thumbnail_response(id_signal="new-sig", image="new-image-data"),
        ]

        inst = _make_installation()
        result = await client.capture_image(inst, 1, "QR", "QR01")

        assert isinstance(result, ThumbnailResponse)
        assert result.id_signal == "new-sig"
        assert result.image == "new-image-data"

    async def test_timeout_returns_last_thumbnail(self, client, transport):
        """When capture times out, returns the last available thumbnail."""
        call_count = 0

        async def _side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                # Baseline thumbnail
                return thumbnail_response(id_signal="old-sig")
            if call_count == 2:
                # Submit capture request
                return request_images_response("ref-img-001")
            # All subsequent calls: status still processing
            return request_images_status_response(res="WAIT", msg="processing image")

        transport.execute.side_effect = _side_effect

        inst = _make_installation()
        # Use a very short timeout so it triggers quickly
        result = await client.capture_image(inst, 1, "QR", "QR01", capture_timeout=0.1)

        # Should return the baseline thumbnail since nothing updated
        assert isinstance(result, ThumbnailResponse)
        assert result.id_signal == "old-sig"


# ── get_thumbnail tests ──────────────────────────────────────────────────────


class TestGetThumbnail:
    async def test_returns_thumbnail_response(self, client, transport):
        """Successful call returns ThumbnailResponse."""
        transport.execute.return_value = thumbnail_response(
            id_signal="sig-100",
            device_code="01",
            device_alias="Camera 1",
            timestamp="2024-06-15T10:30:00",
            signal_type="IMG",
            image="base64imagedata",
        )

        inst = _make_installation()
        result = await client.get_thumbnail(inst, "QR", "QR01")

        assert isinstance(result, ThumbnailResponse)
        assert result.id_signal == "sig-100"
        assert result.device_alias == "Camera 1"
        assert result.image == "base64imagedata"


# ── get_full_image tests ─────────────────────────────────────────────────────


class TestGetFullImage:
    async def test_returns_jpeg_bytes(self, client, transport):
        """Selects the largest BINARY image and returns decoded JPEG bytes."""
        # Create a valid JPEG (starts with 0xFF 0xD8)
        jpeg_data = b"\xff\xd8\xff\xe0" + b"\x00" * 100
        encoded = base64.b64encode(jpeg_data).decode()
        small_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 10
        small_encoded = base64.b64encode(small_jpeg).decode()

        transport.execute.return_value = photo_images_response(
            devices=[
                {
                    "id": "1",
                    "idSignal": "sig-100",
                    "code": "01",
                    "name": "Camera 1",
                    "quality": "HIGH",
                    "images": [
                        {"id": "img-1", "image": small_encoded, "type": "BINARY"},
                        {"id": "img-2", "image": encoded, "type": "BINARY"},
                        {"id": "img-3", "image": "thumbnail-data", "type": "THUMBNAIL"},
                    ],
                }
            ]
        )

        inst = _make_installation()
        result = await client.get_full_image(inst, "sig-100", "IMG")

        assert result is not None
        assert result == jpeg_data
        assert result[:2] == b"\xff\xd8"

    async def test_returns_none_for_no_devices(self, client, transport):
        """Returns None when no devices in response."""
        transport.execute.return_value = photo_images_response(devices=[])

        inst = _make_installation()
        result = await client.get_full_image(inst, "sig-100", "IMG")

        assert result is None

    async def test_returns_none_for_no_binary_images(self, client, transport):
        """Returns None when no BINARY type images found."""
        transport.execute.return_value = photo_images_response(
            devices=[
                {
                    "id": "1",
                    "idSignal": "sig-100",
                    "code": "01",
                    "name": "Camera 1",
                    "quality": "HIGH",
                    "images": [
                        {"id": "img-1", "image": "thumb-data", "type": "THUMBNAIL"},
                    ],
                }
            ]
        )

        inst = _make_installation()
        result = await client.get_full_image(inst, "sig-100", "IMG")

        assert result is None

    async def test_returns_none_for_invalid_jpeg(self, client, transport):
        """Returns None when decoded data is not valid JPEG."""
        non_jpeg_data = b"\x89PNG" + b"\x00" * 100  # PNG header instead of JPEG
        encoded = base64.b64encode(non_jpeg_data).decode()

        transport.execute.return_value = photo_images_response(
            devices=[
                {
                    "id": "1",
                    "idSignal": "sig-100",
                    "code": "01",
                    "name": "Camera 1",
                    "quality": "HIGH",
                    "images": [
                        {"id": "img-1", "image": encoded, "type": "BINARY"},
                    ],
                }
            ]
        )

        inst = _make_installation()
        result = await client.get_full_image(inst, "sig-100", "IMG")

        assert result is None

    async def test_returns_none_for_none_devices(self, client, transport):
        """Returns None when devices list is None."""
        transport.execute.return_value = photo_images_response(devices=None)

        inst = _make_installation()
        result = await client.get_full_image(inst, "sig-100", "IMG")

        assert result is None
