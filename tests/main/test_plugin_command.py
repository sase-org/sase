"""Tests for the ``sase plugin`` command."""

from __future__ import annotations

import argparse
import json
import stat
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig
from sase.main import plugin_handler
from sase.main.parser import create_parser
from sase.plugins.chops import collect_chop_inventory
from sase.plugins.doctor import build_plugin_doctor_report
from sase.plugins.inventory import (
    PluginEntryPointRecord,
    PluginInventory,
    collect_plugin_inventory,
)
from sase.plugins.render import render_plugin_doctor


class _FakeDist:
    def __init__(self, name: str, version: str) -> None:
        self.metadata = {"Name": name, "Version": version}
        self.version = version


class _FakeEntryPoint:
    def __init__(
        self,
        *,
        name: str,
        value: str,
        package: str,
        version: str = "1.2.3",
        load_result: object = None,
        load_error: Exception | None = None,
    ) -> None:
        self.name = name
        self.value = value
        self.dist = _FakeDist(package, version)
        self.load_result = load_result
        self.load_error = load_error
        self.load_calls = 0

    def load(self) -> object:
        self.load_calls += 1
        if self.load_error is not None:
            raise self.load_error
        return self.load_result


def _patch_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    mapping: dict[str, list[_FakeEntryPoint]],
) -> None:
    def fake_entry_points(*, group: str) -> list[_FakeEntryPoint]:
        return mapping.get(group, [])

    monkeypatch.setattr(
        "sase.plugins.inventory.importlib.metadata.entry_points",
        fake_entry_points,
    )


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def test_parser_accepts_plugin_flags() -> None:
    parser = create_parser()

    list_short = parser.parse_args(["plugin", "list", "-j"])
    assert list_short.command == "plugin"
    assert list_short.plugin_subcommand == "list"
    assert list_short.json is True

    list_long = parser.parse_args(["plugin", "list", "--json", "--verbose"])
    assert list_long.plugin_subcommand == "list"
    assert list_long.json is True
    assert list_long.verbose is True

    doctor_short = parser.parse_args(["plugin", "doctor", "-j"])
    assert doctor_short.plugin_subcommand == "doctor"
    assert doctor_short.json is True

    doctor_verbose = parser.parse_args(["plugin", "doctor", "--verbose"])
    assert doctor_verbose.plugin_subcommand == "doctor"
    assert doctor_verbose.verbose is True


def test_inventory_groups_entry_points_and_captures_resource_load_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = _FakeEntryPoint(
        name="provider",
        value="fake_provider:Plugin",
        package="sase-provider",
    )
    resource = _FakeEntryPoint(
        name="resources",
        value="fake_resources",
        package="sase-resources",
        load_error=ImportError("boom"),
    )
    _patch_entry_points(
        monkeypatch,
        {
            "sase_vcs": [provider],
            "sase_xprompts": [resource],
        },
    )

    inventory = collect_plugin_inventory()

    assert provider.load_calls == 0
    assert resource.load_calls == 1
    assert [(dist.package, dist.version) for dist in inventory.distributions] == [
        ("sase-provider", "1.2.3"),
        ("sase-resources", "1.2.3"),
    ]
    resources = [ep for ep in inventory.entry_points if ep.group == "sase_xprompts"]
    assert len(resources) == 1
    assert resources[0].load_status == "error"
    assert "ImportError: boom" == resources[0].load_error


def test_chop_inventory_resolves_missing_agent_and_available_unconfigured(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    _make_executable(scripts_dir / "resolved")

    python_bin = tmp_path / "venv" / "bin"
    python_bin.mkdir(parents=True)
    python_executable = python_bin / "python"
    python_executable.write_text("", encoding="utf-8")
    _make_executable(python_bin / "sase_chop_available")

    monkeypatch.setattr("sase.plugins.chops.sys.executable", str(python_executable))
    monkeypatch.setenv("PATH", "")

    config = AxeConfig(
        chop_script_dirs=[str(scripts_dir)],
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                interval=10,
                chops=[
                    ChopConfig(name="resolved", description=""),
                    ChopConfig(name="missing", description=""),
                    ChopConfig(name="agented", description="", agent="do-work"),
                ],
            )
        },
    )

    inventory = collect_chop_inventory(config)

    configured = {(chop.name, chop.status) for chop in inventory.configured_chops}
    assert configured == {
        ("resolved", "configured"),
        ("missing", "missing"),
        ("agented", "agent-backed"),
    }
    resolved = next(
        chop for chop in inventory.configured_chops if chop.name == "resolved"
    )
    assert resolved.resolved_path == str(scripts_dir / "resolved")

    available = inventory.available_unconfigured
    assert len(available) == 1
    assert available[0].name == "available"
    assert available[0].source == "python_bin"
    assert available[0].executable == str(python_bin / "sase_chop_available")


def test_doctor_status_errors_on_resource_load_and_missing_chop() -> None:
    plugin_inventory = PluginInventory(
        entry_points=(
            PluginEntryPointRecord(
                group="sase_xprompts",
                name="broken",
                value="broken",
                package="sase-broken",
                version="1.0",
                load_status="error",
                load_error="ImportError: broken",
            ),
        ),
        distributions=(),
        disabled_env=(),
    )
    chop_inventory = collect_chop_inventory(
        AxeConfig(
            lumberjacks={
                "hooks": LumberjackConfig(
                    name="hooks",
                    interval=10,
                    chops=[ChopConfig(name="missing", description="")],
                )
            }
        )
    )

    report = build_plugin_doctor_report(
        plugin_inventory=plugin_inventory,
        chop_inventory=chop_inventory,
        which_fn=lambda _: None,
    )

    assert report.status == "ERROR"
    assert {check.status for check in report.checks} >= {"ERROR"}
    assert any("Resource entry point" in check.summary for check in report.checks)
    assert any("cannot be resolved" in check.summary for check in report.checks)


def test_handler_json_output_has_schema_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_entry_points(monkeypatch, {})
    monkeypatch.setattr(
        plugin_handler,
        "collect_chop_inventory",
        lambda: collect_chop_inventory(AxeConfig()),
    )

    args = argparse.Namespace(plugin_subcommand="list", json=True, verbose=False)
    with pytest.raises(SystemExit) as exc:
        plugin_handler.handle_plugin_command(args)

    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "list"
    assert "plugins" in payload
    assert "chops" in payload
    assert "checks" in payload


def test_human_doctor_output_has_sections_and_no_traceback() -> None:
    plugin_inventory = PluginInventory(
        entry_points=(
            PluginEntryPointRecord(
                group="sase_vcs",
                name="github",
                value="sase_github:Plugin",
                package="sase-github",
                version="1.0",
                load_status="not_loaded",
            ),
        ),
        distributions=(),
        disabled_env=(),
    )
    chop_inventory = collect_chop_inventory(AxeConfig())
    report = build_plugin_doctor_report(
        plugin_inventory=plugin_inventory,
        chop_inventory=chop_inventory,
        which_fn=lambda _: None,
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=140)

    render_plugin_doctor(report, console=console)

    text = output.getvalue()
    assert "Plugin Doctor" in text
    assert "Checks" in text
    assert "Resource Plugins" in text
    assert "Configured Chops" in text
    assert "Available Unconfigured Chops" in text
    assert "Install Guidance" in text
    assert "gh CLI was not found" in text
    assert "Traceback" not in text
