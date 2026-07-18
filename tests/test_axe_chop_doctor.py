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
    _aggregate_chop_status,
    _build_chop_checks,
    build_chop_doctor_report,
)
from sase.axe.chop_inventory import collect_chop_inventory
from sase.axe.config import (
    AxeConfig,
    _AxeConfigDiagnostic,
    AxeConfigError,
    ChopConfig,
    LumberjackConfig,
)


def _make_executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _point_home(monkeypatch: pytest.MonkeyPatch, home: Path) -> None:
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))


def _enable_telegram(home: Path) -> None:
    flag = home / ".sase" / "telegram_is_enabled"
    flag.parent.mkdir(parents=True, exist_ok=True)
    flag.touch()


def _point_python_bin(monkeypatch: pytest.MonkeyPatch, python_bin: Path) -> None:
    python_bin.mkdir(parents=True)
    (python_bin / "python").write_text("", encoding="utf-8")
    monkeypatch.setattr(
        "sase.axe.chop_inventory.sys.executable", str(python_bin / "python")
    )
    monkeypatch.setenv("PATH", "")


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

    checks = _build_chop_checks(inventory, which_fn=lambda _: None)

    assert _aggregate_chop_status(checks) == "ERROR"
    assert any(
        check.status == "ERROR" and "cannot be resolved" in check.summary
        for check in checks
    )


def test_build_chop_checks_warns_on_unconfigured_telegram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_bin = tmp_path / "venv" / "bin"
    _point_python_bin(monkeypatch, python_bin)
    _make_executable(python_bin / "sase_chop_tg_inbound")

    _point_home(monkeypatch, tmp_path)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_CHAT_ID", raising=False)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_USERNAME", raising=False)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_TOKEN", raising=False)

    inventory = collect_chop_inventory(AxeConfig())
    checks = _build_chop_checks(inventory, which_fn=lambda _: None)

    statuses = {check.id: check.status for check in checks}
    assert statuses["available_unconfigured_chops"] == "WARN"
    assert statuses["telegram_env"] == "WARN"
    assert statuses["telegram_bot_token"] == "WARN"
    assert _aggregate_chop_status(checks) == "WARN"


def test_build_chop_checks_accepts_telegram_chop_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_bin = tmp_path / "venv" / "bin"
    _point_python_bin(monkeypatch, python_bin)
    _make_executable(python_bin / "sase_chop_tg_inbound")
    _point_home(monkeypatch, tmp_path)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_CHAT_ID", raising=False)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_USERNAME", raising=False)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_TOKEN", raising=False)

    config = AxeConfig(
        lumberjacks={
            "telegram": LumberjackConfig(
                name="telegram",
                interval=10,
                chops=[
                    ChopConfig(
                        name="tg_inbound",
                        description="",
                        env={
                            "SASE_TELEGRAM_BOT_CHAT_ID": "123",
                            "SASE_TELEGRAM_BOT_USERNAME": "sase_bot",
                        },
                    )
                ],
            )
        }
    )

    checks = _build_chop_checks(collect_chop_inventory(config), which_fn=lambda _: None)

    statuses = {check.id: check.status for check in checks}
    assert statuses["telegram_env"] == "OK"
    assert statuses["telegram_bot_token"] == "WARN"


def test_build_chop_checks_accepts_telegram_token_from_chop_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_bin = tmp_path / "venv" / "bin"
    _point_python_bin(monkeypatch, python_bin)
    _make_executable(python_bin / "sase_chop_tg_inbound")
    _point_home(monkeypatch, tmp_path)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_TOKEN", raising=False)

    config = AxeConfig(
        lumberjacks={
            "telegram": LumberjackConfig(
                name="telegram",
                interval=10,
                chops=[
                    ChopConfig(
                        name="tg_inbound",
                        description="",
                        env={"SASE_TELEGRAM_BOT_TOKEN": "token"},
                    )
                ],
            )
        }
    )

    checks = _build_chop_checks(collect_chop_inventory(config), which_fn=lambda _: None)

    token_check = next(check for check in checks if check.id == "telegram_bot_token")
    assert token_check.status == "OK"
    assert "SASE_TELEGRAM_BOT_TOKEN" in token_check.summary


