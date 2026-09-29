"""E2 settlement: finish races, the proc hook, and deliver-once publishing."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sase.procs import get_proc
from sase.procs.models import Proc
from sase.tool.executor_recording import finish_tool_run
from sase.tool.liveness import reconcile_handoff_run, reconcile_unsettled_tool_runs
from sase.tool.notify import deliver_handoff_settlement
from sase.tool.settlement import settle_monitor_tool_run, settle_tool_run_followup
from tool._settlement_helpers import (
    claim,
    clean_env,
    expected_notification_id,
    fabricate_proc,
    get_run,
    reserve,
    reserve_with_dead_launcher,
    settle_fabricated,
    terminal_fact,
    tool_run_notifications,
)


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    clean_env(monkeypatch, tmp_path)


def _followup_of(proc: Proc) -> object:
    assert isinstance(proc.result, dict)
    return proc.result["followup"]


# --- Finish race ------------------------------------------------------------


def test_finish_tool_run_treats_an_already_settled_run_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = reserve("proc", "proc-7")
    claim(run_id, "proc", "proc-7")
    reconcile_handoff_run(run_id, terminal_fact("proc", "proc-7", "error", exit_code=2))
    assert get_run(run_id)["state"] == "failed"

    assert finish_tool_run(
        run_id,
        state="failed",
        exit_code=2,
        duration_ms=5,
        terminal_cause="exited",
    )

    def busy(_payload: dict[str, Any]) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr("sase.tool.executor_recording.tool_run_finish", busy)
    assert finish_tool_run(run_id, state="failed", exit_code=2, duration_ms=5)


def test_finish_tool_run_still_fails_when_the_run_is_unsettled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_id = reserve("proc", "proc-7b")
    claim(run_id, "proc", "proc-7b")

    def busy(_payload: dict[str, Any]) -> None:
        raise RuntimeError("database is locked")

    monkeypatch.setattr("sase.tool.executor_recording.tool_run_finish", busy)
    assert not finish_tool_run(run_id, state="failed", exit_code=2, duration_ms=5)


def test_failed_worker_finish_is_recovered_through_the_settlement_hook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 7: a worker whose finish raised is settled from the owner's result."""

    run_id = reserve("proc", "proc-7c")
    claim(run_id, "proc", "proc-7c")
    fabricate_proc(tmp_path, "proc-7c", run_id)

    def busy(_payload: dict[str, Any]) -> None:
        raise RuntimeError("database is locked")

    with monkeypatch.context() as scoped:
        scoped.setattr("sase.tool.executor_recording.tool_run_finish", busy)
        assert not finish_tool_run(run_id, state="failed", exit_code=3, duration_ms=5)
    clean_env(monkeypatch, tmp_path)
    assert get_run(run_id)["state"] == "running"

    settle_fabricated("proc-7c", status="error", reason="error", exit_code=3)

    run = get_run(run_id)
    assert run["state"] == "failed"
    assert run["exit_code"] == 3
    assert run["settled_by"] == "owner"
    assert len(tool_run_notifications()) == 1


# --- Proc settlement hook ---------------------------------------------------


def test_proc_settlement_hook_settles_run_and_publishes_once(tmp_path: Path) -> None:
    run_id = reserve("proc", "proc-hook")
    claim(run_id, "proc", "proc-hook")
    fabricate_proc(tmp_path, "proc-hook", run_id)

    finished = settle_fabricated(
        "proc-hook", status="error", reason="error", exit_code=3
    )

    assert finished.status == "error"
    assert _followup_of(finished) == "tool-run-settled"
    run = get_run(run_id)
    assert (run["state"], run["exit_code"], run["settled_by"]) == ("failed", 3, "owner")
    notifications = tool_run_notifications()
    assert [item.id for item in notifications] == [expected_notification_id(run_id)]
    note = notifications[0]
    assert note.sender == "tool-run"
    assert note.tags == ["tool-run"]
    assert note.action == "OpenToolRun"
    assert note.action_data == {
        "run_id": run_id,
        "command": f"sase tool show {run_id}",
    }
    from sase.tool.notify import _build_notification

    built = _build_notification(run, run_id, note.id)
    assert built.action == "OpenToolRun"
    assert built.action_data == {
        "run_id": run_id,
        "command": f"sase tool show {run_id}",
    }
    assert f"sase tool show {run_id}" in note.notes
    assert note.notes[0].startswith("Tool run ad-hoc failed")
    assert "(exit 3)" in note.notes[0]


def test_supervisor_loss_via_proc_reconcile_settles_lost(tmp_path: Path) -> None:
    """Row 4 end to end: a supervisor that died is reconciled, the run is lost."""

    from sase.procs import reconcile_running_procs

    run_id = reserve("proc", "proc-loss")
    claim(run_id, "proc", "proc-loss")
    fabricate_proc(tmp_path, "proc-loss", run_id)

    reconcile_running_procs()

    proc = get_proc("proc-loss")
    assert proc is not None and proc.status == "error"
    run = get_run(run_id)
    assert run["state"] == "lost"
    assert run["terminal_cause"] == "owner_lost"
    assert len(tool_run_notifications()) == 1


def test_stopped_proc_before_start_settles_via_hook(tmp_path: Path) -> None:
    run_id = reserve_with_dead_launcher("proc-stop")
    fabricate_proc(tmp_path, "proc-stop", run_id)

    settle_fabricated(
        "proc-stop",
        status="killed",
        reason="stop",
        exit_code=None,
        message="proc killed",
    )

    run = get_run(run_id)
    assert run["state"] == "signaled"
    assert run["terminal_cause"] == "stop_requested"
    assert "command was not run" in run["diagnostics"]


