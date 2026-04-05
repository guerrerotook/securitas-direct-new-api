"""Tests for securitas_direct_new_api.responses."""

from __future__ import annotations


from custom_components.securitas.securitas_direct_new_api.responses import (
    ArmStatusEnvelope,
    CheckAlarmEnvelope,
    ErrorResponse,
    GeneralStatusEnvelope,
    GraphQLErrorData,
    InstallationListEnvelope,
    LoginEnvelope,
    PanelError,
    SmartlockConfigEnvelope,
    ThumbnailEnvelope,
)


# ── LoginEnvelope ─────────────────────────────────────────────────────────────


class TestLoginEnvelope:
    def test_parse_success_response(self):
        payload = {
            "data": {
                "xSLoginToken": {
                    "res": "OK",
                    "msg": None,
                    "hash": "abc123hash",
                    "refreshToken": "refresh-tok-xyz",
                    "legals": None,
                    "changePassword": False,
                    "needDeviceAuthorization": False,
                    "mainUser": True,
                }
            }
        }
        env = LoginEnvelope.model_validate(payload)
        inner = env.data.xSLoginToken
        assert inner.res == "OK"
        assert inner.hash == "abc123hash"
        assert inner.refresh_token == "refresh-tok-xyz"
        assert inner.change_password is False
        assert inner.need_device_authorization is False
        assert inner.main_user is True

    def test_optional_fields_default_to_none(self):
        payload = {
            "data": {
                "xSLoginToken": {
                    "res": "ERR",
                }
            }
        }
        env = LoginEnvelope.model_validate(payload)
        inner = env.data.xSLoginToken
        assert inner.res == "ERR"
        assert inner.hash is None
        assert inner.refresh_token is None
        assert inner.main_user is None

    def test_alias_mapping_refresh_token(self):
        """refreshToken (camelCase) maps to refresh_token (snake_case)."""
        payload = {
            "data": {
                "xSLoginToken": {
                    "res": "OK",
                    "refreshToken": "tok-abc",
                }
            }
        }
        env = LoginEnvelope.model_validate(payload)
        assert env.data.xSLoginToken.refresh_token == "tok-abc"


# ── InstallationListEnvelope ──────────────────────────────────────────────────


class TestInstallationListEnvelope:
    def test_parse_with_one_installation(self):
        payload = {
            "data": {
                "xSInstallations": {
                    "installations": [
                        {
                            "numinst": "123456",
                            "alias": "Home",
                            "panel": "SDVFAST",
                            "type": "PLUS",
                            "name": "John",
                            "surname": "Doe",
                            "address": "1 Main St",
                            "city": "Madrid",
                            "postcode": "28001",
                            "province": "Madrid",
                            "email": "john@example.com",
                            "phone": "555-0001",
                            "capabilities": "cap-v2",
                        }
                    ]
                }
            }
        }
        env = InstallationListEnvelope.model_validate(payload)
        installations = env.data.xSInstallations.installations
        assert len(installations) == 1
        inst = installations[0]
        # Verify alias mapping: numinst -> number, surname -> last_name, postcode -> postal_code
        assert inst.number == "123456"
        assert inst.last_name == "Doe"
        assert inst.postal_code == "28001"
        assert inst.alias == "Home"
        assert inst.city == "Madrid"

    def test_parse_empty_installation_list(self):
        payload = {"data": {"xSInstallations": {"installations": []}}}
        env = InstallationListEnvelope.model_validate(payload)
        assert env.data.xSInstallations.installations == []

    def test_parse_multiple_installations(self):
        payload = {
            "data": {
                "xSInstallations": {
                    "installations": [
                        {"numinst": "111", "alias": "Home"},
                        {"numinst": "222", "alias": "Office"},
                    ]
                }
            }
        }
        env = InstallationListEnvelope.model_validate(payload)
        assert len(env.data.xSInstallations.installations) == 2
        assert env.data.xSInstallations.installations[1].number == "222"


# ── GeneralStatusEnvelope ─────────────────────────────────────────────────────


class TestGeneralStatusEnvelope:
    def test_parse_wifi_connected(self):
        payload = {
            "data": {
                "xSStatus": {
                    "status": "1",
                    "timestampUpdate": "2024-01-15T10:30:00",
                    "wifiConnected": True,
                    "exceptions": [],
                }
            }
        }
        env = GeneralStatusEnvelope.model_validate(payload)
        status = env.data.xSStatus
        assert status.status == "1"
        assert status.wifi_connected is True
        assert status.timestamp_update == "2024-01-15T10:30:00"
        assert status.exceptions == []

    def test_parse_wifi_disconnected(self):
        payload = {
            "data": {
                "xSStatus": {
                    "status": "0",
                    "wifiConnected": False,
                }
            }
        }
        env = GeneralStatusEnvelope.model_validate(payload)
        assert env.data.xSStatus.wifi_connected is False

    def test_all_optional_fields_none(self):
        payload = {"data": {"xSStatus": {}}}
        env = GeneralStatusEnvelope.model_validate(payload)
        status = env.data.xSStatus
        assert status.status is None
        assert status.wifi_connected is None
        assert status.timestamp_update is None
        assert status.exceptions is None


