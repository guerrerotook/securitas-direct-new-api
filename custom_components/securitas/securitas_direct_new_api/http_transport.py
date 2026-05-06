"""Pure HTTP transport layer for the Securitas Direct API.

Sends POST requests with caller-provided headers, handles retries on DNS
errors and rate-limit (403) responses, and detects Incapsula WAF blocks.

This module knows nothing about authentication tokens, GraphQL semantics,
or Securitas business logic.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiohttp import ClientConnectorDNSError, ClientConnectorError, ClientSession

from .exceptions import SecuritasDirectError, WAFBlockedError

_LOGGER = logging.getLogger(__name__)

# Keys whose values should be replaced with a placeholder in debug logs
_LOG_TRUNCATE_KEYS = {"hours", "image", "reg"}

# Standard headers added to every request
_DEFAULT_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        " AppleWebKit/537.36 (KHTML, like Gecko)"
        " Chrome/102.0.5005.124 Safari/537.36"
        " Edg/102.0.1245.41"
    ),
    "content-type": "application/json; charset=utf-8",
}


def _sanitize_response_for_log(response_text: str) -> str:
    """Replace large fields in a JSON response with a placeholder for logging."""
    try:
        data = json.loads(response_text)
    except (json.JSONDecodeError, ValueError):
        return response_text

    def _truncate(obj: Any) -> Any:
        if isinstance(obj, dict):
            return {
                k: (["..."] if isinstance(v, list) else "...")
                if k in _LOG_TRUNCATE_KEYS
                else _truncate(v)
                for k, v in obj.items()
            }
        if isinstance(obj, list):
            return [_truncate(item) for item in obj]
        return obj

    return json.dumps(_truncate(data))


class HttpTransport:
    """Send POST requests with retries, WAF detection, and JSON parsing.

    This is the bottom transport layer — it has no knowledge of auth tokens,
    GraphQL structure, or Securitas API semantics.
    """

    def __init__(self, session: ClientSession, base_url: str) -> None:
        self._session = session
        self._base_url = base_url

    async def execute(
        self, content: dict[str, Any], headers: dict[str, str]
    ) -> dict[str, Any]:
        """POST *content* as JSON to the base URL and return the parsed response.

        Args:
            content: Request body (serialised as JSON).
            headers: Caller-provided headers (merged on top of defaults).

        Returns:
            The parsed JSON response as a dict.

        Raises:
            WAFBlockedError: Incapsula WAF block detected (no retry).
            SecuritasDirectError: HTTP error, connection error, or JSON parse failure.
        """
        merged_headers = {**_DEFAULT_HEADERS, **headers}

        response_text = ""
        for attempt in range(2):
            try:
                async with self._session.post(
                    self._base_url, headers=merged_headers, json=content
                ) as response:
                    http_status: int = response.status
                    response_text = await response.text()
                    response_headers = response.headers
            except ClientConnectorError as err:
                os_err = err.os_error or err.strerror or "unknown"
                if isinstance(err, ClientConnectorDNSError) and attempt == 0:
                    _LOGGER.debug("DNS timeout, retrying once: %s", err)
                    await asyncio.sleep(2)
                    continue
                raise SecuritasDirectError(
                    f"Connection error with URL {self._base_url}: {os_err}",
                ) from err

            _LOGGER.debug(
                "response=%s",
                _sanitize_response_for_log(response_text),
            )

            if http_status == 403 and attempt == 0:
                # Incapsula WAF blocks return HTML — retrying just extends the
                # block.  Raise immediately so callers can back off properly.
                if "_Incapsula_Resource" in response_text:
                    _LOGGER.warning(
                        "HTTP 403 WAF block (not retrying — WAF blocks require longer backoff)"
                    )
                    raise WAFBlockedError(
                        f"HTTP {http_status} WAF block from {self._base_url}",
                        http_status=http_status,
                    )

                retry_after = response_headers.get("Retry-After")
                try:
                    delay = int(retry_after) if retry_after else 2
                except (ValueError, TypeError):
                    delay = 2
                _LOGGER.warning("HTTP 403, retrying in %ds", delay)
                await asyncio.sleep(delay)
                continue

            if http_status >= 400:
                _LOGGER.debug(
                    "HTTP %d error: %s",
                    http_status,
                    response_text[:500],
                )
                raise SecuritasDirectError(
                    f"HTTP {http_status} from {self._base_url}",
                    http_status=http_status,
                )

            break  # Success

        try:
            return json.loads(response_text)
        except json.JSONDecodeError as err:
            _LOGGER.error(
                "Failed to parse JSON response: %s",
                _sanitize_response_for_log(response_text),
            )
            raise SecuritasDirectError(err.msg) from err
