"""In-process tests for the pre-spawn host admission gate."""

from __future__ import annotations

import os
import secrets
import subprocess
import threading
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config.core import clear_config_cache
from sase.core import tool_run as core
from sase.core.tool_run import (
    tool_run_admission_enter,
    tool_run_admission_poll,
    tool_run_begin,
    tool_run_show,
)
from sase.tool import admission as gate
from sase.tool.argv import resolve_run_argv
from sase.tool.executor_models import RecordedRunContext
from sase.tool.executor_recording import build_begin_request, finish_tool_run
from sase.tool.executor_run import run_recorded_body
from sase.tool.executor_signals import SignalState
from sase.tool.join_worker import execute_join_run


def _clean_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    monkeypatch.setenv("SASE_HOME", str(home))
    for key in (
        "SASE_AGENT",
        "SASE_AGENT_NAME",
        "SASE_ARTIFACTS_DIR",
        "SASE_MONITOR_ID",
        "SASE_MONITOR_ARTIFACTS_DIR",
        "SASE_PROC_ID",
        "SASE_PROC_LOG_PATH",
        "SASE_TOOL_RUN_ID",
        "SASE_TOOL_RUN_AGENT_CHILD",
        "SASE_TOOL_RUN_EVENTS",
        "SASE_TOOL_RUN_AGENT",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    # Fast loop for in-process tests; the subprocess tests use real cadence.
    monkeypatch.setattr(gate, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(gate, "POLL_JITTER_SECONDS", 0.0)
    monkeypatch.setattr(gate, "SLICE_SECONDS", 0.01)
    monkeypatch.setattr(gate, "SWEEP_SECONDS", 0.2)
    return home


def _project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    admission: object = None,
    script: str = "true",
) -> Path:
    root = tmp_path / "project"
    (root / ".git").mkdir(parents=True, exist_ok=True)
    (root / "sase").mkdir(exist_ok=True)
    config: dict[str, Any] = {
        "tools": {
            "check": {
                "argv": ["sh", "-c", script],
                "description": "admission fixture",
                "args": "deny",
                "inputs": [],
                "env": [],
                "fingerprint": {"repos": [], "toolchain": {}},
            }
        }
    }
    if admission is not None:
        config["tool_runs"] = {"admission": admission}
    (root / "sase" / "sase.yml").write_text(yaml.safe_dump(config), encoding="utf-8")
    monkeypatch.chdir(root)
    clear_config_cache()
    return root


def _begin(words: tuple[str, ...] = ("check",), **overrides: Any) -> tuple[str, Any]:
    run_id = secrets.token_hex(16)
    resolved = resolve_run_argv(list(words))
    request = build_begin_request(
        run_id,
        resolved=resolved,
        owner_kind=None,
        owner_id=None,
        parent_run_id=None,
        events_path=None,
        stdout_path=None,
        stderr_path=None,
    )
    request.update(overrides)
    started = tool_run_begin(request)
    assert started["run"]["state"] == "running"
    return run_id, resolved


def _ctx(run_id: str, resolved: Any, **fields: Any) -> RecordedRunContext:
    values: dict[str, Any] = {
        "run_id": run_id,
        "recorded": True,
        "resolved": resolved,
        "has_owner": False,
        "owns_output": True,
        "compact": False,
        "tail_lines": 200,
        "events_path": None,
        "stdout_path": None,
        "stderr_path": None,
    }
    values.update(fields)
    return RecordedRunContext(**values)


def _hold_slot(limit: int = 1, **overrides: Any) -> str:
    """Record a running ``check`` run that holds one slot."""

    holder, _ = _begin(**overrides)
    entered = tool_run_admission_enter(
        {"schema_version": 1, "run_id": holder, "key": "check", "limit": limit}
    )
    assert entered["outcome"] == "admitted"
    return holder


def _admission(run_id: str) -> dict[str, Any] | None:
    run = tool_run_show(run_id)["run"]
    demand = run.get("demand") or {}
    return demand.get("admission")


def _record(run_id: str) -> dict[str, Any]:
    record = _admission(run_id)
    assert isinstance(record, dict), f"run {run_id} has no admission record"
    return record


def _settle(run_id: str) -> None:
    assert finish_tool_run(
        run_id, state="succeeded", exit_code=0, duration_ms=1, terminal_cause="exited"
    )


def _forbid_core_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise AssertionError("admission must not call core here")

    for name in (
        "tool_run_admission_enter",
        "tool_run_admission_poll",
        "tool_run_admission_force",
    ):
        monkeypatch.setattr(core, name, refuse)


def _admit(ctx: RecordedRunContext) -> Any:
    return gate.admit_before_spawn(ctx, SignalState(), show_header=lambda: None)


# -- exemptions ---------------------------------------------------------------


def test_unset_config_makes_no_admission_call_and_writes_no_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch)
    run_id, resolved = _begin()
    _forbid_core_admission(monkeypatch)

    result = _admit(_ctx(run_id, resolved))

    assert result.proceed and not result.waited
    assert _admission(run_id) is None
    assert capsys.readouterr().err == ""