# ── CheckAlarmEnvelope ────────────────────────────────────────────────────────


class TestCheckAlarmEnvelope:
    def test_parse_with_reference_id(self):
        payload = {
            "data": {
                "xSCheckAlarm": {
                    "res": "OK",
                    "msg": "Check initiated",
                    "referenceId": "ref-check-001",
                }
            }
        }
        env = CheckAlarmEnvelope.model_validate(payload)
        inner = env.data.xSCheckAlarm
        assert inner.res == "OK"
        assert inner.msg == "Check initiated"
        assert inner.reference_id == "ref-check-001"

    def test_alias_mapping_reference_id(self):
        """referenceId (camelCase) maps to reference_id (snake_case)."""
        payload = {
            "data": {
                "xSCheckAlarm": {
                    "res": "OK",
                    "referenceId": "ref-999",
                }
            }
        }
        env = CheckAlarmEnvelope.model_validate(payload)
        assert env.data.xSCheckAlarm.reference_id == "ref-999"

    def test_msg_is_optional(self):
        payload = {
            "data": {
                "xSCheckAlarm": {
                    "res": "OK",
                    "referenceId": "ref-001",
                }
            }
        }
        env = CheckAlarmEnvelope.model_validate(payload)
        assert env.data.xSCheckAlarm.msg is None


# ── ArmStatusEnvelope ─────────────────────────────────────────────────────────


class TestArmStatusEnvelope:
    def test_parse_success(self):
        payload = {
            "data": {
                "xSArmStatus": {
                    "res": "OK",
                    "msg": "Armed successfully",
                    "status": "1",
                    "numinst": "123456",
                    "protomResponse": "T",
                    "protomResponseDate": "2024-01-15",
                    "requestId": "req-arm-001",
                    "error": None,
                }
            }
        }
        env = ArmStatusEnvelope.model_validate(payload)
        result = env.data.xSArmStatus
        assert result.res == "OK"
        assert result.msg == "Armed successfully"
        assert result.status == "1"
        assert result.numinst == "123456"
        assert result.protom_response == "T"
        assert result.protom_response_data == "2024-01-15"
        assert result.request_id == "req-arm-001"
        assert result.error is None

    def test_parse_with_panel_error(self):
        payload = {
            "data": {
                "xSArmStatus": {
                    "res": "ERR",
                    "msg": "Panel error",
                    "error": {
                        "code": "ERR_ZONE_OPEN",
                        "type": "ZONE",
                        "allowForcing": True,
                        "exceptionsNumber": 2,
                        "referenceId": "ref-err-001",
                        "suid": "suid-abc",
                    },
                }
            }
        }
        env = ArmStatusEnvelope.model_validate(payload)
        result = env.data.xSArmStatus
        assert result.res == "ERR"
        assert result.error is not None
        error = result.error
        assert error.code == "ERR_ZONE_OPEN"
        assert error.type == "ZONE"
        assert error.allow_forcing is True
        assert error.exceptions_number == 2
        assert error.reference_id == "ref-err-001"
        assert error.suid == "suid-abc"

    def test_panel_error_alias_allow_forcing(self):
        """allowForcing (camelCase) maps to allow_forcing (snake_case)."""
        error = PanelError.model_validate({"allowForcing": True, "suid": "s1"})
        assert error.allow_forcing is True
        assert error.suid == "s1"

    def test_panel_error_all_optional(self):
        error = PanelError.model_validate({})
        assert error.code is None
        assert error.type is None
        assert error.allow_forcing is None
        assert error.exceptions_number is None
        assert error.reference_id is None
        assert error.suid is None


# ── SmartlockConfigEnvelope ───────────────────────────────────────────────────


