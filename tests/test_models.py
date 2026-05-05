"""Tests for securitas_direct_new_api.models."""

from __future__ import annotations

import pytest

from custom_components.securitas.securitas_direct_new_api.exceptions import (
    UnexpectedStateError,
)
from custom_components.securitas.securitas_direct_new_api.models import (
    AirQuality,
    AlarmState,
    AnnexMode,
    ArmCommand,
    Attribute,
    CameraDevice,
    Installation,
    InteriorMode,
    LockAutolock,
    LockFeatures,
    OperationStatus,
    OtpPhone,
    PerimeterMode,
    PROTO_TO_STATE,
    ProtoCode,
    Sentinel,
    Service,
    SmartLock,
    SmartLockMode,
    SmartLockModeStatus,
    SStatus,
    STATE_TO_COMMAND,
    STATE_TO_PROTO,
    ThumbnailResponse,
    parse_proto_code,
)


# ── Enums ─────────────────────────────────────────────────────────────────────


class TestInteriorMode:
    def test_values(self):
        assert InteriorMode.OFF == "off"
        assert InteriorMode.DAY == "day"
        assert InteriorMode.NIGHT == "night"
        assert InteriorMode.TOTAL == "total"

    def test_all_members(self):
        assert set(InteriorMode) == {
            InteriorMode.OFF,
            InteriorMode.DAY,
            InteriorMode.NIGHT,
            InteriorMode.TOTAL,
        }

    def test_is_str(self):
        assert isinstance(InteriorMode.OFF, str)


class TestPerimeterMode:
    def test_values(self):
        assert PerimeterMode.OFF == "off"
        assert PerimeterMode.ON == "on"

    def test_all_members(self):
        assert set(PerimeterMode) == {PerimeterMode.OFF, PerimeterMode.ON}

    def test_is_str(self):
        assert isinstance(PerimeterMode.ON, str)


class TestAnnexMode:
    def test_values(self):
        assert AnnexMode.OFF == "off"
        assert AnnexMode.ON == "on"

    def test_all_members(self):
        assert set(AnnexMode) == {AnnexMode.OFF, AnnexMode.ON}

    def test_is_str(self):
        assert isinstance(AnnexMode.ON, str)


class TestProtoCode:
    def test_values(self):
        assert ProtoCode.DISARMED == "D"
        assert ProtoCode.PERIMETER_ONLY == "E"
        assert ProtoCode.PARTIAL_DAY == "P"
        assert ProtoCode.PARTIAL_NIGHT == "Q"
        assert ProtoCode.PARTIAL_DAY_PERIMETER == "B"
        assert ProtoCode.PARTIAL_NIGHT_PERIMETER == "C"
        assert ProtoCode.TOTAL == "T"
        assert ProtoCode.TOTAL_PERIMETER == "A"

    def test_eight_members(self):
        assert len(ProtoCode) == 8

    def test_is_str(self):
        assert isinstance(ProtoCode.DISARMED, str)


class TestArmCommand:
    def test_values(self):
        assert ArmCommand.DISARM == "DARM1"
        assert ArmCommand.DISARM_ALL == "DARM1DARMPERI"
        assert ArmCommand.ARM_DAY == "ARMDAY1"
        assert ArmCommand.ARM_NIGHT == "ARMNIGHT1"
        assert ArmCommand.ARM_TOTAL == "ARM1"
        assert ArmCommand.ARM_PERIMETER == "PERI1"
        assert ArmCommand.ARM_DAY_PERIMETER == "ARMDAY1PERI1"
        assert ArmCommand.ARM_NIGHT_PERIMETER == "ARMNIGHT1PERI1"
        assert ArmCommand.ARM_TOTAL_PERIMETER == "ARM1PERI1"

    def test_nine_members(self):
        assert len(ArmCommand) == 9

    def test_is_str(self):
        assert isinstance(ArmCommand.ARM_TOTAL, str)


# ── AlarmState ────────────────────────────────────────────────────────────────


