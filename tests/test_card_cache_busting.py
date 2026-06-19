"""Guard: card JS bare imports stay cache-busted to the manifest version.

`/verisure-owa-panel` is served with ``cache_headers=True`` (long max-age), so
the cards' bare cross-module imports (``verisure-owa-alarm-shared.js``,
``verisure-owa-card-utils.js`` and the legacy shims' entry imports) must carry a
``?v=<version>`` query that tracks the integration version — otherwise a release
serves a hard-cached stale module.

There is an equivalent JS check (``tests-js/integration/card-cache-busting.test.js``),
but that runs in the path-filtered ``js-tests.yml`` workflow, which does NOT fire
on a manifest-only version bump. This Python copy runs in the unfiltered ``CI``
workflow (``tests.yaml``), so it fails on *any* version bump that forgot to
re-stamp the imports (``release.yaml`` re-stamps them automatically; this catches
manual drift before it ships).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_SECURITAS = Path(__file__).parent.parent / "custom_components" / "securitas"
_WWW = _SECURITAS / "www"

# Matches `from "./x.js<query>"` and side-effect `import "./x.js<query>"`.
_IMPORT_RE = re.compile(r'\b(?:from|import)\s+"(\./[A-Za-z0-9._-]+\.js)([^"]*)"')


def _manifest_version() -> str:
    return json.loads((_SECURITAS / "manifest.json").read_text())["version"]


def test_card_import_versions_match_manifest() -> None:
    version = _manifest_version()
    expected = f"?v={version}"
    offenders: dict[str, list[str]] = {}
    for path in sorted(_WWW.glob("*.js")):
        bad = [
            f"{spec}{query}"
            for spec, query in _IMPORT_RE.findall(path.read_text())
            if query != expected
        ]
        if bad:
            offenders[path.name] = bad
    assert not offenders, (
        f"card JS relative imports not stamped {expected} "
        f"(re-stamp to match manifest.json): {offenders}"
    )
