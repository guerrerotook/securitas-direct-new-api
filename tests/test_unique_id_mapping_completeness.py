"""CI guardrail: every legacy unique-id format used in the codebase
maps cleanly through old_to_new_unique_id."""

from __future__ import annotations

import re
from pathlib import Path

from custom_components.verisure_owa.migrate import old_to_new_unique_id

PLATFORM_DIR = Path(__file__).parent.parent / "custom_components" / "verisure_owa"

# Match _attr_unique_id = (f"..."), _attr_unique_id = f"...", and
# _attr_unique_id: str | None = f"..." (typed-annotation form)
_UNIQUE_ID_RE = re.compile(
    r'_attr_unique_id\s*(?::[^=]+?)?\s*=\s*\(?\s*\n?\s*f"([^"]+)"',
    re.M,
)
# Match identifiers={(DOMAIN, f"...")} and (DOMAIN, f"...") in via_device tuples
_IDENTIFIER_RE = re.compile(r'\(DOMAIN,\s*\n?\s*f"([^"]+)"\s*\)', re.M)


def _collect_unique_id_format_strings() -> set[str]:
    """Return every f-string used as a unique_id or device identifier value
    in platform code."""
    formats: set[str] = set()
    for path in PLATFORM_DIR.glob("*.py"):
        if path.name == "migrate.py":
            continue
        text = path.read_text()
        formats.update(_UNIQUE_ID_RE.findall(text))
        formats.update(_IDENTIFIER_RE.findall(text))
    return formats


def _instantiate_format(fmt: str) -> str:
    """Replace placeholders in an f-string template with realistic values."""
    return (
        fmt.replace("{installation.number}", "100001")
        .replace("{self._installation.number}", "100001")
        .replace("{self.installation.number}", "100001")
        .replace("{installation.alias}", "Home")
        .replace("{service_id}", "5")
        .replace("{camera_device.zone_id}", "YR08")
        .replace("{device_id}", "01")
        .replace("{self._device_id}", "01")
        # Sub-panel unique_ids inherit from parent: substitute a realistic v5 base.
        .replace("{self._attr_unique_id}", "v5_verisure_owa.100001")
        .replace("{self._SUFFIX}", "_interior")
    )


def test_every_unique_id_format_is_v5_compatible():
    """Every f-string used to build a unique_id starts with v5_verisure_owa."""
    formats = _collect_unique_id_format_strings()
    assert formats, "No unique-id formats found — regex broken?"
    # Sanity check: the alarm panel's typed-annotation format is in scope
    assert any(fmt == "v5_verisure_owa.{installation.number}" for fmt in formats), (
        f"Alarm panel format missing from regex coverage; got: {formats}"
    )
    for fmt in formats:
        instantiated = _instantiate_format(fmt)
        assert instantiated.startswith("v5_verisure_owa."), (
            f"Unique-id format does not start with v5_verisure_owa: "
            f"{fmt!r} → {instantiated!r}"
        )


def test_every_unique_id_format_is_idempotent_through_mapping():
    """Passing a v5 form through old_to_new_unique_id returns it unchanged."""
    formats = _collect_unique_id_format_strings()
    for fmt in formats:
        instantiated = _instantiate_format(fmt)
        assert old_to_new_unique_id(instantiated) == instantiated, (
            f"Mapping not idempotent for {instantiated!r}"
        )