def test_uncapped_tool_and_adhoc_runs_are_never_limited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"test": 1}})
    run_id, resolved = _begin()
    adhoc_id, adhoc = _begin(("--", "true"))
    _forbid_core_admission(monkeypatch)

    assert _admit(_ctx(run_id, resolved)).proceed
    assert _admit(_ctx(adhoc_id, adhoc)).proceed
    assert _admission(run_id) is None
    assert capsys.readouterr().err == ""


def test_nested_run_inside_a_live_parent_is_exempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    parent = _hold_slot()
    run_id, resolved = _begin(parent_run_id=parent)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    _forbid_core_admission(monkeypatch)

    result = _admit(_ctx(run_id, resolved, parent_run_id=parent))

    assert result.proceed and not result.waited
    assert _admission(run_id) is None
    assert capsys.readouterr().err == ""


def test_settled_inherited_parent_is_not_nesting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    stale, _ = _begin()
    _settle(stale)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", stale)
    run_id, _ = _begin()

    assert gate._is_nested_run(stale, run_id) is False
    assert gate._is_nested_run(run_id, run_id) is False


def test_agent_with_cleared_inherited_parent_queues_as_a_new_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool.ownership import resolve_ownership

    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    parent = _hold_slot()
    monkeypatch.setenv("SASE_TOOL_RUN_ID", parent)
    monkeypatch.setenv("SASE_AGENT", "1")
    ownership = resolve_ownership(quiet=False)
    assert ownership.parent_run_id is None
    run_id, resolved = _begin(parent_run_id=ownership.parent_run_id)
    release = threading.Timer(0.08, _settle, args=(parent,))
    release.start()
    try:
        result = gate.admit_before_spawn(
            _ctx(run_id, resolved, parent_run_id=ownership.parent_run_id),
            SignalState(),
            show_header=lambda: None,
        )
    finally:
        release.join()

    assert result.proceed and result.waited
    assert _record(run_id)["state"] == "admitted"


def test_agent_command_child_keeps_its_parent_and_skips_admission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.tool.executor_process import child_env
    from sase.tool.ownership import resolve_ownership

    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    parent = _hold_slot()
    monkeypatch.setenv("SASE_AGENT", "1")
    monkeypatch.setenv("SASE_AGENT_NAME", "fixture-agent")

    child_environment = child_env(
        recorded=True,
        run_id=parent,
        events_path=tmp_path / "parent-events.jsonl",
        resolved=resolve_run_argv(["check"]),
    )
    for key in list(os.environ):
        if key.startswith("SASE_TOOL_"):
            monkeypatch.delenv(key, raising=False)
    for key, value in child_environment.items():
        if key.startswith("SASE_TOOL_"):
            monkeypatch.setenv(key, value)

    ownership = resolve_ownership(quiet=False)
    assert ownership.parent_run_id == parent
    run_id, resolved = _begin(parent_run_id=ownership.parent_run_id)
    result = _admit(_ctx(run_id, resolved, parent_run_id=ownership.parent_run_id))

    assert result.proceed and not result.waited
    assert _admission(run_id) is None
    assert tool_run_show(run_id)["run"]["parent_run_id"] == parent
    assert capsys.readouterr().err == ""