class TestSmartlockConfigEnvelope:
    def test_parse_with_nested_features(self):
        payload = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "location": "front_door",
                    "deviceId": "dev-lock-001",
                    "referenceId": "ref-lock-001",
                    "zoneId": "zone-3",
                    "serialNumber": "SN-LOCK-001",
                    "family": "LOCK_V2",
                    "label": "Front Door",
                    "features": {
                        "holdBackLatchTime": 5,
                        "calibrationType": 1,
                        "autolock": {
                            "active": True,
                            "timeout": 30,
                        },
                    },
                }
            }
        }
        env = SmartlockConfigEnvelope.model_validate(payload)
        lock = env.data.xSGetSmartlockConfig
        assert lock.res == "OK"
        assert lock.device_id == "dev-lock-001"
        assert lock.reference_id == "ref-lock-001"
        assert lock.zone_id == "zone-3"
        assert lock.serial_number == "SN-LOCK-001"
        assert lock.family == "LOCK_V2"
        assert lock.label == "Front Door"
        assert lock.features is not None
        assert lock.features.hold_back_latch_time == 5
        assert lock.features.calibration_type == 1
        assert lock.features.autolock is not None
        assert lock.features.autolock.active is True
        assert lock.features.autolock.timeout == 30

    def test_parse_without_features(self):
        payload = {
            "data": {
                "xSGetSmartlockConfig": {
                    "res": "OK",
                    "deviceId": "dev-lock-002",
                    "referenceId": "ref-lock-002",
                    "zoneId": "zone-1",
                    "serialNumber": "SN-LOCK-002",
                }
            }
        }
        env = SmartlockConfigEnvelope.model_validate(payload)
        assert env.data.xSGetSmartlockConfig.features is None


# ── ThumbnailEnvelope ─────────────────────────────────────────────────────────


class TestThumbnailEnvelope:
    def test_parse_full_response(self):
        payload = {
            "data": {
                "xSGetThumbnail": {
                    "idSignal": "sig-thumb-001",
                    "deviceCode": "QR",
                    "deviceAlias": "Front Door Camera",
                    "timestamp": "2024-01-15T08:00:00",
                    "signalType": "IMAGE",
                    "image": "base64data==",
                }
            }
        }
        env = ThumbnailEnvelope.model_validate(payload)
        thumb = env.data.xSGetThumbnail
        assert thumb.id_signal == "sig-thumb-001"
        assert thumb.device_code == "QR"
        assert thumb.device_alias == "Front Door Camera"
        assert thumb.timestamp == "2024-01-15T08:00:00"
        assert thumb.signal_type == "IMAGE"
        assert thumb.image == "base64data=="

    def test_parse_all_none(self):
        payload = {"data": {"xSGetThumbnail": {}}}
        env = ThumbnailEnvelope.model_validate(payload)
        thumb = env.data.xSGetThumbnail
        assert thumb.id_signal is None
        assert thumb.image is None


# ── ErrorResponse ─────────────────────────────────────────────────────────────


class TestErrorResponse:
    def test_parse_graphql_error_with_data(self):
        payload = {
            "errors": [
                {
                    "message": "Unauthorized",
                    "data": {
                        "reason": "Token expired",
                        "status": 401,
                        "needDeviceAuthorization": True,
                        "auth-otp-hash": "otp-hash-abc",
                        "auth-phones": [
                            {"id": 1, "phone": "+34 555 000 111"},
                        ],
                    },
                }
            ]
        }
        err = ErrorResponse.model_validate(payload)
        assert len(err.errors) == 1
        error = err.errors[0]
        assert error.message == "Unauthorized"
        assert error.data is not None
        data = error.data
        assert data.reason == "Token expired"
        assert data.status == 401
        assert data.need_device_authorization is True
        assert data.auth_otp_hash == "otp-hash-abc"
        assert data.auth_phones is not None
        assert len(data.auth_phones) == 1
        assert data.auth_phones[0]["phone"] == "+34 555 000 111"

    def test_parse_simple_error_no_data(self):
        payload = {"errors": [{"message": "Internal Server Error"}]}
        err = ErrorResponse.model_validate(payload)
        assert len(err.errors) == 1
        assert err.errors[0].message == "Internal Server Error"
        assert err.errors[0].data is None

    def test_parse_multiple_errors(self):
        payload = {
            "errors": [
                {"message": "Error one"},
                {"message": "Error two"},
            ]
        }
        err = ErrorResponse.model_validate(payload)
        assert len(err.errors) == 2
        assert err.errors[0].message == "Error one"
        assert err.errors[1].message == "Error two"

    def test_graphql_error_data_alias_mapping(self):
        """Verify hyphenated aliases auth-otp-hash and auth-phones are parsed."""
        data = GraphQLErrorData.model_validate(
            {
                "auth-otp-hash": "myhash",
                "auth-phones": [{"id": 2, "phone": "+1 555 9999"}],
                "needDeviceAuthorization": False,
            }
        )
        assert data.auth_otp_hash == "myhash"
        assert data.auth_phones is not None
        assert data.auth_phones[0]["id"] == 2
        assert data.need_device_authorization is False
