"""Tests for ``sase flag enable`` and ``sase flag disable``."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
from rich.console import Console

from sase.axe.process import AxeStartResult
from sase.feature_flags import snapshot as snapshot_mod
from sase.feature_flags.cli_set import (
    ACE_RESTART_NOTICE,
    APPLY_SAVED_FEATURE_FLAG,
    SET_JSON_SCHEMA_VERSION,
    handle_flag_set,
)
from sase.feature_flags.env import SASE_FEATURE_FLAGS_ENV
from sase.feature_flags.state import (
    FEATURE_FLAG_STATE_FILENAME,
    feature_flag_state_path,
    load_saved_feature_flags,
)
from sase.main.update_types import RestartAxeFn
from tests.main.parser_cli_helpers import parse_sase_args
from tests._conftest_runtime import reset_process_feature_flags


KEY = "ref_sync_gesture"


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=160, color_system=None, highlight=False), buf


def _forbid_restart(**_kwargs: object) -> AxeStartResult:
    raise AssertionError("AXE restart must not run")


def _run(
    argv: list[str],
    *,
    console: Console | None = None,
    axe_running: bool = False,
    restart_axe_fn: RestartAxeFn | None = None,
) -> int:
    args = parse_sase_args(argv)
    enabled = args.flag_subcommand == "enable"
    return handle_flag_set(
        args,
        enabled=enabled,
        console=console,
        axe_running_fn=lambda: axe_running,
        restart_axe_fn=(
            restart_axe_fn if restart_axe_fn is not None else _forbid_restart
        ),
    )


@pytest.fixture(autouse=True)
def _clean_flag_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    reset_process_feature_flags()
    yield
    reset_process_feature_flags()


def test_enable_persists_and_reports_skipped_axe() -> None:
    console, buf = _console()

    code = _run(["flag", "enable", KEY], console=console)

    assert code == 0
    loaded = load_saved_feature_flags()
    assert loaded.flags[KEY] is True
    out = buf.getvalue()
    assert KEY in out
    assert "enabled" in out
    assert "previous saved:  —" in out
    assert "effective:       on" in out
    assert SASE_FEATURE_FLAGS_ENV in out
    assert FEATURE_FLAG_STATE_FILENAME in out
    assert "shadowed" not in out
    assert ACE_RESTART_NOTICE in out
    assert "AXE is not running; left stopped." in out
    assert "load the updated code" not in out
    assert "Axe restarted" not in out


def test_disable_then_repeat_is_idempotent_and_retries_axe() -> None:
    restart_calls: list[str] = []

    def _restart(*, desired_state_source: str) -> AxeStartResult:
        restart_calls.append(desired_state_source)
        return AxeStartResult(status="started", pid=4242)

    console, buf = _console()
    first = _run(
        ["flag", "disable", KEY],
        console=console,
        axe_running=True,
        restart_axe_fn=_restart,
    )
    second = _run(
        ["flag", "disable", KEY],
        console=console,
        axe_running=True,
        restart_axe_fn=_restart,
    )

    assert first == 0
    assert second == 0
    loaded = load_saved_feature_flags()
    assert loaded.flags[KEY] is False
    assert restart_calls == ["sase flag disable", "sase flag disable"]
    out = buf.getvalue()
    assert "previous saved:  —" in out
    assert "previous saved:  off" in out
    assert "disabled" in out
    assert "Axe restarted (pid 4242)" in out
    assert APPLY_SAVED_FEATURE_FLAG in out
    assert "load the updated code" not in out


def test_unknown_flag_is_usage_error_and_skips_axe(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _axe_running() -> bool:
        raise AssertionError("axe status must not be checked for an unknown flag")

    args = parse_sase_args(["flag", "enable", "missing_flag"])
    code = handle_flag_set(
        args,
        enabled=True,
        axe_running_fn=_axe_running,
        restart_axe_fn=_forbid_restart,
    )

    assert code == 2
    assert "unknown feature flag: missing_flag" in capsys.readouterr().err
    assert not Path(feature_flag_state_path()).exists()


def test_corrupt_store_is_operational_failure_and_non_destructive(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from sase.feature_flags.state import feature_flag_state_path

    path = Path(feature_flag_state_path())
    path.write_text("{not-json", encoding="utf-8")
    original = path.read_bytes()

    code = _run(["flag", "enable", KEY])

    assert code == 1
    assert path.read_bytes() == original
    assert capsys.readouterr().err


def test_shadowed_cli_override_warns_and_still_saves() -> None:
    snapshot_mod.set_cli_feature_flags({KEY: False})
    console, buf = _console()

    code = _run(["flag", "enable", KEY], console=console)

    assert code == 0
    loaded = load_saved_feature_flags()
    assert loaded.flags[KEY] is True
    out = buf.getvalue()
    assert "shadowed" in out
    assert "CLI:" in out
    assert "effective remains off" in out


def test_json_envelope_separates_mutation_and_restart(
    capsys: pytest.CaptureFixture[str],
) -> None:
    first = _run(["flag", "disable", KEY, "--json"])
    payload = json.loads(capsys.readouterr().out)

    assert first == 0
    assert payload["schema_version"] == SET_JSON_SCHEMA_VERSION
    assert set(payload) == {
        "command",
        "mutation",
        "ok",
        "restart",
        "schema_version",
    }
    assert payload["ok"] is True
    assert payload["command"] == "disable"
    assert payload["mutation"]["key"] == KEY
    assert payload["mutation"]["enabled"] is False
    assert payload["mutation"]["changed"] is True
    assert payload["mutation"]["previous_saved"] is None
    assert payload["mutation"]["shadowed"] is False
    assert payload["restart"]["status"] == "skipped_not_running"
    assert payload["restart"]["reason"] == "axe is not running"


def test_json_idempotent_repeat_retries_restart(
    capsys: pytest.CaptureFixture[str],
) -> None:
    restart_calls = 0

    def _restart(*, desired_state_source: str) -> AxeStartResult:
        nonlocal restart_calls
        restart_calls += 1
        assert desired_state_source == "sase flag enable"
        return AxeStartResult(status="started", pid=99)

    _run(
        ["flag", "enable", KEY, "--json"],
        axe_running=True,
        restart_axe_fn=_restart,
    )
    capsys.readouterr()
    code = _run(
        ["flag", "enable", KEY, "--json"],
        axe_running=True,
        restart_axe_fn=_restart,
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert restart_calls == 2
    assert payload["mutation"]["changed"] is False
    assert payload["mutation"]["previous_saved"] is True
    assert payload["restart"]["status"] == "restarted"
    assert payload["restart"]["pid"] == 99


def test_restart_failure_keeps_saved_preference_and_is_partial_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail(*, desired_state_source: str) -> AxeStartResult:
        return AxeStartResult(status="failed", message="daemon refused")

    console, buf = _console()
    code = _run(
        ["flag", "disable", KEY],
        console=console,
        axe_running=True,
        restart_axe_fn=_fail,
    )

    assert code == 1
    loaded = load_saved_feature_flags()
    assert loaded.flags[KEY] is False
    out = buf.getvalue()
    assert "disabled" in out
    assert ACE_RESTART_NOTICE in out
    assert "daemon refused" in out

    json_code = _run(
        ["flag", "disable", KEY, "--json"],
        axe_running=True,
        restart_axe_fn=_fail,
    )
    payload = json.loads(capsys.readouterr().out)
    assert json_code == 1
    assert payload["ok"] is False
    assert payload["mutation"]["changed"] is False
    assert payload["mutation"]["enabled"] is False
    assert payload["restart"]["status"] == "failed"


def test_rich_and_json_are_exclusive(capsys: pytest.CaptureFixture[str]) -> None:
    console, buf = _console()
    code = _run(["flag", "enable", KEY, "-j"], console=console)

    assert code == 0
    assert buf.getvalue() == ""
    payload = json.loads(capsys.readouterr().out)
    assert payload["command"] == "enable"
    assert payload["mutation"]["enabled"] is True
