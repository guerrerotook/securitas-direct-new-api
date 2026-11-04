#!/usr/bin/env python3
"""Install the newest Home Assistant and its test harness for a CI channel.

Usage:
    python scripts/ci_ha_install.py {stable,beta,dev}
        [--requirements FILE ...] [--extra PKG ...]

The script exits non-zero if it does not end up on the version it asked for,
because a later install can silently replace Home Assistant with another version.
The calling workflow decides whether that blocks the job.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

HA_PACKAGE = "homeassistant"
NEW_HARNESS = "pytest-homeassistant"
OLD_HARNESS = "pytest-homeassistant-custom-component"
CORE_REPOSITORY = "https://github.com/home-assistant/core.git"

FIRST_YEAR = 2026
NEW_HARNESS_SINCE = (2026, 11)
DEV_STAGE, BETA_STAGE, FINAL_STAGE = 0, 1, 2

VERSION_PATTERN = re.compile(r"(\d{4})\.(\d{1,2})\.(\d+)(?:b(\d+)|\.dev(\d+))?")
PRINT_VERSION = "from homeassistant.const import __version__; print(__version__)"


def parse_version(text: str) -> tuple[int, int, int, int, int] | None:
    """Return a sort key, or None for anything that is not a usable HA version."""
    match = VERSION_PATTERN.fullmatch(text)
    if match is None:
        return None
    year, month, patch, beta, dev = match.groups()
    if int(year) < FIRST_YEAR:
        return None
    if dev is not None:
        return int(year), int(month), int(patch), DEV_STAGE, int(dev)
    if beta is not None:
        return int(year), int(month), int(patch), BETA_STAGE, int(beta)
    return int(year), int(month), int(patch), FINAL_STAGE, 0


def uses_new_harness(version: str) -> bool:
    """Return whether this HA version is tested with the new harness."""
    parsed = parse_version(version)
    return parsed is not None and parsed[:2] >= NEW_HARNESS_SINCE


def is_stable(version: str) -> bool:
    """Return whether a parsable version is a final release."""
    return parse_version(version)[3] == FINAL_STAGE


def usable_versions(pypi_json: dict) -> list[str]:
    """Return the parsable releases that have files left, newest first."""
    versions = []
    for version, files in pypi_json["releases"].items():
        yanked = all(file.get("yanked") for file in files)
        if parse_version(version) is not None and not yanked:
            versions.append(version)
    return sorted(versions, key=parse_version, reverse=True)


def latest_versions(pypi_json: dict) -> tuple[str, str]:
    """Return the latest stable version and the newest of any kind."""
    versions = usable_versions(pypi_json)
    stable = [version for version in versions if is_stable(version)]
    if not stable:
        raise ValueError("PyPI lists no usable stable release")
    return stable[0], versions[0]


def pick_target(
    channel: str,
    ha_json: dict,
    harness_json: dict,
) -> tuple[str, bool]:
    """Return the newest installable version, and whether it is behind HA's newest.

    The two packages publish minutes apart, so the harness can briefly lag.
    """
    latest_stable, newest = latest_versions(ha_json)
    wanted = latest_stable if channel == "stable" else newest
    harness_versions = usable_versions(harness_json)
    for version in usable_versions(ha_json):
        if channel == "stable" and not is_stable(version):
            continue
        if not uses_new_harness(version) or version in harness_versions:
            return version, version != wanted
    raise ValueError(f"No version for channel {channel} has a matching harness")


def check_channel(channel: str, installed: str, target: str | None) -> str | None:
    """Return None when the installed version is right, else an error message."""
    if channel == "dev":
        if ".dev" in installed:
            return None
        return f"Channel dev expected a .dev version, found {installed}"
    if installed == target:
        return None
    return f"Channel {channel} expected {target}, found {installed}"


def fetch_pypi(package: str) -> dict:
    """Return a package's PyPI JSON document."""
    url = f"https://pypi.org/pypi/{package}/json"
    with urllib.request.urlopen(url, timeout=30) as response:
        return json.load(response)


def run(command: list[str]) -> None:
    """Run a command, stopping the script if it fails."""
    subprocess.run(command, check=True)


def pip_install(*arguments: str) -> None:
    """Install into the environment running this script."""
    run([sys.executable, "-m", "pip", "install", *arguments])


def install_release(channel: str) -> str:
    """Install a published HA and harness, returning the HA version chosen."""
    target, behind = pick_target(
        channel,
        fetch_pypi(HA_PACKAGE),
        fetch_pypi(NEW_HARNESS),
    )
    if behind:
        print(f"::warning::{NEW_HARNESS} lags Home Assistant: using {target}")
    pip_install(f"{HA_PACKAGE}=={target}")
    if uses_new_harness(target):
        pip_install(f"{NEW_HARNESS}=={target}")
    else:
        pip_install(OLD_HARNESS)
    return target


def install_dev() -> None:
    """Install HA and the harness from the tip of the core repository."""
    temp = os.environ.get("RUNNER_TEMP") or tempfile.mkdtemp()
    core = Path(temp) / "ha-core"
    run(["git", "clone", "--depth", "1", CORE_REPOSITORY, str(core)])
    pip_install(str(core), str(core / "packages" / NEW_HARNESS))


def main(argv: list[str] | None = None) -> int:
    """Install the channel's packages and check the version that ended up there."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("channel", choices=["stable", "beta", "dev"])
    parser.add_argument("--requirements", action="append", default=[])
    parser.add_argument("--extra", action="append", default=[])
    args = parser.parse_args(argv)

    target = None
    if args.channel == "dev":
        install_dev()
    else:
        target = install_release(args.channel)

    extras = []
    for requirements in args.requirements:
        extras += ["-r", requirements]
    extras += args.extra
    if extras:
        pip_install(*extras)

    result = subprocess.run(
        [sys.executable, "-c", PRINT_VERSION],
        check=True,
        capture_output=True,
        text=True,
    )
    installed = result.stdout.strip()
    error = check_channel(args.channel, installed, target)
    if error is not None:
        print(f"::error::{error}")
        return 1
    print(f"Home Assistant {installed} is installed for channel {args.channel}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