class TestAlarmState:
    def test_construction(self):
        state = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        assert state.interior == InteriorMode.OFF
        assert state.perimeter == PerimeterMode.OFF

    def test_frozen_cannot_mutate(self):
        state = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        with pytest.raises(Exception):
            state.interior = InteriorMode.DAY  # type: ignore[misc]

    def test_equality(self):
        a = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.ON)
        b = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.ON)
        assert a == b

    def test_inequality(self):
        a = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF)
        b = AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.OFF)
        assert a != b

    def test_hashable(self):
        state = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        d = {state: "armed_total_peri"}
        assert d[state] == "armed_total_peri"

    def test_usable_as_dict_key(self):
        states = {
            AlarmState(
                interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF
            ): "disarmed",
            AlarmState(
                interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF
            ): "armed_away",
        }
        assert (
            states[AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)]
            == "disarmed"
        )
        assert (
            states[AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)]
            == "armed_away"
        )

    def test_hash_equal_objects_same_hash(self):
        a = AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.ON)
        b = AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.ON)
        assert hash(a) == hash(b)

    def test_not_equal_to_non_alarm_state(self):
        state = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        assert state.__eq__("not an alarm state") == NotImplemented


class TestAlarmStateAnnex:
    def test_annex_defaults_to_off(self):
        s = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        assert s.annex == AnnexMode.OFF

    def test_annex_explicit(self):
        s = AlarmState(
            interior=InteriorMode.DAY,
            perimeter=PerimeterMode.OFF,
            annex=AnnexMode.ON,
        )
        assert s.annex == AnnexMode.ON

    def test_three_axis_equality(self):
        a = AlarmState(
            interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF, annex=AnnexMode.ON,
        )
        b = AlarmState(
            interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF, annex=AnnexMode.ON,
        )
        c = AlarmState(
            interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF, annex=AnnexMode.OFF,
        )
        assert a == b
        assert a != c
        assert hash(a) == hash(b)
        assert hash(a) != hash(c)


# ── Mapping tables ────────────────────────────────────────────────────────────


class TestProtoToState:
    def test_has_eight_entries(self):
        assert len(PROTO_TO_STATE) == 8

    def test_all_proto_codes_mapped(self):
        for code in ProtoCode:
            assert code in PROTO_TO_STATE, f"{code} not in PROTO_TO_STATE"

    def test_disarmed_maps_to_off_off(self):
        state = PROTO_TO_STATE[ProtoCode.DISARMED]
        assert state.interior == InteriorMode.OFF
        assert state.perimeter == PerimeterMode.OFF

    def test_perimeter_only_maps_to_off_on(self):
        state = PROTO_TO_STATE[ProtoCode.PERIMETER_ONLY]
        assert state.interior == InteriorMode.OFF
        assert state.perimeter == PerimeterMode.ON

    def test_partial_day_maps_to_day_off(self):
        state = PROTO_TO_STATE[ProtoCode.PARTIAL_DAY]
        assert state.interior == InteriorMode.DAY
        assert state.perimeter == PerimeterMode.OFF

    def test_partial_night_maps_to_night_off(self):
        state = PROTO_TO_STATE[ProtoCode.PARTIAL_NIGHT]
        assert state.interior == InteriorMode.NIGHT
        assert state.perimeter == PerimeterMode.OFF

    def test_partial_day_perimeter_maps_to_day_on(self):
        state = PROTO_TO_STATE[ProtoCode.PARTIAL_DAY_PERIMETER]
        assert state.interior == InteriorMode.DAY
        assert state.perimeter == PerimeterMode.ON

    def test_partial_night_perimeter_maps_to_night_on(self):
        state = PROTO_TO_STATE[ProtoCode.PARTIAL_NIGHT_PERIMETER]
        assert state.interior == InteriorMode.NIGHT
        assert state.perimeter == PerimeterMode.ON

    def test_total_maps_to_total_off(self):
        state = PROTO_TO_STATE[ProtoCode.TOTAL]
        assert state.interior == InteriorMode.TOTAL
        assert state.perimeter == PerimeterMode.OFF

    def test_total_perimeter_maps_to_total_on(self):
        state = PROTO_TO_STATE[ProtoCode.TOTAL_PERIMETER]
        assert state.interior == InteriorMode.TOTAL
        assert state.perimeter == PerimeterMode.ON


class TestStateToProto:
    def test_has_eight_entries(self):
        assert len(STATE_TO_PROTO) == 8

    def test_is_reverse_of_proto_to_state(self):
        for code, state in PROTO_TO_STATE.items():
            assert STATE_TO_PROTO[state] == code

    def test_bidirectional_roundtrip(self):
        for code in ProtoCode:
            state = PROTO_TO_STATE[code]
            assert STATE_TO_PROTO[state] == code


