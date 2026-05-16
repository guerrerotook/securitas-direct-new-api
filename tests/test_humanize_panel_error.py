"""Tests for ``humanize_panel_error_msg`` — turns the raw
``alarm-manager.error_*[#zone_id]`` strings returned by the panel into
something a user can read in a notification."""

from __future__ import annotations

from custom_components.securitas.verisure_owa_api.client._alarm import (
    humanize_panel_error_msg,
)


class TestKnownErrorCodes:
    """Recognised error codes get a curated human-readable label."""

    def test_open_zone_with_zone_identifier(self) -> None:
        """The case from the user's report: BLOCKING + open_zone with a zone id."""
        out = humanize_panel_error_msg(
            "alarm-manager.error_mg_open_zone#Pl_Home_Cocina_Puertajardi"
        )
        assert out == "Open zone (Pl / Home / Cocina / Puertajardi)"

    def test_open_zone_without_zone_identifier(self) -> None:
        """If the panel omits the zone-id suffix, we still translate the code."""
        assert (
            humanize_panel_error_msg("alarm-manager.error_mg_open_zone") == "Open zone"
        )

    def test_no_response(self) -> None:
        """Panel didn't respond — already used as a known code elsewhere
        in hub.py (_ERR_NO_RESPONSE)."""
        assert (
            humanize_panel_error_msg("alarm-manager.error_no_response_to_request")
            == "No response from panel"
        )

    def test_status_not_found(self) -> None:
        assert (
            humanize_panel_error_msg("alarm-manager.error_status_not_found")
            == "Status not found"
        )


class TestUnknownErrorCodes:
    """Unknown error codes fall back to a cleaned-up version of the raw
    code: the ``alarm-manager.error_`` prefix is stripped, underscores
    become spaces, the first letter is capitalised, and any ``#zone_id``
    suffix is shown as a slash-separated path."""

    def test_unknown_code_no_suffix(self) -> None:
        assert (
            humanize_panel_error_msg("alarm-manager.error_some_new_code")
            == "Some new code"
        )

    def test_unknown_code_with_suffix(self) -> None:
        assert (
            humanize_panel_error_msg(
                "alarm-manager.error_some_new_code#Pl_Floor1_Window"
            )
            == "Some new code (Pl / Floor1 / Window)"
        )

    def test_unknown_code_single_word(self) -> None:
        assert humanize_panel_error_msg("alarm-manager.error_foo") == "Foo"


class TestBareAlarmManagerCodeWithErrorType:
    """The panel also returns terse codes like ``alarm-manager.errdca3`` (no
    ``error_`` prefix, no human-readable suffix). For these, the ``error``
    dict's ``type`` field is the only useful context we have — surface it
    alongside the raw code so the user can quote both to support."""

    def test_technical_error_with_bare_code(self) -> None:
        """User-reported case: TECHNICAL_ERROR with a 5-char bare code."""
        out = humanize_panel_error_msg(
            "alarm-manager.errdca3",
            error={"code": "alarm-manager.errdca3", "type": "TECHNICAL_ERROR"},
        )
        assert out == "Technical error (alarm-manager.errdca3)"

    def test_blocking_with_bare_code(self) -> None:
        """A BLOCKING terse code, in case the panel emits one."""
        out = humanize_panel_error_msg(
            "alarm-manager.errxyz",
            error={"code": "alarm-manager.errxyz", "type": "BLOCKING"},
        )
        assert out == "Blocking error (alarm-manager.errxyz)"

    def test_unknown_error_type_with_bare_code(self) -> None:
        """Unknown error type → title-case fallback for the label."""
        out = humanize_panel_error_msg(
            "alarm-manager.errqqq",
            error={"code": "alarm-manager.errqqq", "type": "WEIRD_NEW_TYPE"},
        )
        assert out == "Weird new type (alarm-manager.errqqq)"

    def test_bare_code_without_error_dict(self) -> None:
        """If the caller doesn't pass the error dict, we have no context —
        strip the ``alarm-manager.`` prefix and title-case the rest."""
        assert humanize_panel_error_msg("alarm-manager.errdca3") == "Errdca3"

    def test_bare_code_with_error_dict_missing_type(self) -> None:
        """error dict present but no ``type`` key — same fallback as no dict."""
        assert (
            humanize_panel_error_msg(
                "alarm-manager.errdca3", error={"code": "alarm-manager.errdca3"}
            )
            == "Errdca3"
        )


class TestStructuredErrorFormStillWorks:
    """The ``error`` dict is also passed when the structured ``error_*#zone``
    form is used. The dict must NOT interfere with that path — the structured
    form's parsed output should win."""

    def test_structured_form_ignores_error_dict(self) -> None:
        out = humanize_panel_error_msg(
            "alarm-manager.error_mg_open_zone#Pl_Home_Cocina_Puertajardi",
            error={"code": "alarm-manager.usm3", "type": "BLOCKING"},
        )
        # The structured form's curated label wins; the error dict is ignored.
        assert out == "Open zone (Pl / Home / Cocina / Puertajardi)"


class TestPassThroughForNonPanelMessages:
    """Messages that don't look like panel error codes pass through unchanged."""

    def test_empty_string(self) -> None:
        assert humanize_panel_error_msg("") == ""

    def test_arbitrary_text(self) -> None:
        assert humanize_panel_error_msg("Connection reset") == "Connection reset"

    def test_msg_without_alarm_manager_prefix(self) -> None:
        """Some other domain's error format — return as-is rather than
        applying our parser to it."""
        assert (
            humanize_panel_error_msg("auth-service.error_invalid_token")
            == "auth-service.error_invalid_token"
        )

    def test_alarm_manager_msg_that_is_not_an_error(self) -> None:
        """alarm-manager.processed.request etc. — not an error_* shape."""
        assert (
            humanize_panel_error_msg("alarm-manager.processed.request")
            == "alarm-manager.processed.request"
        )