def test_join_worker_takes_no_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.core.tool_run import tool_run_claim, tool_run_join
    from sase.tool.handoff import reserve_handoff_run

    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    holder = _hold_slot()
    reservation = reserve_handoff_run(
        resolve_run_argv(["check"]),
        owner_kind="proc",
        owner_id="proc-join",
        agent="agent-1",
        starter={
            "agent": "agent-1",
            "pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        },
    )
    assert reservation.reserved, reservation.error
    run_id = reservation.run_id
    joined = tool_run_join(
        {
            "schema_version": 1,
            "run_id": run_id,
            "joiner_kind": "monitor",
            "joiner_id": "mon-join",
            "agent": "agent-1",
        }
    )
    assert joined["outcome"] == "joined"
    claimed = tool_run_claim(
        {
            "schema_version": 1,
            "run_id": run_id,
            "owner_kind": "proc",
            "owner_id": "proc-join",
            "wrapper_pid": os.getpid(),
            "boot_id": "boot-1",
            "process_start_identity": "boot-1:1",
        }
    )
    assert claimed["outcome"] == "claimed"
    _settle(run_id)
    monkeypatch.setenv("SASE_MONITOR_ID", "mon-join")

    # The join follows the run to its end while the only slot stays held.
    assert execute_join_run(run_id) == 0
    polled = tool_run_admission_poll({"schema_version": 1, "run_id": holder})
    assert [peer["run_id"] for peer in polled["holders"]] == [holder]
    assert _admission(run_id) is None


# -- fail-open ----------------------------------------------------------------


def test_unrecorded_run_falls_open_without_a_core_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    _forbid_core_admission(monkeypatch)

    result = _admit(_ctx("deadbeef" * 4, resolve_run_argv(["check"]), recorded=False))

    assert result.proceed and not result.waited
    assert (
        "sase: check admission unavailable (run not recorded); running without a slot"
        in capsys.readouterr().err
    )


def test_invalid_config_falls_open_naming_the_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 0}})
    run_id, resolved = _begin()
    _forbid_core_admission(monkeypatch)

    result = _admit(_ctx(run_id, resolved))

    assert result.proceed
    err = capsys.readouterr().err
    assert "sase: check admission unavailable (" in err
    assert "tool_runs.admission.max_concurrent.check" in err
    assert "running without a slot" in err


def test_missing_binding_falls_open_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.core.rust import require_rust_binding

    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    _hold_slot()
    run_id, resolved = _begin()

    def stale_wheel(name: str) -> Any:
        if name.startswith("tool_run_admission_"):
            raise AttributeError(
                f"sase_core_rs is importable but does not expose binding {name!r}"
            )
        return require_rust_binding(name)

    monkeypatch.setattr(core, "require_rust_binding", stale_wheel)

    result = _admit(_ctx(run_id, resolved))

    assert result.proceed and not result.waited
    assert "lacks the admission bindings" in capsys.readouterr().err
    assert _admission(run_id) is None


def test_persistent_store_errors_fall_open_after_the_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    run_id, resolved = _begin()
    calls: list[str] = []

    def busy(*_args: object, **_kwargs: object) -> dict[str, Any]:
        calls.append("enter")
        raise RuntimeError("database is locked")

    monkeypatch.setattr(core, "tool_run_admission_enter", busy)
    monkeypatch.setattr(gate, "STORE_ERROR_GRACE_SECONDS", 0.2)

    result = _admit(_ctx(run_id, resolved))

    assert result.proceed
    assert len(calls) > 1
    assert (
        "admission unavailable (store error: database is locked)"
        in capsys.readouterr().err
    )