class TestStateToCommand:
    def test_every_state_has_command(self):
        for state in PROTO_TO_STATE.values():
            assert state in STATE_TO_COMMAND, f"{state} not in STATE_TO_COMMAND"

    def test_disarmed_state_maps_to_disarm(self):
        disarmed = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.OFF)
        assert STATE_TO_COMMAND[disarmed] == ArmCommand.DISARM

    def test_perimeter_only_maps_to_arm_perimeter(self):
        peri = AlarmState(interior=InteriorMode.OFF, perimeter=PerimeterMode.ON)
        assert STATE_TO_COMMAND[peri] == ArmCommand.ARM_PERIMETER

    def test_day_maps_to_arm_day(self):
        state = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.OFF)
        assert STATE_TO_COMMAND[state] == ArmCommand.ARM_DAY

    def test_night_maps_to_arm_night(self):
        state = AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.OFF)
        assert STATE_TO_COMMAND[state] == ArmCommand.ARM_NIGHT

    def test_total_maps_to_arm_total(self):
        state = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.OFF)
        assert STATE_TO_COMMAND[state] == ArmCommand.ARM_TOTAL

    def test_day_perimeter_maps_to_arm_day_perimeter(self):
        state = AlarmState(interior=InteriorMode.DAY, perimeter=PerimeterMode.ON)
        assert STATE_TO_COMMAND[state] == ArmCommand.ARM_DAY_PERIMETER

    def test_night_perimeter_maps_to_arm_night_perimeter(self):
        state = AlarmState(interior=InteriorMode.NIGHT, perimeter=PerimeterMode.ON)
        assert STATE_TO_COMMAND[state] == ArmCommand.ARM_NIGHT_PERIMETER

    def test_total_perimeter_maps_to_arm_total_perimeter(self):
        state = AlarmState(interior=InteriorMode.TOTAL, perimeter=PerimeterMode.ON)
        assert STATE_TO_COMMAND[state] == ArmCommand.ARM_TOTAL_PERIMETER


# ── parse_proto_code ──────────────────────────────────────────────────────────


class TestParseProtoCode:
    @pytest.mark.parametrize(
        "code,expected",
        [
            ("D", ProtoCode.DISARMED),
            ("E", ProtoCode.PERIMETER_ONLY),
            ("P", ProtoCode.PARTIAL_DAY),
            ("Q", ProtoCode.PARTIAL_NIGHT),
            ("B", ProtoCode.PARTIAL_DAY_PERIMETER),
            ("C", ProtoCode.PARTIAL_NIGHT_PERIMETER),
            ("T", ProtoCode.TOTAL),
            ("A", ProtoCode.TOTAL_PERIMETER),
        ],
    )
    def test_valid_codes(self, code, expected):
        assert parse_proto_code(code) == expected

    def test_invalid_code_raises_unexpected_state_error(self):
        with pytest.raises(UnexpectedStateError) as exc_info:
            parse_proto_code("X")
        assert exc_info.value.proto_code == "X"

    def test_empty_string_raises_unexpected_state_error(self):
        with pytest.raises(UnexpectedStateError):
            parse_proto_code("")

    def test_lowercase_raises_unexpected_state_error(self):
        with pytest.raises(UnexpectedStateError):
            parse_proto_code("d")


# ── Installation ──────────────────────────────────────────────────────────────