def test_build_chop_checks_accepts_telegram_token_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_bin = tmp_path / "venv" / "bin"
    _point_python_bin(monkeypatch, python_bin)
    _make_executable(python_bin / "sase_chop_tg_inbound")
    _point_home(monkeypatch, tmp_path)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_TOKEN", raising=False)
    token_file = tmp_path / ".sase" / "telegram_bot_token"
    token_file.parent.mkdir()
    token_file.write_text("token\n", encoding="utf-8")
    token_file.chmod(0o600)

    checks = _build_chop_checks(
        collect_chop_inventory(AxeConfig()), which_fn=lambda _: None
    )

    token_check = next(check for check in checks if check.id == "telegram_bot_token")
    assert token_check.status == "OK"
    assert "~/.sase/telegram_bot_token" in token_check.summary


def test_build_chop_checks_errors_when_enabled_configured_and_token_missing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    python_bin = tmp_path / "venv" / "bin"
    _point_python_bin(monkeypatch, python_bin)
    _make_executable(python_bin / "sase_chop_tg_inbound")
    _point_home(monkeypatch, tmp_path)
    _enable_telegram(tmp_path)
    monkeypatch.delenv("SASE_TELEGRAM_BOT_TOKEN", raising=False)

    config = AxeConfig(
        lumberjacks={
            "telegram": LumberjackConfig(
                name="telegram",
                interval=10,
                chops=[
                    ChopConfig(
                        name="tg_inbound",
                        description="",
                        env={
                            "SASE_TELEGRAM_BOT_CHAT_ID": "123",
                            "SASE_TELEGRAM_BOT_USERNAME": "sase_bot",
                        },
                    )
                ],
            )
        }
    )

    checks = _build_chop_checks(collect_chop_inventory(config), which_fn=lambda _: None)

    token_check = next(check for check in checks if check.id == "telegram_bot_token")
    assert token_check.status == "ERROR"
    assert "SASE_TELEGRAM_BOT_TOKEN" in token_check.next_steps[0]
    assert _aggregate_chop_status(checks) == "ERROR"


def test_build_chop_doctor_report_no_error_when_all_resolve() -> None:
    report = build_chop_doctor_report(
        inventory=collect_chop_inventory(AxeConfig()),
        which_fn=lambda _: "/usr/bin/pass",
    )

    # No configured script chops are missing, so nothing escalates to ERROR even
    # if unconfigured scripts or Telegram prerequisites raise WARN.
    assert report.status != "ERROR"
    assert all(check.status != "ERROR" for check in report.checks)


def test_build_chop_doctor_report_surfaces_config_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error = AxeConfigError(
        [
            _AxeConfigDiagnostic(
                code="agent_chop_removed",
                message="agent chops are no longer supported",
                path="axe.lumberjacks.audits.chops[0].agent",
                layer="overlay:test.yml:/tmp/test.yml",
            )
        ]
    )

    def _raise_config_error() -> AxeConfig:
        raise error

    monkeypatch.setattr("sase.axe.chop_inventory.load_axe_config", _raise_config_error)

    report = build_chop_doctor_report(which_fn=lambda _: None)

    assert report.status == "ERROR"
    config_check = next(
        check for check in report.checks if check.id.startswith("axe_config:")
    )
    assert "axe.lumberjacks.audits.chops[0].agent" in config_check.details[0]
    assert "overlay:test.yml:/tmp/test.yml" in config_check.details[0]


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
                chops=[
                    ChopConfig(
                        name="friendly",
                        description="d",
                        script="full_executable",
                    )
                ],
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
    assert any(c["name"] == "friendly" for c in payload["chops"]["configured"])


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
                chops=[ChopConfig(name="shared", description="")],
            ),
            "jack2": LumberjackConfig(
                name="jack2",
                interval=10,
                chops=[ChopConfig(name="shared", description="")],
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