# -- the wait -----------------------------------------------------------------


def test_waiter_prints_counts_then_the_grant_and_records_the_wait(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    holder = _hold_slot()
    run_id, resolved = _begin()
    timer = threading.Timer(0.4, _settle, args=(holder,))
    timer.start()
    try:
        headers: list[bool] = []
        result = gate.admit_before_spawn(
            _ctx(run_id, resolved),
            SignalState(),
            show_header=lambda: headers.append(True),
        )
    finally:
        timer.join()

    assert result.proceed and result.waited
    assert headers, "the run header prints before the waiting line"
    err = capsys.readouterr().err
    assert "sase: waiting for a check slot (limit 1: 1 running, 0 ahead)" in err
    assert err.count("sase: waiting for a check slot") == 1
    assert "sase: check slot granted after " in err
    record = _record(run_id)
    assert record["state"] == "admitted"
    assert record["admitted_by"] == "slot"
    assert record["wait_ms"] > 0


def test_immediate_admission_prints_nothing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 2}})
    _hold_slot(limit=2)
    run_id, resolved = _begin()

    result = _admit(_ctx(run_id, resolved))

    assert result.proceed and result.waited
    assert capsys.readouterr().err == ""
    assert _record(run_id)["state"] == "admitted"


def test_max_wait_admits_over_the_limit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
    )
    holder = _hold_slot()
    run_id, resolved = _begin()

    result = _admit(_ctx(run_id, resolved))

    assert result.proceed
    err = capsys.readouterr().err
    assert "(max_wait_seconds 1); running over the limit of 1" in err
    record = _record(run_id)
    assert record["state"] == "admitted"
    assert record["admitted_by"] == "max_wait"
    polled = tool_run_admission_poll({"schema_version": 1, "run_id": holder})
    assert {peer["run_id"] for peer in polled["holders"]} == {holder, run_id}


def test_force_settled_stops_before_the_child_runs(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
        script=f"touch {marker}",
    )
    _hold_slot()
    run_id, resolved = _begin()
    monkeypatch.setattr(
        core,
        "tool_run_admission_force",
        lambda *_args, **_kwargs: {"outcome": "settled"},
    )

    assert run_recorded_body(_ctx(run_id, resolved), SignalState()) == 143
    run = tool_run_show(run_id)["run"]
    assert not marker.exists()
    assert run["state"] == "signaled"
    assert "command was not run" in (run.get("diagnostics") or [])
    assert _record(run_id)["state"] == "abandoned"