class TestInstallation:
    def test_defaults(self):
        inst = Installation()
        assert inst.number == ""
        assert inst.alias == ""
        assert inst.panel == ""
        assert inst.type == ""
        assert inst.name == ""
        assert inst.last_name == ""
        assert inst.address == ""
        assert inst.city == ""
        assert inst.postal_code == ""
        assert inst.province == ""
        assert inst.email == ""
        assert inst.phone == ""
        assert inst.capabilities == ""
        assert inst.alarm_partitions == []

    def test_construction_from_api_response_dict_with_aliases(self):
        """Verify that camelCase API response keys work via aliases."""
        data = {
            "numinst": "123456",
            "alias": "Home",
            "panel": "SDVFAST",
            "type": "PLUS",
            "name": "John",
            "surname": "Doe",
            "address": "123 Main St",
            "city": "Madrid",
            "postcode": "28001",
            "province": "Madrid",
            "email": "test@example.com",
            "phone": "555-1234",
            "capabilities": "cap1",
        }
        inst = Installation.model_validate(data)
        assert inst.number == "123456"
        assert inst.last_name == "Doe"
        assert inst.postal_code == "28001"

    def test_construction_with_python_field_names(self):
        """Verify populate_by_name=True: snake_case names also work."""
        inst = Installation(
            number="789",
            last_name="Smith",
            postal_code="12345",
        )
        assert inst.number == "789"
        assert inst.last_name == "Smith"
        assert inst.postal_code == "12345"

    def test_is_mutable(self):
        inst = Installation(number="123")
        inst.number = "456"
        assert inst.number == "456"

    def test_alarm_partitions_default_factory(self):
        a = Installation()
        b = Installation()
        assert a.alarm_partitions is not b.alarm_partitions


# ── OperationStatus ───────────────────────────────────────────────────────────


class TestOperationStatus:
    def test_defaults(self):
        op = OperationStatus()
        assert op.operation_status == ""
        assert op.message == ""
        assert op.status == ""
        assert op.installation_number == ""
        assert op.protom_response == ""
        assert op.protom_response_data == ""
        assert op.request_id == ""
        assert op.error is None

    def test_construction_from_api_response_dict(self):
        data = {
            "res": "OK",
            "msg": "Operation completed",
            "status": "1",
            "numinst": "123456",
            "protomResponse": "T",
            "protomResponseDate": "2024-01-01",
            "requestId": "req-001",
            "error": None,
        }
        op = OperationStatus.model_validate(data)
        assert op.operation_status == "OK"
        assert op.message == "Operation completed"
        assert op.installation_number == "123456"
        assert op.protom_response == "T"
        assert op.protom_response_data == "2024-01-01"
        assert op.request_id == "req-001"

    def test_error_field_can_be_dict(self):
        op = OperationStatus(error={"code": "ERR001", "description": "failed"})
        assert op.error == {"code": "ERR001", "description": "failed"}

    def test_python_field_names(self):
        op = OperationStatus(operation_status="ERR", message="bad", request_id="r1")
        assert op.operation_status == "ERR"
        assert op.request_id == "r1"


# ── SStatus ───────────────────────────────────────────────────────────────────


class TestSStatus:
    def test_defaults(self):
        s = SStatus()
        assert s.status is None
        assert s.timestamp_update is None
        assert s.wifi_connected is None

    def test_construction_from_api_response_dict(self):
        data = {
            "status": "1",
            "timestampUpdate": "2024-01-01T12:00:00",
            "wifiConnected": True,
        }
        s = SStatus.model_validate(data)
        assert s.status == "1"
        assert s.timestamp_update == "2024-01-01T12:00:00"
        assert s.wifi_connected is True

    def test_python_field_names(self):
        s = SStatus(status="0", timestamp_update="ts", wifi_connected=False)
        assert s.status == "0"
        assert s.timestamp_update == "ts"
        assert s.wifi_connected is False


# ── Lock models ───────────────────────────────────────────────────────────────


class TestLockAutolock:
    def test_defaults(self):
        al = LockAutolock()
        assert al.active is None
        assert al.timeout is None

    def test_construction(self):
        al = LockAutolock(active=True, timeout=30)
        assert al.active is True
        assert al.timeout == 30

    def test_timeout_can_be_str(self):
        al = LockAutolock(timeout="30s")
        assert al.timeout == "30s"


class TestLockFeatures:
    def test_defaults(self):
        lf = LockFeatures()
        assert lf.hold_back_latch_time == 0
        assert lf.calibration_type == 0
        assert lf.autolock is None

    def test_from_api_dict_with_nested_autolock(self):
        data = {
            "holdBackLatchTime": 5,
            "calibrationType": 2,
            "autolock": {"active": True, "timeout": 60},
        }
        lf = LockFeatures.model_validate(data)
        assert lf.hold_back_latch_time == 5
        assert lf.calibration_type == 2
        assert lf.autolock is not None
        assert lf.autolock.active is True
        assert lf.autolock.timeout == 60

    def test_python_field_names(self):
        lf = LockFeatures(hold_back_latch_time=3, calibration_type=1)
        assert lf.hold_back_latch_time == 3
        assert lf.calibration_type == 1


