"""Tests for the script CI uses to install Home Assistant and its test harness."""

import subprocess
import sys

import pytest

import scripts.ci_ha_install as ci_ha_install


def pypi(*versions, yanked=(), empty=()):
    """Build the part of a PyPI JSON document that the script reads."""
    releases = {}
    for version in versions:
        releases[version] = [{"yanked": version in yanked}]
    for version in empty:
        releases[version] = []
    return {"releases": releases}


@pytest.mark.parametrize(
    ("older", "newer"),
    [
        ("2026.11.0.dev0", "2026.11.0b4"),
        ("2026.11.0b4", "2026.11.0"),
        ("2026.11.0b4", "2026.11.0b10"),
        ("2026.11.0.dev0", "2026.11.0.dev202611040234"),
        ("2026.9.4", "2026.10.0"),
        ("2026.11.0", "2026.11.1b0"),
        ("2026.12.3", "2027.1.0"),
    ],
)
def test_parse_version_orders(older, newer):
    assert ci_ha_install.parse_version(older) < ci_ha_install.parse_version(newer)


@pytest.mark.parametrize(
    "text",
    ["0.19", "0.7.0.1", "0.7.0rc1", "0.1.3", "2025.2.0", "2026.11", "2026.11.0rc1", ""],
)
def test_parse_version_skips_odd_and_old_versions(text):
    assert ci_ha_install.parse_version(text) is None


@pytest.mark.parametrize(
    ("version", "expected"),
    [
        ("2025.2.0", False),
        ("2026.10.4", False),
        ("2026.11.0.dev0", True),
        ("2026.11.0b4", True),
        ("2026.11.0", True),
        ("2027.1.0", True),
        ("not-a-version", False),
    ],
)
def test_uses_new_harness(version, expected):
    assert ci_ha_install.uses_new_harness(version) is expected


def test_latest_versions_splits_stable_from_prerelease():
    document = pypi("2026.10.3", "2026.10.4", "2026.11.0b3", "2026.11.0b4")
    assert ci_ha_install.latest_versions(document) == ("2026.10.4", "2026.11.0b4")


def test_latest_versions_compares_numbers_not_text():
    document = pypi("2026.9.4", "2026.10.4", "2026.11.0b9", "2026.11.0b10")
    assert ci_ha_install.latest_versions(document) == ("2026.10.4", "2026.11.0b10")


def test_latest_versions_newest_can_be_the_stable_release():
    document = pypi("2026.11.0b4", "2026.11.0")
    assert ci_ha_install.latest_versions(document) == ("2026.11.0", "2026.11.0")


def test_latest_versions_skips_yanked():
    document = pypi(
        "2026.10.4",
        "2026.10.5",
        "2026.11.0b4",
        "2026.11.0b5",
        yanked=("2026.10.5", "2026.11.0b5"),
    )
    assert ci_ha_install.latest_versions(document) == ("2026.10.4", "2026.11.0b4")


def test_latest_versions_skips_unparsable_and_fileless_releases():
    document = pypi("0.19", "0.7.0.1", "0.7.0rc1", "2026.10.4", empty=("2026.10.5",))
    assert ci_ha_install.latest_versions(document) == ("2026.10.4", "2026.10.4")


def test_latest_versions_raises_when_nothing_is_usable():
    with pytest.raises(ValueError, match="stable"):
        ci_ha_install.latest_versions(pypi("0.1.3"))


def test_pick_target_stable_before_the_harness_applies():
    ha = pypi("2026.10.4", "2026.11.0b4")
    harness = pypi("0.1.3", "2026.11.0b4")
    assert ci_ha_install.pick_target("stable", ha, harness) == ("2026.10.4", False)


def test_pick_target_beta_on_both_lists():
    ha = pypi("2026.10.4", "2026.11.0b4")
    harness = pypi("0.1.3", "2026.11.0b4")
    assert ci_ha_install.pick_target("beta", ha, harness) == ("2026.11.0b4", False)


def test_pick_target_stable_falls_back_when_the_harness_lags():
    ha = pypi("2026.10.4", "2026.11.0", "2026.11.1")
    harness = pypi("2026.11.0b4", "2026.11.0")
    assert ci_ha_install.pick_target("stable", ha, harness) == ("2026.11.0", True)


def test_pick_target_stable_falls_back_to_the_old_harness():
    ha = pypi("2026.10.4", "2026.11.0b4", "2026.11.0")
    harness = pypi("2026.11.0b4")
    assert ci_ha_install.pick_target("stable", ha, harness) == ("2026.10.4", True)


def test_pick_target_beta_falls_back_when_the_harness_lags():
    ha = pypi("2026.10.4", "2026.11.0b4", "2026.11.0b5")
    harness = pypi("2026.11.0b4")
    assert ci_ha_install.pick_target("beta", ha, harness) == ("2026.11.0b4", True)


def test_pick_target_ignores_yanked_harness_releases():
    ha = pypi("2026.11.0", "2026.11.1")
    harness = pypi("2026.11.0", "2026.11.1", yanked=("2026.11.1",))
    assert ci_ha_install.pick_target("stable", ha, harness) == ("2026.11.0", True)


def test_pick_target_stable_never_lands_on_a_prerelease():
    ha = pypi("2026.11.0b4", "2026.11.0")
    harness = pypi("2026.11.0b4")
    with pytest.raises(ValueError, match="stable"):
        ci_ha_install.pick_target("stable", ha, harness)


