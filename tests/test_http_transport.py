"""Tests for HttpTransport — pure HTTP transport layer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiohttp import ClientConnectorDNSError

from custom_components.securitas.securitas_direct_new_api.exceptions import (
    SecuritasDirectError,
    WAFBlockedError,
)
from custom_components.securitas.securitas_direct_new_api.http_transport import (
    HttpTransport,
)


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_response(*, status: int = 200, text: str = '{"ok": true}', headers=None):
    """Build a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.text = AsyncMock(return_value=text)
    resp.headers = headers or {}
    return resp


def _mock_post(session: MagicMock, responses: list):
    """Wire session.post to return successive mock responses.

    Each entry in *responses* is either:
      - a mock response object  (returned via the context-manager)
      - an exception class/instance (raised on __aenter__)
    """
    it = iter(responses)

    def _factory(*_a, **_kw):
        cm = AsyncMock()
        item = next(it)
        if isinstance(item, BaseException) or (
            isinstance(item, type) and issubclass(item, BaseException)
        ):
            cm.__aenter__ = AsyncMock(side_effect=item)
        else:
            cm.__aenter__ = AsyncMock(return_value=item)
        cm.__aexit__ = AsyncMock(return_value=False)
        return cm

    session.post = MagicMock(side_effect=_factory)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def session():
    return MagicMock()


@pytest.fixture
def transport(session):
    return HttpTransport(session=session, base_url="https://api.example.com/graphql")


# ── Tests ───────────────────────────────────────────────────────────────────


class TestHttpTransport:
    """Tests for HttpTransport.execute."""

    async def test_successful_json_post(self, transport, session):
        """Successful POST returns the parsed JSON dict."""
        body = {"data": {"greeting": "hello"}}
        _mock_post(session, [_make_response(text=json.dumps(body))])

        result = await transport.execute(
            content={"query": "{ greeting }"},
            headers={"X-Custom": "value"},
        )

        assert result == body
        # Verify the POST was made with the right URL and merged headers
        _, kwargs = session.post.call_args
        assert kwargs["json"] == {"query": "{ greeting }"}
        assert "User-Agent" in kwargs["headers"]
        assert kwargs["headers"]["content-type"] == "application/json; charset=utf-8"
        assert kwargs["headers"]["X-Custom"] == "value"

    async def test_dns_retry_succeeds_on_second_attempt(self, transport, session):
        """DNS error on first attempt is retried; success on second attempt."""
        dns_err = ClientConnectorDNSError(
            connection_key=MagicMock(), os_error=OSError("DNS failed")
        )
        ok = _make_response(text='{"ok": true}')
        _mock_post(session, [dns_err, ok])

        with patch(
            "custom_components.securitas.securitas_direct_new_api.http_transport.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            result = await transport.execute(content={}, headers={})

        assert result == {"ok": True}
        mock_sleep.assert_awaited_once_with(2)
        assert session.post.call_count == 2

    async def test_dns_failure_raises_after_second_attempt(self, transport, session):
        """Two consecutive DNS errors raise SecuritasDirectError."""
        dns_err1 = ClientConnectorDNSError(
            connection_key=MagicMock(), os_error=OSError("DNS failed")
        )
        dns_err2 = ClientConnectorDNSError(
            connection_key=MagicMock(), os_error=OSError("DNS failed again")
        )
        _mock_post(session, [dns_err1, dns_err2])

        with patch(
            "custom_components.securitas.securitas_direct_new_api.http_transport.asyncio.sleep",
            new_callable=AsyncMock,
        ):
            with pytest.raises(SecuritasDirectError, match="Connection error"):
                await transport.execute(content={}, headers={})

    async def test_rate_limit_retry_with_retry_after(self, transport, session):
        """403 with Retry-After header retries after the specified delay."""
        fail = _make_response(
            status=403,
            text="<html>rate limited</html>",
            headers={"Retry-After": "7"},
        )
        ok = _make_response(text='{"retried": true}')
        _mock_post(session, [fail, ok])

        with patch(
            "custom_components.securitas.securitas_direct_new_api.http_transport.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            result = await transport.execute(content={}, headers={})

        assert result == {"retried": True}
        mock_sleep.assert_awaited_once_with(7)

    async def test_waf_block_raises_immediately(self, transport, session):
        """Incapsula WAF block raises WAFBlockedError without retry."""
        waf_html = (
            '<html><body><iframe src="/_Incapsula_Resource?CWUDNSAI=23">'
            "Request unsuccessful.</iframe></body></html>"
        )
        resp = _make_response(status=403, text=waf_html)
        _mock_post(session, [resp])

        with pytest.raises(WAFBlockedError):
            await transport.execute(content={}, headers={})

        # Only one call — no retry on WAF block
        session.post.assert_called_once()

    @pytest.mark.parametrize("status_code", [400, 404, 500, 502, 503])
    async def test_http_error_raises_with_status(self, transport, session, status_code):
        """HTTP status >= 400 raises SecuritasDirectError with http_status set."""
        resp = _make_response(status=status_code, text="error body")
        _mock_post(session, [resp])

        with pytest.raises(SecuritasDirectError) as exc_info:
            await transport.execute(content={}, headers={})

        assert exc_info.value.http_status == status_code

    async def test_json_parse_error_raises(self, transport, session):
        """Non-JSON response body raises SecuritasDirectError."""
        resp = _make_response(status=200, text="this is not json {{{")
        _mock_post(session, [resp])

        with pytest.raises(SecuritasDirectError):
            await transport.execute(content={}, headers={})

    async def test_403_without_retry_after_defaults_to_2s(self, transport, session):
        """403 without Retry-After header defaults to 2s delay."""
        fail = _make_response(status=403, text="<html>blocked</html>", headers={})
        ok = _make_response(text='{"ok": true}')
        _mock_post(session, [fail, ok])

        with patch(
            "custom_components.securitas.securitas_direct_new_api.http_transport.asyncio.sleep",
            new_callable=AsyncMock,
        ) as mock_sleep:
            await transport.execute(content={}, headers={})

        mock_sleep.assert_awaited_once_with(2)

    async def test_caller_headers_override_defaults(self, transport, session):
        """Caller-provided headers can override the default User-Agent."""
        _mock_post(session, [_make_response()])

        await transport.execute(
            content={},
            headers={"User-Agent": "CustomAgent/1.0"},
        )

        _, kwargs = session.post.call_args
        assert kwargs["headers"]["User-Agent"] == "CustomAgent/1.0"


class TestSanitizeResponseForLog:
    """Tests for _sanitize_response_for_log."""

    def test_truncates_known_keys(self):
        from custom_components.securitas.securitas_direct_new_api.http_transport import (
            _sanitize_response_for_log,
        )

        raw = json.dumps(
            {"hours": [{"h": "08:00"}, {"h": "09:00"}], "image": "base64data..."}
        )
        sanitized = json.loads(_sanitize_response_for_log(raw))
        assert sanitized["hours"] == ["..."]
        assert sanitized["image"] == "..."

    def test_non_json_returns_as_is(self):
        from custom_components.securitas.securitas_direct_new_api.http_transport import (
            _sanitize_response_for_log,
        )

        raw = "not json"
        assert _sanitize_response_for_log(raw) == "not json"
