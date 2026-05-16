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