def test_force_not_found_falls_open_and_recovers_unavailable_evidence(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
        script=f"touch {marker}",
    )
    _hold_slot()
    run_id, resolved = _begin()
    original_force = core.tool_run_admission_force
    outcomes: list[str] = []

    def missing_max_wait(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if request.get("reason") == "max_wait":
            return {"outcome": "not_found"}
        return original_force(request, **kwargs)

    monkeypatch.setattr(core, "tool_run_admission_force", missing_max_wait)
    monkeypatch.setattr(
        gate, "_count", lambda outcome, *_args: outcomes.append(outcome)
    )

    assert run_recorded_body(_ctx(run_id, resolved), SignalState()) == 0
    run = tool_run_show(run_id)["run"]
    assert marker.exists()
    assert run["state"] == "succeeded"
    assert _record(run_id)["admitted_by"] == "unavailable"
    assert "forced" not in outcomes
    assert "unavailable" in outcomes
    err = capsys.readouterr().err
    assert err.count("admission unavailable") == 1
    assert "no check slot after" not in err


def test_transient_force_error_retries_until_max_wait_is_confirmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
    )
    _hold_slot()
    run_id, resolved = _begin()
    original_force = core.tool_run_admission_force
    calls = 0

    def one_transient_error(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database is locked")
        return original_force(request, **kwargs)

    monkeypatch.setattr(core, "tool_run_admission_force", one_transient_error)

    result = _admit(_ctx(run_id, resolved))

    assert result.proceed
    assert calls >= 2
    assert _record(run_id)["admitted_by"] == "max_wait"


def test_force_store_error_falls_open_and_recovers_before_child_settlement(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
        script=f"sleep 1.5; touch {marker}",
    )
    _hold_slot()
    run_id, resolved = _begin()
    original_force = core.tool_run_admission_force
    monkeypatch.setattr(gate, "STORE_ERROR_GRACE_SECONDS", 0.15)

    def unavailable_during_force(
        request: dict[str, Any], **kwargs: Any
    ) -> dict[str, Any]:
        if request.get("reason") == "max_wait":
            raise RuntimeError("database is locked")
        return original_force(request, **kwargs)

    monkeypatch.setattr(core, "tool_run_admission_force", unavailable_during_force)

    assert run_recorded_body(_ctx(run_id, resolved), SignalState()) == 0
    run = tool_run_show(run_id)["run"]
    assert marker.exists()
    assert run["state"] == "succeeded"
    admission = _record(run_id)
    assert admission["admitted_by"] == "unavailable"
    assert admission["wait_ms"] < run["duration_ms"]


def test_poll_failure_after_entry_recovers_the_bypass_at_a_later_write(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}},
        script=f"touch {marker}",
    )
    _hold_slot()
    run_id, resolved = _begin()
    monkeypatch.setattr(gate, "STORE_ERROR_GRACE_SECONDS", 0.15)
    monkeypatch.setattr(
        core,
        "tool_run_admission_poll",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database is locked")
        ),
    )
    original_force = core.tool_run_admission_force
    recoveries: list[dict[str, Any]] = []

    def recover_on_retry(request: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        if request.get("reason") == "unavailable":
            recoveries.append(dict(request))
            if len(recoveries) == 1:
                raise RuntimeError("database is locked")
        return original_force(request, **kwargs)

    monkeypatch.setattr(core, "tool_run_admission_force", recover_on_retry)

    assert run_recorded_body(_ctx(run_id, resolved), SignalState()) == 0
    run = tool_run_show(run_id)["run"]
    admission = _record(run_id)
    assert marker.exists()
    assert run["state"] == "succeeded"
    assert admission["state"] == "admitted"
    assert admission["admitted_by"] == "unavailable"
    # The pre-spawn bypass time survives the failed first write.
    assert len(recoveries) == 2
    assert {item["now_ms"] for item in recoveries} == {recoveries[0]["now_ms"]}
    assert admission["admitted_ts_ms"] == recoveries[0]["now_ms"]
    assert not any(
        "evidence incomplete" in item for item in (run.get("diagnostics") or [])
    )
    assert capsys.readouterr().err.count("admission unavailable") == 1


def test_unrecovered_bypass_is_named_in_settlement_diagnostics(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
    )
    _hold_slot()
    run_id, resolved = _begin()
    monkeypatch.setattr(gate, "STORE_ERROR_GRACE_SECONDS", 0.12)
    monkeypatch.setattr(
        core,
        "tool_run_admission_force",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database is locked")
        ),
    )

    assert run_recorded_body(_ctx(run_id, resolved), SignalState()) == 0
    run = tool_run_show(run_id)["run"]
    assert run["state"] == "succeeded"
    assert _record(run_id)["state"] == "abandoned"
    assert any(
        "admission bypass evidence incomplete" in item
        for item in (run.get("diagnostics") or [])
    )


