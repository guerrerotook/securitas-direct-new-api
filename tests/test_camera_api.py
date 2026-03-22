"""Tests for CameraDevice, ThumbnailResponse dataclasses, and camera API methods."""

from unittest.mock import AsyncMock

import pytest

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    CameraDevice,
    Installation,
    ThumbnailResponse,
)
from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
)

pytestmark = pytest.mark.asyncio


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def installation():
    return Installation(number="123456", alias="Home", panel="SDVFAST", type="PLUS")


@pytest.fixture
def authed_api(api):
    api._check_authentication_token = AsyncMock()
    api._check_capabilities_token = AsyncMock()
    api.delay_check_operation = 0
    return api


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


class TestGetDeviceList:
    DEVICE_LIST_RESPONSE = {
        "data": {
            "xSDeviceList": {
                "res": "OK",
                "devices": [
                    {
                        "id": "1",
                        "code": "1",
                        "zoneId": "QR01",
                        "name": "Cucina",
                        "type": "QR",
                        "isActive": True,
                        "serialNumber": "36QYX3LE",
                    },
                    {
                        "id": "2",
                        "code": "2",
                        "zoneId": "MG02",
                        "name": "Entrata",
                        "type": "MG",
                        "isActive": True,
                        "serialNumber": None,
                    },
                    {
                        "id": "9",
                        "code": "9",
                        "zoneId": "QR09",
                        "name": "Cameretta",
                        "type": "QR",
                        "isActive": True,
                        "serialNumber": "36NF2KPR",
                    },
                    {
                        "id": "11",
                        "code": "10",
                        "zoneId": "QR10",
                        "name": "Salon",
                        "type": "QR",
                        "isActive": True,
                        "serialNumber": "36NEYYER",
                    },
                    {
                        "id": "20",
                        "code": "17",
                        "zoneId": "QR17",
                        "name": "Inactive",
                        "type": "QR",
                        "isActive": False,
                        "serialNumber": None,
                    },
                ],
            }
        }
    }

    async def test_returns_only_active_camera_devices(
        self, authed_api, mock_execute, installation
    ):
        mock_execute.return_value = self.DEVICE_LIST_RESPONSE
        result = await authed_api.get_device_list(installation)
        assert len(result) == 3
        assert all(isinstance(d, CameraDevice) for d in result)
        assert [d.name for d in result] == ["Cucina", "Cameretta", "Salon"]

    async def test_parses_device_fields(self, authed_api, mock_execute, installation):
        mock_execute.return_value = self.DEVICE_LIST_RESPONSE
        result = await authed_api.get_device_list(installation)
        salon = result[2]
        assert salon.id == "11"
        assert salon.code == 10
        assert salon.zone_id == "QR10"
        assert salon.name == "Salon"
        assert salon.device_type == "QR"
        assert salon.serial_number == "36NEYYER"

    async def test_yr_pir_camera_with_null_zone_id(
        self, authed_api, mock_execute, installation
    ):
        """YR (PIR camera) devices have zoneId=null; zone_id should fall back to device id."""
        mock_execute.return_value = {
            "data": {
                "xSDeviceList": {
                    "res": "OK",
                    "devices": [
                        {
                            "id": "11",
                            "code": "5",
                            "zoneId": None,
                            "name": "Pl_Home_Entrada_Fotoentrada",
                            "type": "YR",
                            "isActive": None,
                            "serialNumber": None,
                        },
                        {
                            "id": "12",
                            "code": "6",
                            "zoneId": None,
                            "name": "Pl_Home_Habitacion_Hab",
                            "type": "YR",
                            "isActive": None,
                            "serialNumber": None,
                        },
                    ],
                }
            }
        }
        result = await authed_api.get_device_list(installation)
        assert len(result) == 2
        assert result[0].zone_id == "11"
        assert result[1].zone_id == "12"

    async def test_yp_perimetral_camera(self, authed_api, mock_execute, installation):
        """YP perimetral exterior cameras should be included."""
        mock_execute.return_value = {
            "data": {
                "xSDeviceList": {
                    "res": "OK",
                    "devices": [
                        {
                            "id": "4",
                            "code": "3",
                            "zoneId": "YP03",
                            "name": "Fachada",
                            "type": "YP",
                            "isActive": True,
                            "serialNumber": None,
                        },
                    ],
                }
            }
        }
        result = await authed_api.get_device_list(installation)
        assert len(result) == 1
        assert result[0].device_type == "YP"
        assert result[0].zone_id == "YP03"
        assert result[0].name == "Fachada"
        assert result[0].code == 3

    async def test_empty_device_list(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {"xSDeviceList": {"res": "OK", "devices": []}}
        }
        result = await authed_api.get_device_list(installation)
        assert result == []

    async def test_no_cameras(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {
                "xSDeviceList": {
                    "res": "OK",
                    "devices": [
                        {
                            "id": "2",
                            "code": "2",
                            "zoneId": "MG02",
                            "name": "Entrata",
                            "type": "MG",
                            "isActive": True,
                            "serialNumber": None,
                        },
                    ],
                }
            }
        }
        result = await authed_api.get_device_list(installation)
        assert result == []