class TestSmartLock:
    def test_defaults(self):
        sl = SmartLock()
        assert sl.res is None
        assert sl.location is None
        assert sl.device_id == ""
        assert sl.reference_id == ""
        assert sl.zone_id == ""
        assert sl.serial_number == ""
        assert sl.family == ""
        assert sl.label == ""
        assert sl.features is None

    def test_from_api_dict(self):
        data = {
            "res": "OK",
            "location": "front_door",
            "deviceId": "dev-001",
            "referenceId": "ref-001",
            "zoneId": "zone-1",
            "serialNumber": "SN12345",
            "family": "LOCK_V2",
            "label": "Front Door",
            "features": {
                "holdBackLatchTime": 2,
                "calibrationType": 0,
                "autolock": {"active": False, "timeout": None},
            },
        }
        sl = SmartLock.model_validate(data)
        assert sl.res == "OK"
        assert sl.device_id == "dev-001"
        assert sl.reference_id == "ref-001"
        assert sl.zone_id == "zone-1"
        assert sl.serial_number == "SN12345"
        assert sl.features is not None
        assert sl.features.hold_back_latch_time == 2
        assert sl.features.autolock is not None
        assert sl.features.autolock.active is False


class TestSmartLockMode:
    def test_defaults(self):
        slm = SmartLockMode()
        assert slm.res is None
        assert slm.lock_status == ""
        assert slm.device_id == ""
        assert slm.status_timestamp == ""

    def test_from_api_dict(self):
        data = {
            "res": "OK",
            "lockStatus": "LOCKED",
            "deviceId": "dev-001",
            "statusTimestamp": "2024-01-01T12:00:00",
        }
        slm = SmartLockMode.model_validate(data)
        assert slm.lock_status == "LOCKED"
        assert slm.device_id == "dev-001"
        assert slm.status_timestamp == "2024-01-01T12:00:00"


class TestSmartLockModeStatus:
    def test_defaults(self):
        slms = SmartLockModeStatus()
        assert slms.request_id == ""
        assert slms.message == ""
        assert slms.protom_response == ""
        assert slms.status == ""

    def test_from_api_dict(self):
        data = {
            "requestId": "req-123",
            "msg": "Lock command sent",
            "protomResponse": "OK",
            "status": "1",
        }
        slms = SmartLockModeStatus.model_validate(data)
        assert slms.request_id == "req-123"
        assert slms.message == "Lock command sent"
        assert slms.protom_response == "OK"
        assert slms.status == "1"


# ── Camera models ─────────────────────────────────────────────────────────────


class TestCameraDevice:
    def test_defaults(self):
        cam = CameraDevice()
        assert cam.id == ""
        assert cam.code == 0
        assert cam.zone_id == ""
        assert cam.name == ""
        assert cam.device_type == ""
        assert cam.serial_number is None

    def test_from_api_dict(self):
        data = {
            "id": "cam-001",
            "code": 5,
            "zoneId": "zone-2",
            "name": "Front Camera",
            "type": "QR",
            "serialNumber": "CAM12345",
        }
        cam = CameraDevice.model_validate(data)
        assert cam.id == "cam-001"
        assert cam.code == 5
        assert cam.zone_id == "zone-2"
        assert cam.name == "Front Camera"
        assert cam.device_type == "QR"
        assert cam.serial_number == "CAM12345"

    def test_serial_number_can_be_none(self):
        data = {"id": "cam-002", "code": 1, "zoneId": "z1", "name": "Cam", "type": "YR"}
        cam = CameraDevice.model_validate(data)
        assert cam.serial_number is None


class TestThumbnailResponse:
    def test_defaults(self):
        tr = ThumbnailResponse()
        assert tr.id_signal is None
        assert tr.device_code is None
        assert tr.device_alias is None
        assert tr.timestamp is None
        assert tr.signal_type is None
        assert tr.image is None

    def test_from_api_dict(self):
        data = {
            "idSignal": "sig-001",
            "deviceCode": "QR",
            "deviceAlias": "Front Door Camera",
            "timestamp": "2024-01-01T12:00:00",
            "signalType": "IMAGE",
            "image": "base64encodeddata...",
        }
        tr = ThumbnailResponse.model_validate(data)
        assert tr.id_signal == "sig-001"
        assert tr.device_code == "QR"
        assert tr.device_alias == "Front Door Camera"
        assert tr.timestamp == "2024-01-01T12:00:00"
        assert tr.signal_type == "IMAGE"
        assert tr.image == "base64encodeddata..."