def test_settlement_hook_errors_still_finish_the_proc_row(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Row 12: a ToolRun or notification error never wedges proc settlement."""

    run_id = reserve("proc", "proc-wedge")
    claim(run_id, "proc", "proc-wedge")
    fabricate_proc(tmp_path, "proc-wedge", run_id)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("reconcile exploded")

    monkeypatch.setattr("sase.tool.settlement.reconcile_handoff_run", boom)
    finished = settle_fabricated(
        "proc-wedge", status="error", reason="error", exit_code=3
    )

    assert finished.status == "error"
    assert _followup_of(finished) == "tool-run-error"
    assert get_run(run_id)["state"] == "running"


def test_settlement_hook_import_or_outer_errors_are_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = reserve("proc", "proc-wedge2")
    fabricate_proc(tmp_path, "proc-wedge2", run_id)

    def boom(_state: dict[str, Any]) -> None:
        raise RuntimeError("hook exploded")

    monkeypatch.setattr("sase.tool.settlement.settle_tool_run_followup", boom)
    finished = settle_fabricated(
        "proc-wedge2", status="error", reason="error", exit_code=3
    )
    assert finished.status == "error"
    assert _followup_of(finished) == "tool-run-error"


def test_notification_failure_is_reported_not_raised(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = reserve("proc", "proc-notify-fail")
    claim(run_id, "proc", "proc-notify-fail")
    monkeypatch.setattr(
        "sase.notifications.store.append_notification",
        lambda _n: (_ for _ in ()).throw(OSError("disk full")),
    )
    state: dict[str, Any] = {
        "proc_id": "proc-notify-fail",
        "exit_code": 3,
        "termination_reason": "error",
        "followup": {"kind": "tool-run", "run_id": run_id},
    }
    settle_tool_run_followup(state)
    assert get_run(run_id)["state"] == "failed"
    assert state["followup_outcome"] == "tool-run-error"
    assert "notification failed" in state["followup_error"]


# --- Deliver once -----------------------------------------------------------


def test_repeated_passes_and_resumed_settlement_publish_exactly_once(
    tmp_path: Path,
) -> None:
    """Row 8: hook twice, worker delivery, and reconcile passes collapse to one."""

    run_id = reserve("proc", "proc-once")
    claim(run_id, "proc", "proc-once")
    state: dict[str, Any] = {
        "proc_id": "proc-once",
        "exit_code": 3,
        "termination_reason": "error",
        "followup": {"kind": "tool-run", "run_id": run_id},
    }

    settle_tool_run_followup(state)
    assert state["followup_outcome"] == "tool-run-settled"
    settle_tool_run_followup(state)
    assert state["followup_outcome"] == "tool-run-settled"
    assert deliver_handoff_settlement(run_id) == "already_published"
    assert deliver_handoff_settlement(get_run(run_id)) == "already_published"
    reconcile_unsettled_tool_runs()
    reconcile_unsettled_tool_runs(reap_orphans=True)

    notifications = tool_run_notifications()
    assert [item.id for item in notifications] == [expected_notification_id(run_id)]


def test_reconcile_pass_that_settles_a_proc_owned_run_delivers(
    tmp_path: Path,
) -> None:
    """A reconcile pass (e.g. ``tool show``) delivers for a run it settled."""

    run_id = reserve("proc", "proc-pass")
    claim(run_id, "proc", "proc-pass")
    # No proc row: the owner is missing and the worker identity is dead.
    reconcile_unsettled_tool_runs()
    reconcile_unsettled_tool_runs()
    assert get_run(run_id)["state"] == "lost"
    assert [item.id for item in tool_run_notifications()] == [
        expected_notification_id(run_id)
    ]


def test_monitor_owned_runs_produce_no_notification(tmp_path: Path) -> None:
    run_id = reserve("monitor", "mon-1")
    claim(run_id, "monitor", "mon-1")
    settle_monitor_tool_run(
        run_id, "mon-1", {"exit_code": 3, "termination_reason": "error"}
    )
    run = get_run(run_id)
    assert (run["state"], run["exit_code"], run["settled_by"]) == ("failed", 3, "owner")
    assert deliver_handoff_settlement(run_id) == "skipped"
    reconcile_unsettled_tool_runs()
    assert tool_run_notifications() == []


def test_delivery_skips_unsettled_foreground_and_unknown_runs() -> None:
    run_id = reserve("proc", "proc-skip")
    assert deliver_handoff_settlement(run_id) == "skipped"
    assert deliver_handoff_settlement("0" * 32) == "skipped"
    assert (
        deliver_handoff_settlement({"run_id": "x", "state": "succeeded"}) == "skipped"
    )
    assert tool_run_notifications() == []


def test_notification_carries_owner_log_when_it_exists(tmp_path: Path) -> None:
    log = tmp_path / "owner.log"
    log.write_text("output\n", encoding="utf-8")
    run_id = reserve("proc", "proc-log")
    claim(run_id, "proc", "proc-log", owner_log_path=str(log))
    settle_tool_run_followup(
        {
            "proc_id": "proc-log",
            "exit_code": 0,
            "termination_reason": "success",
            "followup": {"kind": "tool-run", "run_id": run_id},
        }
    )
    (note,) = tool_run_notifications()
    assert note.files == [str(log)]
    assert note.notes[0].startswith("Tool run ad-hoc succeeded")
