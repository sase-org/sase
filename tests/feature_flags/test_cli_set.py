"""Tests for ``sase flag enable`` and ``sase flag disable``."""

from __future__ import annotations

import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from rich.console import Console

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
from sase.main.update_types import RestartSchedulerFn
from sase.service.actions import ServiceProcActionError, ServiceProcActionOutcome
from tests.main.parser_cli_helpers import parse_sase_args
from tests._conftest_runtime import reset_process_feature_flags


KEY = "ref_sync_gesture"


def _console() -> tuple[Console, io.StringIO]:
    buf = io.StringIO()
    return Console(file=buf, width=160, color_system=None, highlight=False), buf


def _scheduler_restart(*, reason: str | None = None) -> ServiceProcActionOutcome:
    return ServiceProcActionOutcome(
        action="restart",
        name="scheduler",
        mutations=(),
        nudged=True,
        message="requested service proc scheduler restart",
        generation=9,
    )


def _forbid_restart(**_kwargs: object) -> ServiceProcActionOutcome:
    raise AssertionError("scheduler restart must not run")


def _run(
    argv: list[str],
    *,
    console: Console | None = None,
    scheduler_running: bool = False,
    restart_scheduler_fn: RestartSchedulerFn | None = None,
) -> int:
    args = parse_sase_args(argv)
    enabled = args.flag_subcommand == "enable"
    return handle_flag_set(
        args,
        enabled=enabled,
        console=console,
        scheduler_running_fn=lambda: scheduler_running,
        restart_scheduler_fn=(
            restart_scheduler_fn
            if restart_scheduler_fn is not None
            else _forbid_restart
        ),
    )


@pytest.fixture(autouse=True)
def _clean_flag_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(SASE_FEATURE_FLAGS_ENV, raising=False)
    reset_process_feature_flags()
    yield
    reset_process_feature_flags()


@pytest.fixture(autouse=True)
def _confirmed_scheduler_restart(monkeypatch: pytest.MonkeyPatch) -> None:
    """Confirm injected scheduler restarts without a live service host."""
    import sase.main.update_restart as update_restart_mod

    row = SimpleNamespace(name="scheduler", pid=111)
    monkeypatch.setattr(
        update_restart_mod,
        "current_service_status",
        lambda: SimpleNamespace(procs=[row]),
    )
    monkeypatch.setattr(
        update_restart_mod,
        "wait_for_service_proc_request",
        lambda name, generation, *, timeout, poll=0.2: SimpleNamespace(
            outcome="restarted", pid=222, error=None
        ),
    )


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
    assert "Scheduler is not running; left stopped." in out
    assert "load the updated code" not in out
    assert "Scheduler Restart" not in out


def test_disable_then_repeat_is_idempotent_and_retries_scheduler() -> None:
    restart_calls: list[str | None] = []

    def _restart(*, reason: str | None = None) -> ServiceProcActionOutcome:
        restart_calls.append(reason)
        return _scheduler_restart(reason=reason)

    console, buf = _console()
    first = _run(
        ["flag", "disable", KEY],
        console=console,
        scheduler_running=True,
        restart_scheduler_fn=_restart,
    )
    second = _run(
        ["flag", "disable", KEY],
        console=console,
        scheduler_running=True,
        restart_scheduler_fn=_restart,
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
    assert "service proc scheduler restarted: pid 111 -> pid 222" in out
    assert APPLY_SAVED_FEATURE_FLAG in out
    assert "load the updated code" not in out


def test_unknown_flag_is_usage_error_and_skips_scheduler(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _scheduler_running() -> bool:
        raise AssertionError("scheduler status must not be checked for an unknown flag")

    args = parse_sase_args(["flag", "enable", "missing_flag"])
    code = handle_flag_set(
        args,
        enabled=True,
        scheduler_running_fn=_scheduler_running,
        restart_scheduler_fn=_forbid_restart,
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
    assert payload["restart"]["reason"] == "scheduler is not running"


def test_json_idempotent_repeat_retries_restart(
    capsys: pytest.CaptureFixture[str],
) -> None:
    restart_calls = 0

    def _restart(*, reason: str | None = None) -> ServiceProcActionOutcome:
        nonlocal restart_calls
        restart_calls += 1
        assert reason == "sase flag enable"
        return _scheduler_restart(reason=reason)

    _run(
        ["flag", "enable", KEY, "--json"],
        scheduler_running=True,
        restart_scheduler_fn=_restart,
    )
    capsys.readouterr()
    code = _run(
        ["flag", "enable", KEY, "--json"],
        scheduler_running=True,
        restart_scheduler_fn=_restart,
    )
    payload = json.loads(capsys.readouterr().out)

    assert code == 0
    assert restart_calls == 2
    assert payload["mutation"]["changed"] is False
    assert payload["mutation"]["previous_saved"] is True
    assert payload["restart"]["status"] == "restarted"
    assert (
        payload["restart"]["message"]
        == "service proc scheduler restarted: pid 111 -> pid 222"
    )


def test_restart_failure_keeps_saved_preference_and_is_partial_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def _fail(*, reason: str | None = None) -> ServiceProcActionOutcome:
        raise ServiceProcActionError("daemon refused")

    console, buf = _console()
    code = _run(
        ["flag", "disable", KEY],
        console=console,
        scheduler_running=True,
        restart_scheduler_fn=_fail,
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
        scheduler_running=True,
        restart_scheduler_fn=_fail,
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