# ── Sensor models ─────────────────────────────────────────────────────────────


class TestSentinel:
    def test_construction(self):
        s = Sentinel(
            alias="Living Room", air_quality="GOOD", humidity=55, temperature=22
        )
        assert s.alias == "Living Room"
        assert s.air_quality == "GOOD"
        assert s.humidity == 55
        assert s.temperature == 22
        assert s.zone == ""

    def test_with_zone(self):
        s = Sentinel(
            alias="Bedroom",
            air_quality="MODERATE",
            humidity=60,
            temperature=20,
            zone="zone-3",
        )
        assert s.zone == "zone-3"


class TestAirQuality:
    def test_construction_with_value(self):
        aq = AirQuality(value=42)
        assert aq.value == 42
        assert aq.status_current == 0

    def test_construction_with_status(self):
        aq = AirQuality(value=100, status_current=2)
        assert aq.value == 100
        assert aq.status_current == 2

    def test_value_can_be_none(self):
        aq = AirQuality(value=None)
        assert aq.value is None


class TestOtpPhone:
    def test_construction(self):
        otp = OtpPhone(id=1, phone="+34 555 123 456")
        assert otp.id == 1
        assert otp.phone == "+34 555 123 456"


# ── Service ───────────────────────────────────────────────────────────────────


class TestAttribute:
    def test_defaults(self):
        attr = Attribute()
        assert attr.name == ""
        assert attr.value == ""
        assert attr.active is False

    def test_construction(self):
        attr = Attribute(name="SirenVolume", value="HIGH", active=True)
        assert attr.name == "SirenVolume"
        assert attr.value == "HIGH"
        assert attr.active is True


class TestService:
    def test_defaults(self):
        svc = Service()
        assert svc.id == 0
        assert svc.id_service == 0
        assert svc.active is False
        assert svc.visible is False
        assert svc.bde is False
        assert svc.is_premium is False
        assert svc.cod_oper is False
        assert svc.total_device == 0
        assert svc.request == ""
        assert svc.multiple_req is False
        assert svc.num_devices_mr == 0
        assert svc.secret_word is False
        assert svc.min_wrapper_version is None
        assert svc.description == ""
        assert svc.attributes == []
        assert svc.listdiy == []
        assert svc.listprompt == []
        assert svc.installation is None

    def test_construction_with_attribute_list(self):
        attrs = [
            Attribute(name="attr1", value="v1", active=True),
            Attribute(name="attr2", value="v2", active=False),
        ]
        svc = Service(
            id=10,
            id_service=20,
            active=True,
            description="Test Service",
            attributes=attrs,
        )
        assert svc.id == 10
        assert svc.id_service == 20
        assert svc.active is True
        assert svc.description == "Test Service"
        assert len(svc.attributes) == 2
        assert svc.attributes[0].name == "attr1"
        assert svc.attributes[1].value == "v2"

    def test_from_api_dict_with_aliases(self):
        data = {
            "id": 5,
            "idService": 15,
            "active": True,
            "visible": True,
            "bde": False,
            "isPremium": True,
            "codOper": False,
            "totalDevice": 3,
            "request": "xSArmPanel",
            "multiple_req": False,
            "num_devices_mr": 0,
            "secret_word": False,
            "minWrapperVersion": None,
            "description": "Alarm arming",
            "attributes": [],
            "listdiy": [],
            "listprompt": [],
        }
        svc = Service.model_validate(data)
        assert svc.id == 5
        assert svc.id_service == 15
        assert svc.is_premium is True
        assert svc.total_device == 3

    def test_attributes_default_factory_isolation(self):
        a = Service()
        b = Service()
        assert a.attributes is not b.attributes

    def test_with_installation(self):
        inst = Installation(number="123")
        svc = Service(installation=inst)
        assert svc.installation is not None
        assert svc.installation.number == "123"
