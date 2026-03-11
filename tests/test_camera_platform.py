"""Tests for camera platform entities."""

import pytest
from unittest.mock import MagicMock, AsyncMock

from custom_components.securitas.securitas_direct_new_api.dataTypes import (
    CameraDevice,
)
from custom_components.securitas.securitas_direct_new_api import Installation


@pytest.fixture
def installation():
    return Installation(number="2654190", panel="SDVECU", alias="Casa")


@pytest.fixture
def camera_device():
    return CameraDevice(
        id="11", code=10, zone_id="QR10", name="Salon", serial_number="36NEYYER"
    )


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.camera_images = {}
    hub.get_camera_image = MagicMock(return_value=None)
    hub.fetch_latest_thumbnail = AsyncMock()
    return hub


class TestSecuritasCamera:
    def test_unique_id(self, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        assert cam.unique_id == "v4_2654190_camera_QR10"

    def test_name(self, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        assert cam.name == "Casa Salon"

    def test_should_not_poll(self, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import SecuritasCamera

        cam = SecuritasCamera(mock_hub, installation, camera_device)
        assert cam.should_poll is False

    @pytest.mark.asyncio
    async def test_camera_image_returns_stored_bytes(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import SecuritasCamera

        image_bytes = b"\xff\xd8\xff\xe0fake_jpeg"
        mock_hub.get_camera_image.return_value = image_bytes
        cam = SecuritasCamera(mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == image_bytes
        mock_hub.get_camera_image.assert_called_once_with("2654190", "QR10")

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_empty(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import (
            SecuritasCamera,
            _PLACEHOLDER_IMAGE,
        )

        mock_hub.get_camera_image.return_value = None
        cam = SecuritasCamera(mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == _PLACEHOLDER_IMAGE


class TestSecuritasCaptureButton:
    def test_unique_id(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton

        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        assert btn.unique_id == "v4_2654190_capture_QR10"

    def test_name(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton

        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        assert btn.name == "Casa Capture Salon"

    def test_icon(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton

        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        assert btn.icon == "mdi:camera"

    @pytest.mark.asyncio
    async def test_press_calls_capture(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton

        mock_hub.capture_image = AsyncMock(return_value=b"\xff\xd8")
        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        await btn.async_press()
        mock_hub.capture_image.assert_called_once_with(installation, camera_device)

    @pytest.mark.asyncio
    async def test_press_handles_error(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import SecuritasCaptureButton
        from custom_components.securitas.securitas_direct_new_api.exceptions import (
            SecuritasDirectError,
        )

        mock_hub.capture_image = AsyncMock(side_effect=SecuritasDirectError("fail"))
        btn = SecuritasCaptureButton(mock_hub, installation, camera_device)
        # Should not raise
        await btn.async_press()
