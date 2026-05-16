"""Tests for camera platform entities."""

import base64

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.securitas.verisure_owa_api.models import (
    CameraDevice,
    ThumbnailResponse,
)
from custom_components.securitas.verisure_owa_api import Installation
from custom_components.securitas import DOMAIN
from custom_components.securitas.coordinators import CameraCoordinator, CameraData
from custom_components.securitas.entity import camera_device_info


class TestCameraDeviceInfo:
    def test_identifiers_include_zone_id(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info[
            "identifiers"
        ]

    def test_name_is_camera_device_name(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["name"] == "Salon"

    def test_manufacturer(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["manufacturer"] == "Verisure"

    def test_model(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["model"] == "Camera"

    def test_via_device_points_to_installation(self, installation, camera_device):
        info = camera_device_info(installation, camera_device)
        assert info["via_device"] == (DOMAIN, "v4_securitas_direct.2654190")


@pytest.fixture
def installation():
    return Installation(number="2654190", panel="SDVECU", alias="Casa")


@pytest.fixture
def camera_device():
    return CameraDevice(
        id="11",
        code=10,
        zone_id="QR10",
        name="Salon",
        device_type="QR",
        serial_number="36NEYYER",
    )


@pytest.fixture
def mock_hub():
    hub = MagicMock()
    hub.camera_images = {}
    hub.get_camera_image = MagicMock(return_value=None)
    hub.is_capturing = MagicMock(return_value=False)
    return hub


@pytest.fixture
def mock_coordinator():
    """Create a mock CameraCoordinator with sensible defaults."""
    coord = MagicMock(spec=CameraCoordinator)
    coord.data = CameraData(thumbnails={}, full_images={})
    # CoordinatorEntity expects these
    coord.async_request_refresh = AsyncMock()
    coord.async_add_listener = MagicMock(return_value=MagicMock())
    return coord


@pytest.fixture
def placeholder_bytes():
    """Pre-populate the camera module's lazy placeholder cache for assertions."""
    from custom_components.securitas import camera as cam_module

    bytes_ = b"\xff\xd8\xff\xe0test-placeholder"
    cam_module._PLACEHOLDER_IMAGE = bytes_
    yield bytes_
    cam_module._PLACEHOLDER_IMAGE = None


@pytest.fixture
def jpeg_thumbnail():
    """Return a ThumbnailResponse with valid JPEG base64 data."""
    jpeg_bytes = b"\xff\xd8\xff\xe0fake_jpeg"
    return ThumbnailResponse(
        image=base64.b64encode(jpeg_bytes).decode(),
        timestamp="2026-03-09T12:00:00Z",
    )


class TestVerisureCamera:
    def test_unique_id(self, mock_coordinator, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert cam.unique_id == "v4_securitas_direct.2654190_camera_QR10"

    def test_has_entity_name(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert cam._attr_has_entity_name is True

    def test_no_entity_name_suffix(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """Camera is the primary entity of its device -- no name suffix is set."""
        from homeassistant.helpers.entity import UNDEFINED
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert cam.name is UNDEFINED

    def test_should_not_poll(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert cam.should_poll is False

    @pytest.mark.asyncio
    async def test_camera_image_returns_stored_bytes(
        self, mock_coordinator, mock_hub, installation, camera_device, jpeg_thumbnail
    ):
        from custom_components.securitas.camera import VerisureCamera

        mock_coordinator.data = CameraData(
            thumbnails={"QR10": jpeg_thumbnail}, full_images={}
        )
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == base64.b64decode(jpeg_thumbnail.image)

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_empty(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        placeholder_bytes,
    ):
        from custom_components.securitas.camera import VerisureCamera

        mock_coordinator.data = CameraData(thumbnails={}, full_images={})
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == placeholder_bytes

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_no_data(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        placeholder_bytes,
    ):
        from custom_components.securitas.camera import VerisureCamera

        mock_coordinator.data = None
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == placeholder_bytes

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_for_non_jpeg(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        placeholder_bytes,
    ):
        from custom_components.securitas.camera import VerisureCamera

        # Non-JPEG data (e.g. a file path encoded as base64)
        non_jpeg = ThumbnailResponse(
            image=base64.b64encode(b"not_jpeg_data").decode(),
        )
        mock_coordinator.data = CameraData(
            thumbnails={"QR10": non_jpeg}, full_images={}
        )
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        result = await cam.async_camera_image()
        assert result == placeholder_bytes

    @pytest.mark.asyncio
    async def test_placeholder_loaded_via_executor_on_first_call(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """First placeholder access uses hass.async_add_executor_job and caches the result."""
        from custom_components.securitas import camera as cam_module

        cam_module._PLACEHOLDER_IMAGE = None

        mock_coordinator.data = None
        cam = cam_module.VerisureCamera(
            mock_coordinator, mock_hub, installation, camera_device
        )

        placeholder_bytes = b"\xff\xd8\xff\xe0fake-placeholder"
        mock_hass = MagicMock()
        mock_hass.async_add_executor_job = AsyncMock(return_value=placeholder_bytes)
        cam.hass = mock_hass

        result = await cam.async_camera_image()

        mock_hass.async_add_executor_job.assert_called_once()
        assert result == placeholder_bytes
        assert cam_module._PLACEHOLDER_IMAGE == placeholder_bytes

    @pytest.mark.asyncio
    async def test_placeholder_cached_after_first_load(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """Subsequent placeholder accesses return the cached bytes without re-reading."""
        from custom_components.securitas import camera as cam_module

        placeholder_bytes = b"\xff\xd8cached-placeholder"
        cam_module._PLACEHOLDER_IMAGE = placeholder_bytes

        mock_coordinator.data = None
        cam = cam_module.VerisureCamera(
            mock_coordinator, mock_hub, installation, camera_device
        )

        mock_hass = MagicMock()
        mock_hass.async_add_executor_job = AsyncMock()
        cam.hass = mock_hass

        result = await cam.async_camera_image()

        mock_hass.async_add_executor_job.assert_not_called()
        assert result == placeholder_bytes

    def test_device_info_uses_camera_sub_device(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera
        from custom_components.securitas import DOMAIN

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        info = cam.device_info
        assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info[
            "identifiers"
        ]
        assert info.get("via_device") == (DOMAIN, "v4_securitas_direct.2654190")

    def test_extra_state_attributes_timestamp(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        jpeg_thumbnail,
    ):
        from custom_components.securitas.camera import VerisureCamera

        mock_coordinator.data = CameraData(
            thumbnails={"QR10": jpeg_thumbnail}, full_images={}
        )
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        attrs = cam.extra_state_attributes
        assert attrs["image_timestamp"] == "2026-03-09T12:00:00Z"
        assert attrs["capturing"] is False

    def test_extra_state_attributes_no_data(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera

        mock_coordinator.data = None
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        attrs = cam.extra_state_attributes
        assert attrs["image_timestamp"] is None

    def test_handle_coordinator_update_rotates_token(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        cam.async_update_token = MagicMock()
        cam.async_write_ha_state = MagicMock()

        cam._handle_coordinator_update()
        cam.async_update_token.assert_called_once()
        cam.async_write_ha_state.assert_called_once()

    @pytest.mark.asyncio
    async def test_async_added_to_hass_subscribes_to_state_signal(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        mock_hass = MagicMock()
        cam.hass = mock_hass

        connected_signal = {}

        def _capture_connect(hass, signal, callback):
            connected_signal[signal] = callback
            return MagicMock()

        with patch(
            "custom_components.securitas.camera.async_dispatcher_connect",
            side_effect=_capture_connect,
        ):
            await cam.async_added_to_hass()

        from custom_components.securitas.const import SIGNAL_CAMERA_STATE

        assert SIGNAL_CAMERA_STATE in connected_signal

    def test_handle_state_writes_for_matching_camera(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        cam.async_write_ha_state = MagicMock()

        cam._handle_state("2654190", "QR10")
        cam.async_write_ha_state.assert_called_once()

    def test_handle_state_ignores_other_camera(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        cam.async_write_ha_state = MagicMock()

        cam._handle_state("2654190", "QR11")
        cam.async_write_ha_state.assert_not_called()


@pytest.mark.asyncio
class TestAsyncManualCapture:
    """VerisureCamera.async_manual_capture backs both the
    `verisure_owa.capture_image` entity service and the deprecated
    VerisureCaptureButton.  The button delegates here; the card calls
    the service which calls here.
    """

    async def test_delegates_to_hub_capture_image(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCamera

        mock_hub.capture_image = AsyncMock(
            return_value=(
                b"\xff\xd8",
                ThumbnailResponse(id_signal="sig", signal_type="16"),
            )
        )
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)

        with patch(
            "custom_components.securitas.camera.inject_ha_event",
            new=AsyncMock(),
        ):
            await cam.async_manual_capture()

        mock_hub.capture_image.assert_awaited_once_with(installation, camera_device)

    async def test_injects_image_request_event_with_server_ids(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """When the capture returns a thumbnail with real server ids, the
        injected activity event uses them so the activity-log card can
        fetch the image (id_signal must be real; img=1 follows from that)."""
        from custom_components.securitas.camera import VerisureCamera
        from custom_components.securitas.verisure_owa_api.models import ActivityCategory

        mock_hub.capture_image = AsyncMock(
            return_value=(
                b"\xff\xd8",
                ThumbnailResponse(id_signal="real-id", signal_type="16"),
            )
        )
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)

        with patch(
            "custom_components.securitas.camera.inject_ha_event",
            new=AsyncMock(),
        ) as mock_inject:
            await cam.async_manual_capture()

        mock_inject.assert_awaited_once()
        kwargs = mock_inject.await_args.kwargs
        assert kwargs["category"] == ActivityCategory.IMAGE_REQUEST
        assert kwargs["id_signal"] == "real-id"
        assert kwargs["signal_type"] == "16"
        assert kwargs["device"] == camera_device.zone_id
        assert kwargs["device_name"] == camera_device.name

    async def test_no_event_on_capture_error(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """When the capture itself fails, no activity event is injected —
        the failure was already logged by the hub layer."""
        from custom_components.securitas.camera import VerisureCamera
        from custom_components.securitas.verisure_owa_api.exceptions import (
            VerisureOwaError,
        )

        mock_hub.capture_image = AsyncMock(side_effect=VerisureOwaError("boom"))
        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)

        with patch(
            "custom_components.securitas.camera.inject_ha_event",
            new=AsyncMock(),
        ) as mock_inject:
            await cam.async_manual_capture()  # must not raise

        mock_inject.assert_not_awaited()


class TestVerisureCaptureButton:
    def test_unique_id(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import VerisureCaptureButton

        btn = VerisureCaptureButton(mock_hub, installation, camera_device)
        assert btn.unique_id == "v4_securitas_direct.2654190_capture_QR10"

    def test_has_entity_name(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import VerisureCaptureButton

        btn = VerisureCaptureButton(mock_hub, installation, camera_device)
        assert btn._attr_has_entity_name is True

    def test_name_is_capture(self, mock_hub, installation, camera_device):
        """Button name is the entity-specific suffix; device name is prepended by HA."""
        from custom_components.securitas.button import VerisureCaptureButton

        btn = VerisureCaptureButton(mock_hub, installation, camera_device)
        assert btn.name == "Capture"

    def test_icon(self, mock_hub, installation, camera_device):
        from custom_components.securitas.button import VerisureCaptureButton

        btn = VerisureCaptureButton(mock_hub, installation, camera_device)
        assert btn.icon == "mdi:camera"

    @pytest.mark.asyncio
    async def test_press_delegates_to_camera_entity(
        self, mock_hub, installation, camera_device
    ):
        """Button is a thin wrapper around camera.async_manual_capture."""
        from custom_components.securitas.button import VerisureCaptureButton

        camera_entity = MagicMock()
        camera_entity.async_manual_capture = AsyncMock()
        btn = VerisureCaptureButton(
            mock_hub, installation, camera_device, camera_entity=camera_entity
        )

        await btn.async_press()

        camera_entity.async_manual_capture.assert_awaited_once_with()

    @pytest.mark.asyncio
    async def test_press_no_op_without_camera_entity(
        self, mock_hub, installation, camera_device
    ):
        """If the button was constructed without a camera reference (legacy
        callers in tests), the press is a no-op rather than crashing."""
        from custom_components.securitas.button import VerisureCaptureButton

        btn = VerisureCaptureButton(mock_hub, installation, camera_device)
        await btn.async_press()  # must not raise

    @pytest.mark.asyncio
    async def test_press_forwards_context_to_camera_entity(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.button import VerisureCaptureButton

        camera_entity = MagicMock()
        camera_entity.async_manual_capture = AsyncMock()
        btn = VerisureCaptureButton(
            mock_hub, installation, camera_device, camera_entity=camera_entity
        )
        ctx = MagicMock()
        btn._context = ctx

        await btn.async_press()

        assert camera_entity._context is ctx

    def test_device_info_uses_camera_sub_device(
        self, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.button import VerisureCaptureButton
        from custom_components.securitas import DOMAIN

        btn = VerisureCaptureButton(mock_hub, installation, camera_device)
        info = btn.device_info
        assert (DOMAIN, "v4_securitas_direct.2654190_camera_QR10") in info[
            "identifiers"
        ]
        assert info.get("via_device") == (DOMAIN, "v4_securitas_direct.2654190")


class TestVerisureCameraFull:
    """Tests for the VerisureCameraFull entity."""

    def test_unique_id(self, mock_coordinator, mock_hub, installation, camera_device):
        from custom_components.securitas.camera import VerisureCameraFull

        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert cam.unique_id == "v4_securitas_direct.2654190_camera_full_QR10"

    def test_has_entity_name(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert cam._attr_has_entity_name is True

    def test_name_is_full_image(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert cam.name == "Full Image"

    def test_should_not_poll(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert cam.should_poll is False

    @pytest.mark.asyncio
    async def test_camera_image_returns_stored_bytes(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        image_bytes = b"\xff\xd8\xff\xe0full_jpeg"
        mock_coordinator.data = CameraData(
            thumbnails={}, full_images={"QR10": image_bytes}
        )
        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        result = await cam.async_camera_image()
        assert result == image_bytes

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_empty(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        placeholder_bytes,
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        mock_coordinator.data = CameraData(thumbnails={}, full_images={})
        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        result = await cam.async_camera_image()
        assert result == placeholder_bytes

    @pytest.mark.asyncio
    async def test_camera_image_returns_placeholder_when_no_data(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        placeholder_bytes,
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        mock_coordinator.data = None
        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        result = await cam.async_camera_image()
        assert result == placeholder_bytes

    def test_device_info_matches_thumbnail_entity(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """Both camera entities must share the same HA device (same identifiers)."""
        from custom_components.securitas.camera import (
            VerisureCamera,
            VerisureCameraFull,
        )
        from custom_components.securitas import DOMAIN

        thumb_cam = VerisureCamera(
            mock_coordinator, mock_hub, installation, camera_device
        )
        full_cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )

        assert (
            thumb_cam.device_info["identifiers"] == full_cam.device_info["identifiers"]
        )
        assert (
            DOMAIN,
            "v4_securitas_direct.2654190_camera_QR10",
        ) in full_cam.device_info["identifiers"]

    def test_handle_coordinator_update_rotates_token(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        cam.async_update_token = MagicMock()
        cam.async_write_ha_state = MagicMock()

        cam._handle_coordinator_update()
        cam.async_update_token.assert_called_once()
        cam.async_write_ha_state.assert_called_once()

    def test_extra_state_attributes_timestamp(
        self,
        mock_coordinator,
        mock_hub,
        installation,
        camera_device,
        jpeg_thumbnail,
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        mock_coordinator.data = CameraData(
            thumbnails={"QR10": jpeg_thumbnail}, full_images={}
        )
        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        attrs = cam.extra_state_attributes
        assert attrs["image_timestamp"] == "2026-03-09T12:00:00Z"

    def test_extra_state_attributes_no_data(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        from custom_components.securitas.camera import VerisureCameraFull

        mock_coordinator.data = None
        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        attrs = cam.extra_state_attributes
        assert attrs["image_timestamp"] is None


class TestCameraV5Schema:
    """Camera unique_ids use the v5 schema."""

    def test_camera_unique_id_uses_canonical_schema(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """New entities use the canonical v4_securitas_direct.<num>_<type>
        form. Pre-v5 installs (with v4_<num>_<type>) are rewritten by
        migrate_unique_ids on first load — see tests/test_migrate_unique_ids.py.
        """
        from custom_components.securitas.camera import VerisureCamera

        cam = VerisureCamera(mock_coordinator, mock_hub, installation, camera_device)
        assert (
            cam._attr_unique_id
            == f"v4_securitas_direct.{installation.number}_camera_{camera_device.zone_id}"
        )

    def test_camera_full_unique_id_uses_canonical_schema(
        self, mock_coordinator, mock_hub, installation, camera_device
    ):
        """New entities use the canonical schema."""
        from custom_components.securitas.camera import VerisureCameraFull

        cam = VerisureCameraFull(
            mock_coordinator, mock_hub, installation, camera_device
        )
        assert (
            cam._attr_unique_id
            == f"v4_securitas_direct.{installation.number}_camera_full_{camera_device.zone_id}"
        )