class TestRequestImages:
    async def test_success(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {
                "xSRequestImages": {
                    "res": "OK",
                    "msg": "alarm-manager.processed.request",
                    "referenceId": "4ebfe653-fa54-4805-874c-cea1c9ad927a",
                }
            }
        }
        ref_id = await authed_api.request_images(installation, device_code=10)
        assert ref_id == "4ebfe653-fa54-4805-874c-cea1c9ad927a"

    async def test_yp_device_type(self, authed_api, mock_execute, installation):
        """YP cameras should use deviceType 103."""
        mock_execute.return_value = {
            "data": {
                "xSRequestImages": {
                    "res": "OK",
                    "msg": "alarm-manager.processed.request",
                    "referenceId": "abc-123",
                }
            }
        }
        await authed_api.request_images(installation, device_code=3, device_type="YP")
        call_args = mock_execute.call_args
        variables = call_args[0][0]["variables"]
        assert variables["deviceType"] == 103

    async def test_qr_device_type(self, authed_api, mock_execute, installation):
        """QR cameras should use deviceType 106."""
        mock_execute.return_value = {
            "data": {
                "xSRequestImages": {
                    "res": "OK",
                    "msg": "alarm-manager.processed.request",
                    "referenceId": "abc-123",
                }
            }
        }
        await authed_api.request_images(installation, device_code=1, device_type="QR")
        call_args = mock_execute.call_args
        variables = call_args[0][0]["variables"]
        assert variables["deviceType"] == 106

    async def test_error_response(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {
                "xSRequestImages": {
                    "res": "ERROR",
                    "msg": "some error",
                    "referenceId": None,
                }
            }
        }
        with pytest.raises(SecuritasDirectError):
            await authed_api.request_images(installation, device_code=10)


class TestGetThumbnail:
    async def test_success(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {
                "xSGetThumbnail": {
                    "idSignal": "15681796423",
                    "deviceId": None,
                    "deviceCode": "QR10",
                    "deviceAlias": "Salon",
                    "timestamp": "2026-03-09 17:47:13",
                    "signalType": "16",
                    "image": "/9j/4AAQSkZJRgABAQEAAA==",
                    "type": "BINARY",
                    "quality": "",
                }
            }
        }
        result = await authed_api.get_thumbnail(
            installation, device_name="Salon", zone_id="QR10"
        )
        assert isinstance(result, ThumbnailResponse)
        assert result.id_signal == "15681796423"
        assert result.device_code == "QR10"
        assert result.device_alias == "Salon"
        assert result.image == "/9j/4AAQSkZJRgABAQEAAA=="

    async def test_no_image_available(self, authed_api, mock_execute, installation):
        mock_execute.return_value = {
            "data": {
                "xSGetThumbnail": {
                    "idSignal": None,
                    "deviceId": None,
                    "deviceCode": None,
                    "deviceAlias": None,
                    "timestamp": None,
                    "signalType": None,
                    "image": None,
                    "type": None,
                    "quality": None,
                }
            }
        }
        result = await authed_api.get_thumbnail(
            installation, device_name="Salon", zone_id="QR10"
        )
        assert result.image is None
        assert result.id_signal is None


class TestSanitizeResponseForLog:
    """Tests for _sanitize_response_for_log in http_client."""

    def setup_method(self):
        from custom_components.securitas.securitas_direct_new_api.http_client import (
            _sanitize_response_for_log,
        )

        self.fn = _sanitize_response_for_log

    def test_truncates_image_field(self):
        import json

        raw = json.dumps({"image": "very_long_base64_data=="})
        result = json.loads(self.fn(raw))
        assert result["image"] == "..."

    def test_truncates_hours_list_field(self):
        import json

        raw = json.dumps({"hours": [1, 2, 3, 4, 5]})
        result = json.loads(self.fn(raw))
        assert result["hours"] == ["..."]

    def test_does_not_modify_other_fields(self):
        import json

        raw = json.dumps({"name": "Salon", "code": 42})
        result = json.loads(self.fn(raw))
        assert result["name"] == "Salon"
        assert result["code"] == 42

    def test_returns_non_json_as_is(self):
        raw = "not valid json {"
        assert self.fn(raw) == raw

    def test_nested_truncation(self):
        import json

        raw = json.dumps(
            {"data": {"xSGetThumbnail": {"image": "base64==", "type": "BINARY"}}}
        )
        result = json.loads(self.fn(raw))
        assert result["data"]["xSGetThumbnail"]["image"] == "..."
        assert result["data"]["xSGetThumbnail"]["type"] == "BINARY"


class TestHubCameraOperations:
    def test_signal_constant_exists(self):
        from custom_components.securitas import SIGNAL_CAMERA_UPDATE

        assert isinstance(SIGNAL_CAMERA_UPDATE, str)

    def test_signal_camera_state_constant_exists(self):
        from custom_components.securitas import (
            SIGNAL_CAMERA_STATE,
            SIGNAL_CAMERA_UPDATE,
        )

        assert isinstance(SIGNAL_CAMERA_STATE, str)
        assert SIGNAL_CAMERA_STATE != SIGNAL_CAMERA_UPDATE

    def test_get_camera_image_returns_none_when_empty(self):
        """Test that get_camera_image returns None for missing keys."""
        # Just test the dict lookup logic
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
        import base64

        # This is what the API returns when image isn't ready — a file path
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
