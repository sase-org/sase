"""Admission exemptions and fail-open behavior tests."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import pytest

from sase.core import tool_run as core
from sase.core.tool_run import tool_run_admission_poll, tool_run_show
from sase.tool import admission as gate
from sase.tool.argv import resolve_run_argv
from sase.tool.executor_run import run_recorded_body
from sase.tool.executor_signals import SignalState
from sase.tool.join_worker import execute_join_run
from tests.tool._admission_helpers import (
    admit,
    begin,
    clean_env,
    ctx,
    hold_slot,
    project,
    record_for_run,
    settle_run,
)


def _admission(run_id: str) -> dict[str, Any] | None:
    run = tool_run_show(run_id)["run"]
    demand = run.get("demand") or {}
    return demand.get("admission")


def _forbid_core_admission(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(*_args: object, **_kwargs: object) -> dict[str, Any]:
        raise AssertionError("admission must not call core here")

    for name in (
        "tool_run_admission_enter",
        "tool_run_admission_poll",
        "tool_run_admission_force",
    ):
        monkeypatch.setattr(core, name, refuse)


# -- exemptions ---------------------------------------------------------------


def test_unset_config_makes_no_admission_call_and_writes_no_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch)
    run_id, resolved = begin()
    _forbid_core_admission(monkeypatch)

    result = admit(ctx(run_id, resolved))

    assert result.proceed and not result.waited
    assert _admission(run_id) is None
    assert capsys.readouterr().err == ""


def test_uncapped_tool_and_adhoc_runs_are_never_limited(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"test": 1}})
    run_id, resolved = begin()
    adhoc_id, adhoc = begin(("--", "true"))
    _forbid_core_admission(monkeypatch)

    assert admit(ctx(run_id, resolved)).proceed
    assert admit(ctx(adhoc_id, adhoc)).proceed
    assert _admission(run_id) is None
    assert capsys.readouterr().err == ""


def test_nested_run_inside_a_live_parent_is_exempt(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    parent = hold_slot()
    run_id, resolved = begin(parent_run_id=parent)
    monkeypatch.delenv("SASE_TOOL_RUN_ID", raising=False)
    _forbid_core_admission(monkeypatch)

    result = admit(ctx(run_id, resolved, parent_run_id=parent))

    assert result.proceed and not result.waited
    assert _admission(run_id) is None
    assert capsys.readouterr().err == ""


def test_settled_inherited_parent_is_not_nesting(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    stale, _ = begin()
    settle_run(stale)
    monkeypatch.setenv("SASE_TOOL_RUN_ID", stale)
    run_id, _ = begin()

    assert gate._is_nested_run(stale, run_id) is False
    assert gate._is_nested_run(run_id, run_id) is False


def test_agent_with_cleared_inherited_parent_queues_as_a_new_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from sase.tool.ownership import resolve_ownership

    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    parent = hold_slot()
    monkeypatch.setenv("SASE_TOOL_RUN_ID", parent)
    monkeypatch.setenv("SASE_AGENT", "1")
    ownership = resolve_ownership(quiet=False)
    assert ownership.parent_run_id is None
    run_id, resolved = begin(parent_run_id=ownership.parent_run_id)
    release = threading.Timer(0.08, settle_run, args=(parent,))
    release.start()
    try:
        result = gate.admit_before_spawn(
            ctx(run_id, resolved, parent_run_id=ownership.parent_run_id),
            SignalState(),
            show_header=lambda: None,
        )
    finally:
        release.join()

    assert result.proceed and result.waited
    assert record_for_run(run_id)["state"] == "admitted"


def test_agent_command_child_keeps_its_parent_and_skips_admission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.tool.executor_process import child_env
    from sase.tool.ownership import resolve_ownership

    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    parent = hold_slot()
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
    run_id, resolved = begin(parent_run_id=ownership.parent_run_id)
    result = admit(ctx(run_id, resolved, parent_run_id=ownership.parent_run_id))

    assert result.proceed and not result.waited
    assert _admission(run_id) is None
    assert tool_run_show(run_id)["run"]["parent_run_id"] == parent
    assert capsys.readouterr().err == ""


def test_join_worker_takes_no_slot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.core.tool_run import tool_run_claim, tool_run_join
    from sase.tool.handoff import reserve_handoff_run

    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    holder = hold_slot()
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
    settle_run(run_id)
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
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    _forbid_core_admission(monkeypatch)

    result = admit(ctx("deadbeef" * 4, resolve_run_argv(["check"]), recorded=False))

    assert result.proceed and not result.waited
    assert (
        "sase: check admission unavailable (run not recorded); running without a slot"
        in capsys.readouterr().err
    )


def test_invalid_config_falls_open_naming_the_field(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 0}})
    run_id, resolved = begin()
    _forbid_core_admission(monkeypatch)

    result = admit(ctx(run_id, resolved))

    assert result.proceed
    err = capsys.readouterr().err
    assert "sase: check admission unavailable (" in err
    assert "tool_runs.admission.max_concurrent.check" in err
    assert "running without a slot" in err


def test_missing_binding_falls_open_at_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from sase.core.rust import require_rust_binding

    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    hold_slot()
    run_id, resolved = begin()

    def stale_wheel(name: str) -> Any:
        if name.startswith("tool_run_admission_"):
            raise AttributeError(
                f"sase_core_rs is importable but does not expose binding {name!r}"
            )
        return require_rust_binding(name)

    monkeypatch.setattr(core, "require_rust_binding", stale_wheel)

    result = admit(ctx(run_id, resolved))

    assert result.proceed and not result.waited
    assert "lacks the admission bindings" in capsys.readouterr().err
    assert _admission(run_id) is None


def test_persistent_store_errors_fall_open_after_the_grace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    clean_env(monkeypatch, tmp_path)
    project(tmp_path, monkeypatch, admission={"max_concurrent": {"check": 1}})
    run_id, resolved = begin()
    calls: list[str] = []

    def busy(*_args: object, **_kwargs: object) -> dict[str, Any]:
        calls.append("enter")
        raise RuntimeError("database is locked")

    monkeypatch.setattr(core, "tool_run_admission_enter", busy)
    monkeypatch.setattr(gate, "STORE_ERROR_GRACE_SECONDS", 0.2)

    result = admit(ctx(run_id, resolved))

    assert result.proceed
    assert len(calls) > 1
    assert (
        "admission unavailable (store error: database is locked)"
        in capsys.readouterr().err
    )