@pytest.mark.parametrize(
    ("channel", "installed", "target"),
    [
        ("stable", "2026.10.4", "2026.10.4"),
        ("beta", "2026.11.0b4", "2026.11.0b4"),
        ("dev", "2026.12.0.dev0", None),
    ],
)
def test_check_channel_accepts_the_right_version(channel, installed, target):
    assert ci_ha_install.check_channel(channel, installed, target) is None


@pytest.mark.parametrize(
    ("channel", "installed", "target"),
    [
        ("stable", "2026.10.3", "2026.10.4"),
        ("beta", "2026.10.4", "2026.11.0b4"),
        ("dev", "2026.10.4", None),
    ],
)
def test_check_channel_reports_the_wrong_version(channel, installed, target):
    message = ci_ha_install.check_channel(channel, installed, target)
    assert installed in message
    assert channel in message


class FakeSystem:
    """Stands in for PyPI, pip and git, recording each command."""

    def __init__(self, monkeypatch, installed, ha=None, harness=None):
        self.commands = []
        self.installed = installed
        self.documents = {
            ci_ha_install.HA_PACKAGE: ha,
            ci_ha_install.NEW_HARNESS: harness,
        }
        monkeypatch.setattr(ci_ha_install, "fetch_pypi", self.fetch_pypi)
        monkeypatch.setattr(ci_ha_install.subprocess, "run", self.run)

    def fetch_pypi(self, package):
        return self.documents[package]

    def run(self, command, **_kwargs):
        self.commands.append(command)
        return subprocess.CompletedProcess(command, 0, stdout=f"{self.installed}\n")

    @property
    def pip_arguments(self):
        prefix = [sys.executable, "-m", "pip", "install"]
        return [command[4:] for command in self.commands if command[:4] == prefix]


def test_main_stable_installs_the_old_harness_for_older_ha(monkeypatch, capsys):
    system = FakeSystem(
        monkeypatch,
        "2026.10.4",
        ha=pypi("2026.10.4", "2026.11.0b4"),
        harness=pypi("2026.11.0b4"),
    )
    assert ci_ha_install.main(["stable"]) == 0
    assert system.pip_arguments == [
        ["homeassistant==2026.10.4"],
        ["pytest-homeassistant-custom-component"],
    ]
    assert "::warning::" not in capsys.readouterr().out


def test_main_stable_installs_the_matching_new_harness(monkeypatch):
    system = FakeSystem(
        monkeypatch,
        "2026.11.0",
        ha=pypi("2026.11.0"),
        harness=pypi("2026.11.0"),
    )
    assert ci_ha_install.main(["stable"]) == 0
    assert system.pip_arguments == [
        ["homeassistant==2026.11.0"],
        ["pytest-homeassistant==2026.11.0"],
    ]


def test_main_beta_pins_exactly_without_allowing_other_prereleases(monkeypatch):
    system = FakeSystem(
        monkeypatch,
        "2026.11.0b4",
        ha=pypi("2026.10.4", "2026.11.0b4"),
        harness=pypi("2026.11.0b4"),
    )
    assert ci_ha_install.main(["beta"]) == 0
    assert system.pip_arguments == [
        ["homeassistant==2026.11.0b4"],
        ["pytest-homeassistant==2026.11.0b4"],
    ]
    assert not any("--pre" in arguments for arguments in system.pip_arguments)


def test_main_dev_installs_from_a_clone_of_core(monkeypatch, tmp_path):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    system = FakeSystem(monkeypatch, "2026.12.0.dev0")
    assert ci_ha_install.main(["dev"]) == 0
    core = tmp_path / "ha-core"
    assert system.commands[0] == [
        "git",
        "clone",
        "--depth",
        "1",
        "https://github.com/home-assistant/core.git",
        str(core),
    ]
    assert system.pip_arguments == [
        [str(core), str(core / "packages" / "pytest-homeassistant")],
    ]


def test_main_installs_requirements_and_extras_before_the_check(monkeypatch):
    system = FakeSystem(
        monkeypatch,
        "2026.10.4",
        ha=pypi("2026.10.4"),
        harness=pypi("2026.11.0b4"),
    )
    arguments = [
        "stable",
        "--requirements",
        "one.txt",
        "--requirements",
        "two.txt",
        "--extra",
        "aioesphomeapi>=29.0.0",
        "--extra",
        "pydantic",
    ]
    assert ci_ha_install.main(arguments) == 0
    assert system.pip_arguments[2:] == [
        ["-r", "one.txt", "-r", "two.txt", "aioesphomeapi>=29.0.0", "pydantic"],
    ]
    assert system.commands[-1][:2] == [sys.executable, "-c"]
    assert len(system.pip_arguments) == 3


def test_main_warns_but_passes_when_the_harness_lags(monkeypatch, capsys):
    FakeSystem(
        monkeypatch,
        "2026.11.0b4",
        ha=pypi("2026.10.4", "2026.11.0b4", "2026.11.0b5"),
        harness=pypi("2026.11.0b4"),
    )
    assert ci_ha_install.main(["beta"]) == 0
    assert "::warning::" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("channel", "installed"),
    [("stable", "2026.10.3"), ("beta", "2026.10.4"), ("dev", "2026.10.4")],
)
def test_main_fails_when_a_job_ends_up_on_the_wrong_version(
    monkeypatch,
    tmp_path,
    capsys,
    channel,
    installed,
):
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    FakeSystem(
        monkeypatch,
        installed,
        ha=pypi("2026.10.4", "2026.11.0b4"),
        harness=pypi("2026.11.0b4"),
    )
    assert ci_ha_install.main([channel]) == 1
    assert "::error::" in capsys.readouterr().out
