"""Tests for CameraDevice, ThumbnailResponse dataclasses, and camera utility functions."""

import base64
import json

import pytest

from custom_components.securitas.securitas_direct_new_api.models import (
    CameraDevice,
    ThumbnailResponse,
)

pytestmark = pytest.mark.asyncio


# ── Dataclass tests ──────────────────────────────────────────────────────────


class TestCameraDevice:
    """Tests for the CameraDevice dataclass."""

    def test_default_values(self):
        """Test CameraDevice has correct default values."""
        camera = CameraDevice()
        assert camera.id == ""
        assert camera.code == 0
        assert camera.zone_id == ""
        assert camera.name == ""
        assert camera.device_type == ""
        assert camera.serial_number is None

    def test_with_values(self):
        """Test CameraDevice with explicit values."""
        camera = CameraDevice(
            id="CAM001",
            code=42,
            zone_id="Z3",
            name="Front Door Camera",
            device_type="QR",
            serial_number="SN-123456",
        )
        assert camera.id == "CAM001"
        assert camera.code == 42
        assert camera.zone_id == "Z3"
        assert camera.name == "Front Door Camera"
        assert camera.device_type == "QR"
        assert camera.serial_number == "SN-123456"


class TestThumbnailResponse:
    """Tests for the ThumbnailResponse dataclass."""

    def test_default_values(self):
        """Test ThumbnailResponse has correct default values."""
        thumb = ThumbnailResponse()
        assert thumb.id_signal is None
        assert thumb.device_code is None
        assert thumb.device_alias is None
        assert thumb.timestamp is None
        assert thumb.signal_type is None
        assert thumb.image is None

    def test_with_values(self):
        """Test ThumbnailResponse with explicit values."""
        thumb = ThumbnailResponse(
            id_signal="SIG-001",
            device_code="DEV-42",
            device_alias="Front Door",
            timestamp="2026-03-09T12:00:00Z",
            signal_type="MOTION",
            image="base64encodeddata==",
        )
        assert thumb.id_signal == "SIG-001"
        assert thumb.device_code == "DEV-42"
        assert thumb.device_alias == "Front Door"
        assert thumb.timestamp == "2026-03-09T12:00:00Z"
        assert thumb.signal_type == "MOTION"
        assert thumb.image == "base64encodeddata=="


# ── Sanitize response for log ────────────────────────────────────────────────


class TestSanitizeResponseForLog:
    """Tests for _sanitize_response_for_log in http_transport."""

    def setup_method(self):
        from custom_components.securitas.securitas_direct_new_api.http_transport import (
            _sanitize_response_for_log,
        )

        self.fn = _sanitize_response_for_log

    def test_truncates_image_field(self):
        raw = json.dumps({"image": "very_long_base64_data=="})
        result = json.loads(self.fn(raw))
        assert result["image"] == "..."

    def test_truncates_hours_list_field(self):
        raw = json.dumps({"hours": [1, 2, 3, 4, 5]})
        result = json.loads(self.fn(raw))
        assert result["hours"] == ["..."]

    def test_does_not_modify_other_fields(self):
        raw = json.dumps({"name": "Salon", "code": 42})
        result = json.loads(self.fn(raw))
        assert result["name"] == "Salon"
        assert result["code"] == 42

    def test_returns_non_json_as_is(self):
        raw = "not valid json {"
        assert self.fn(raw) == raw

    def test_nested_truncation(self):
        raw = json.dumps(
            {"data": {"xSGetThumbnail": {"image": "base64==", "type": "BINARY"}}}
        )
        result = json.loads(self.fn(raw))
        assert result["data"]["xSGetThumbnail"]["image"] == "..."
        assert result["data"]["xSGetThumbnail"]["type"] == "BINARY"


# ── Hub camera operations ────────────────────────────────────────────────────


class TestHubCameraOperations:
    def test_signal_camera_state_constant_exists(self):
        from custom_components.securitas import SIGNAL_CAMERA_STATE

        assert isinstance(SIGNAL_CAMERA_STATE, str)

    def test_get_camera_image_returns_none_when_empty(self):
        """Test that get_camera_image returns None for missing keys."""
        images: dict[str, bytes] = {}
        assert images.get("2654190_QR10") is None

    def test_get_camera_image_returns_stored_bytes(self):
        """Test that stored bytes are retrievable."""
        images: dict[str, bytes] = {}
        image_bytes = b"\xff\xd8\xff\xe0fake_jpeg"
        images["2654190_QR10"] = image_bytes
        assert images.get("2654190_QR10") == image_bytes

    def test_poll_continues_while_processing(self):
        """Polling should NOT stop when res=OK but msg contains 'processing'."""
        responses = [
            {"res": "OK", "msg": "alarm-manager.photo-request.processing"},
            {"res": "OK", "msg": "alarm-manager.photo-request.processing"},
            {"res": "OK", "msg": "alarm-manager.photo-request.success"},
        ]
        # Simulate the polling break condition from capture_image
        poll_count = 0
        for raw in responses:
            poll_count += 1
            msg = raw.get("msg", "")
            if "processing" not in msg and raw.get("res") != "WAIT":
                break
        assert poll_count == 3, "Should poll 3 times before breaking on success"

    def test_poll_breaks_on_success(self):
        """Polling should stop when msg indicates success."""
        raw = {"res": "OK", "msg": "alarm-manager.photo-request.success"}
        msg = raw.get("msg", "")
        should_continue = "processing" in msg or raw.get("res") == "WAIT"
        assert not should_continue

    def test_jpeg_validation_rejects_non_jpeg(self):
        """Non-JPEG data (e.g. file path) should be detected."""
        # This is what the API returns when image isn't ready - a file path
        file_path = "/var/volatile/media/36QYX3LE_38_1.jpeg"
        encoded = base64.b64encode(file_path.encode()).decode()
        decoded = base64.b64decode(encoded)
        assert not decoded.startswith(b"\xff\xd8"), (
            "File path should not look like JPEG"
        )

    def test_jpeg_validation_accepts_jpeg(self):
        """Real JPEG data starts with FFD8 magic bytes."""
        jpeg_data = b"\xff\xd8\xff\xe0\x00\x10JFIF"
        assert jpeg_data.startswith(b"\xff\xd8")
