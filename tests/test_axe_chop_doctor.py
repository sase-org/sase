"""Tests for AXE chop diagnostics and the ``sase axe chop`` CLI handlers."""

from __future__ import annotations

import argparse
import json
import stat
from io import StringIO
from pathlib import Path

import pytest
from rich.console import Console

from sase.axe import cli
from sase.axe.chop_doctor import (
    aggregate_chop_status,
    build_chop_checks,
    build_chop_doctor_report,
)
from sase.axe.chop_inventory import collect_chop_inventory
from sase.axe.config import AxeConfig, ChopConfig, LumberjackConfig


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _config_with_missing_chop() -> AxeConfig:
    return AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                interval=10,
                chops=[ChopConfig(name="missing", description="")],
            )
        }
    )


# --- chop doctor model ---


def test_build_chop_checks_errors_on_missing_configured_chop() -> None:
    inventory = collect_chop_inventory(_config_with_missing_chop())

    checks = build_chop_checks(inventory, which_fn=lambda _: None)

    assert aggregate_chop_status(checks) == "ERROR"
    assert any(
        check.status == "ERROR" and "cannot be resolved" in check.summary
        for check in checks
    )


def test_build_chop_checks_warns_on_unconfigured_telegram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_bin = tmp_path / "venv" / "bin"
    python_bin.mkdir(parents=True)
    (python_bin / "python").write_text("", encoding="utf-8")
    _make_executable(python_bin / "sase_chop_tg_inbound")

    monkeypatch.setattr(
        "sase.axe.chop_inventory.sys.executable", str(python_bin / "python")
    )
    monkeypatch.setenv("PATH", "")
    monkeypatch.delenv("SASE_TELEGRAM_BOT_CHAT_ID", raising=False)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_USERNAME", raising=False)

    inventory = collect_chop_inventory(AxeConfig())
    checks = build_chop_checks(inventory, which_fn=lambda _: None)

    statuses = {check.id: check.status for check in checks}
    assert statuses["available_unconfigured_chops"] == "WARN"
    assert statuses["telegram_env"] == "WARN"
    assert statuses["telegram_pass"] == "WARN"
    assert aggregate_chop_status(checks) == "WARN"


def test_build_chop_doctor_report_no_error_when_all_resolve() -> None:
    report = build_chop_doctor_report(
        inventory=collect_chop_inventory(AxeConfig()),
        which_fn=lambda _: "/usr/bin/pass",
    )

    # No configured script chops are missing, so nothing escalates to ERROR even
    # if unconfigured scripts or Telegram prerequisites raise WARN.
    assert report.status != "ERROR"
    assert all(check.status != "ERROR" for check in report.checks)


# --- sase axe chop list handler ---


def test_handle_axe_chop_list_json_has_schema_version(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    config = AxeConfig(
        lumberjacks={
            "hooks": LumberjackConfig(
                name="hooks",
                interval=10,
                chops=[ChopConfig(name="agented", description="d", agent="do")],
            )
        }
    )
    monkeypatch.setattr(cli, "load_axe_config", lambda: config)

    args = argparse.Namespace(json=True, available=False, verbose=False)
    with pytest.raises(SystemExit) as exc:
        cli.handle_axe_chop_list(args)

    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "list"
    assert "chops" in payload
    assert any(c["name"] == "agented" for c in payload["chops"]["configured"])


def test_handle_axe_chop_list_json_keeps_per_lumberjack_rows(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A chop name in two lumberjacks yields one configured entry per lumberjack."""
    config = AxeConfig(
        lumberjacks={
            "jack1": LumberjackConfig(
                name="jack1",
                interval=10,
                chops=[ChopConfig(name="shared", description="", agent="a")],
            ),
            "jack2": LumberjackConfig(
                name="jack2",
                interval=10,
                chops=[ChopConfig(name="shared", description="", agent="a")],
            ),
        }
    )
    monkeypatch.setattr(cli, "load_axe_config", lambda: config)

    args = argparse.Namespace(json=True, available=False, verbose=False)
    with pytest.raises(SystemExit) as exc:
        cli.handle_axe_chop_list(args)

    assert exc.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    lumberjacks = sorted(
        c["lumberjack"] for c in payload["chops"]["configured"] if c["name"] == "shared"
    )
    assert lumberjacks == ["jack1", "jack2"]


# --- sase axe chop doctor handler ---


def test_handle_axe_chop_doctor_exit_one_on_error(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sase.axe.chop_doctor.collect_chop_inventory",
        lambda config=None: collect_chop_inventory(_config_with_missing_chop()),
    )

    args = argparse.Namespace(json=True, verbose=False)
    with pytest.raises(SystemExit) as exc:
        cli.handle_axe_chop_doctor(args)

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == 1
    assert payload["command"] == "doctor"
    assert payload["status"] == "ERROR"


def test_handle_axe_chop_doctor_exit_zero_when_clean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "sase.axe.chop_doctor.collect_chop_inventory",
        lambda config=None: collect_chop_inventory(AxeConfig()),
    )

    args = argparse.Namespace(json=False, verbose=False)
    with pytest.raises(SystemExit) as exc:
        cli.handle_axe_chop_doctor(args)

    assert exc.value.code == 0


# --- rendering ---


def test_render_chop_doctor_has_sections_and_no_traceback() -> None:
    from sase.axe.chop_render import render_chop_doctor

    report = build_chop_doctor_report(
        inventory=collect_chop_inventory(_config_with_missing_chop()),
        which_fn=lambda _: None,
    )
    output = StringIO()
    console = Console(file=output, force_terminal=False, color_system=None, width=140)

    render_chop_doctor(report, console=console)

    text = output.getvalue()
    assert "Chop Doctor" in text
    assert "Checks" in text
    assert "Configured Chops" in text
    assert "Traceback" not in text