@pytest.mark.parametrize(
    ("probe_name", "expected_cause"),
    [("stop_recorded", "stop_requested"), ("timeout_recorded", "timeout")],
)
def test_stop_or_timeout_during_force_retry_does_not_start_child(
    probe_name: str,
    expected_cause: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}, "max_wait_seconds": 1},
        script=f"touch {marker}",
    )
    _hold_slot()
    run_id, resolved = _begin()
    monkeypatch.setattr(
        core,
        "tool_run_admission_force",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database is locked")
        ),
    )
    calls = 0

    def stop_after_retry() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 2

    code = run_recorded_body(
        _ctx(run_id, resolved, **{probe_name: stop_after_retry}), SignalState()
    )
    run = tool_run_show(run_id)["run"]
    assert code == 143
    assert not marker.exists()
    assert run["terminal_cause"] == expected_cause
    assert "command was not run" in (run.get("diagnostics") or [])
    assert _record(run_id)["state"] == "abandoned"


def test_dead_holder_is_reconciled_and_frees_its_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.core.process_identity import process_identity_token

    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    # A holder whose wrapper already exited: its pid is gone.
    gone = subprocess.Popen(["true"])
    identity = process_identity_token(gone.pid)
    gone.wait()
    holder = _hold_slot(
        wrapper_pid=gone.pid,
        process_start_identity=identity or None,
    )
    run_id, resolved = _begin()

    result = _admit(_ctx(run_id, resolved))

    assert result.proceed
    assert tool_run_show(holder)["run"]["state"] == "lost"
    assert _record(run_id)["state"] == "admitted"


def test_stopped_waiter_settles_without_running_and_is_abandoned(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}},
        script=f"touch {marker}",
    )
    _hold_slot()
    run_id, resolved = _begin()
    polls: list[int] = []

    def stop_after_a_wait() -> bool:
        polls.append(1)
        return len(polls) >= 3

    code = run_recorded_body(
        _ctx(run_id, resolved, stop_recorded=stop_after_a_wait), SignalState()
    )

    assert code == 143
    assert not marker.exists()
    run = tool_run_show(run_id)["run"]
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "stop_requested"
    assert "command was not run" in (run.get("diagnostics") or [])
    assert _record(run_id)["state"] == "abandoned"
    err = capsys.readouterr().err
    assert err.count(f"sase tool run {run_id}") == 1
    assert "sase: stopped waiting for a check slot (stop requested)" in err


def test_sigterm_while_waiting_settles_signaled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _clean_env(monkeypatch, tmp_path)
    _project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    _hold_slot()
    run_id, resolved = _begin()
    signals = SignalState()
    timer = threading.Timer(0.2, lambda: setattr(signals, "sigterm", True))
    timer.start()
    try:
        code = run_recorded_body(_ctx(run_id, resolved), signals)
    finally:
        timer.join()

    assert code == 143
    run = tool_run_show(run_id)["run"]
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "signal"
    assert _record(run_id)["state"] == "abandoned"


def test_admitted_run_executes_its_child_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    _clean_env(monkeypatch, tmp_path)
    marker = tmp_path / "ran"
    _project(
        tmp_path,
        monkeypatch,
        admission={"max_concurrent": {"check": 1}},
        script=f"echo x >> {marker}",
    )
    holder = _hold_slot()
    run_id, resolved = _begin()
    timer = threading.Timer(0.3, _settle, args=(holder,))
    timer.start()
    try:
        code = run_recorded_body(_ctx(run_id, resolved), SignalState())
    finally:
        timer.join()

    assert code == 0
    assert marker.read_text() == "x\n"
    run = tool_run_show(run_id)["run"]
    assert run["state"] == "succeeded"
    # duration_ms measures from the spawn, so it excludes the wait.
    assert run["duration_ms"] < _record(run_id)["wait_ms"]
    err = capsys.readouterr().err
    assert err.count(f"sase tool run {run_id}") == 1
    assert err.index("sase: waiting for a check slot") < err.index(
        "sase: check slot granted"
    )
