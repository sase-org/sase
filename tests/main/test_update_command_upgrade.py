"""Tests for the normal ``uv tool upgrade`` update flow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sase.axe.process import AxeStartResult
from sase.main.update_handler import UPDATE_JSON_SCHEMA_VERSION, handle_update_command
from sase.uv_tool.detect import UvToolInstall
from sase.uv_tool.errors import UvCommandFailedError
from sase.uv_tool.runner import UvChangeSet, parse_uv_output
from tests.main.update_command_helpers import (
    _UPGRADE_OUTPUT,
    _args,
    _console,
    _install,
    _text,
    _versions,
)


def test_upgrade_runs_expected_argv_and_renders(tmp_path: Path) -> None:
    seen: dict[str, list[str]] = {}

    def _run(argv: list[str]) -> UvChangeSet:
        seen["argv"] = argv
        return parse_uv_output(_UPGRADE_OUTPUT)

    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert seen["argv"] == ["uv", "tool", "upgrade", "--color", "never", "sase"]
    text = _text(out)
    assert "0.5.0 \u2192 0.6.1" in text
    assert "already current" in text
    assert "Updated sase + 1 plugin" in text


def test_upgrade_json_payload_is_stable(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    clock = iter([10.0, 14.2])
    code = handle_update_command(
        _args(json=True),
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: next(clock),
    )

    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == UPDATE_JSON_SCHEMA_VERSION
    assert payload["dry_run"] is False
    assert payload["changed"] is True
    assert payload["command"] == ["uv", "tool", "upgrade", "--color", "never", "sase"]
    assert payload["elapsed_seconds"] == 4.2
    assert payload["counts"] == {"updated": 2, "already_current": 1, "removed": 0}
    names = [p["name"] for p in payload["packages"]]
    assert names == ["sase", "sase-github", "sase-telegram"]
    sase = payload["packages"][0]
    assert sase["kind"] == "upgraded"
    assert sase["old_version"] == "0.5.0"
    assert sase["new_version"] == "0.6.1"


def test_upgrade_quiet_prints_one_line(tmp_path: Path) -> None:
    out = _console()
    code = handle_update_command(
        _args(quiet=True),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert _text(out).strip() == (
        "Updated sase + 1 plugin in 0.0s \u00b7 1 already current"
    )


def test_managed_upgrade_restarts_axe_when_changed(tmp_path: Path) -> None:
    restart_calls = 0

    def _restart() -> AxeStartResult:
        nonlocal restart_calls
        restart_calls += 1
        return AxeStartResult(status="started", pid=9753)

    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: True,
        restart_axe_fn=_restart,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert restart_calls == 1
    assert "Axe restarted (pid 9753)" in _text(out)


def test_upgrade_noop_says_up_to_date(tmp_path: Path) -> None:
    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: _install(tmp_path),
        run_fn=lambda _argv: parse_uv_output("Nothing to upgrade\n"),
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert "Already up to date" in _text(out)


def test_upgrade_command_failure_exits_one(tmp_path: Path) -> None:
    def _run(argv: list[str]) -> UvChangeSet:
        raise UvCommandFailedError(argv=argv, returncode=2, stderr="No solution found")

    err = _console()
    code = handle_update_command(
        _args(),
        console=_console(),
        err_console=err,
        probe_fn=lambda: _install(tmp_path),
        run_fn=_run,
        version_fn=_versions,
    )

    assert code == 1
    assert "No solution found" in _text(err)


@pytest.mark.parametrize("dry_run", [False, True])
def test_upgrade_preflights_missing_local_plugin_path(
    tmp_path: Path,
    dry_run: bool,
) -> None:
    missing = tmp_path / "missing-plugin"
    receipt = f"""
[tool]
requirements = [
    {{ name = "sase" }},
    {{ name = "sase-acme", directory = "{missing}" }},
]
"""
    err = _console()

    code = handle_update_command(
        _args(dry_run=dry_run),
        console=_console(),
        err_console=err,
        probe_fn=lambda: _install(tmp_path, receipt),
        run_fn=lambda _argv: pytest.fail("uv must not run after preflight failure"),
        version_fn=_versions,
    )

    assert code == 1
    err_text = " ".join(_text(err).split())
    assert "plugin 'sase-acme'" in err_text
    assert str(missing) in err_text
    assert "sase plugin uninstall sase-acme" in err_text


def test_upgrade_tolerates_missing_receipt(tmp_path: Path) -> None:
    # Receipt missing on disk: the upgrade still succeeds; the render degrades
    # gracefully (no "already current" cross-reference) instead of crashing.
    install = UvToolInstall(
        uv_path="/usr/bin/uv",
        tool_dir=tmp_path,
        sase_dir=tmp_path / "sase",
        receipt_path=tmp_path / "sase" / "uv-receipt.toml",
    )
    out = _console()
    code = handle_update_command(
        _args(),
        console=out,
        probe_fn=lambda: install,
        run_fn=lambda _argv: parse_uv_output(_UPGRADE_OUTPUT),
        axe_running_fn=lambda: False,
        version_fn=_versions,
        clock=lambda: 0.0,
    )

    assert code == 0
    assert "0.5.0 \u2192 0.6.1" in _text(out)
