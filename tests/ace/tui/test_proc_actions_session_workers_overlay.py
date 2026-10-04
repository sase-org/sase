"""Session overlay, projection, and reporter-output coverage."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.proc_actions import TrackedProcResult
from sase.ace.tui.modals.plugins_browser_sase_update_procs import (
    running_background_procs,
)
from sase.ace.tui.proc_observer import (
    ObservedProc,
    ProcObserverSnapshot,
    ProcProjection,
)
from sase.core.time import local_now
from sase.procs import store as proc_store
from tests.ace.tui._proc_actions_session_workers_shared import (
    ProcHost,
    durable_row,
    ok_result,
)

__all__ = [
    "test_current_observer_snapshot_replaces_projection",
    "test_running_background_procs_excludes_monitor_turns",
    "test_session_and_durable_rows_dedup_and_exclude_across_overlay",
    "test_session_overlay_never_registers_observer_or_writes_store",
    "test_session_overlay_preserves_rows_across_observer_snapshots",
    "test_session_overlay_removes_row_after_success_and_error",
    "test_session_worker_appears_in_effective_projection_and_counts",
    "test_session_worker_logs_error_terminal_record",
    "test_session_worker_retains_reporter_output_on_completion",
    "test_stale_observer_snapshot_does_not_overwrite_current_projection",
    "test_thread_snapshot_delivery_passes_producing_observer",
]


def test_session_worker_appears_in_effective_projection_and_counts() -> None:
    host = ProcHost(ProcProjection(session_id="session-mine"))

    submitted = host._submit_session_worker(
        "sync", ok_result, display_name="local sync"
    )

    assert submitted is not None
    effective = host._effective_proc_projection()
    assert effective.active_count == 1
    assert [row.proc_id for row in effective.rows] == [submitted.proc_id]
    assert submitted.session_id == "session-mine"
    assert effective.scoped_rows(all_sessions=False) == [submitted]
    assert host.indicator_counts == [1]
    assert [item.identity for item in running_background_procs(host)] == [
        submitted.proc_id
    ]


def test_running_background_procs_excludes_monitor_turns() -> None:
    durable = durable_row(scope="sase-update")
    monitor_row = ObservedProc(
        proc_id="monitor-1",
        proc_type="detached",
        cl_name="sase",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
        origin="monitor",
    )
    host = ProcHost(
        ProcProjection(
            rows=(durable, monitor_row),
            active_count=2,
            active_monitor_count=1,
        )
    )

    # A detached monitor supervisor outlives ACE by design, so it must not
    # block a self-update restart the way an installation mutation does.
    assert [item.identity for item in running_background_procs(host)] == [
        durable.proc_id
    ]


def test_session_overlay_preserves_rows_across_observer_snapshots() -> None:
    host = ProcHost(ProcProjection(session_id="session-mine"))
    submitted = host._submit_session_worker("sync", ok_result)
    assert submitted is not None
    durable = durable_row(scope="other")

    host._apply_proc_observer_snapshot(
        ProcObserverSnapshot(
            projection=ProcProjection(
                rows=(durable,),
                active_count=1,
                session_id="session-mine",
            )
        )
    )

    effective = host._effective_proc_projection()
    assert {row.proc_id for row in effective.rows} == {
        submitted.proc_id,
        durable.proc_id,
    }
    assert effective.active_count == 2
    assert host._proc_projection.rows == (durable,)


def test_stale_observer_snapshot_does_not_overwrite_current_projection() -> None:
    seeded = durable_row(scope="seeded")
    host = ProcHost(
        ProcProjection(rows=(seeded,), active_count=1, session_id="session-mine")
    )
    previous = host._proc_observer
    host._proc_observer = SimpleNamespace()

    host._apply_proc_observer_snapshot(
        ProcObserverSnapshot(projection=ProcProjection(session_id="session-mine")),
        previous,
    )

    assert host._proc_projection.rows == (seeded,)


def test_current_observer_snapshot_replaces_projection() -> None:
    host = ProcHost(ProcProjection(session_id="session-mine"))
    durable = durable_row(scope="other")

    host._apply_proc_observer_snapshot(
        ProcObserverSnapshot(
            projection=ProcProjection(
                rows=(durable,),
                active_count=1,
                session_id="session-mine",
            )
        ),
        host._proc_observer,
    )

    assert host._proc_projection.rows == (durable,)


def test_thread_snapshot_delivery_passes_producing_observer() -> None:
    host = ProcHost()
    recorded: list[tuple[Any, ...]] = []
    host.call_from_thread = lambda fn, *args: recorded.append((fn, *args))
    snapshot = ProcObserverSnapshot(projection=ProcProjection())

    host._on_proc_observer_thread_snapshot(snapshot, host._proc_observer)

    assert recorded == [
        (host._apply_proc_observer_snapshot, snapshot, host._proc_observer)
    ]


def test_session_overlay_removes_row_after_success_and_error() -> None:
    host = ProcHost(ProcProjection(session_id="session-mine"))
    first = host._submit_session_worker("sync", ok_result)
    assert first is not None
    host.complete_session_worker()

    assert host._effective_proc_projection().rows == ()
    assert host.indicator_counts[-1] == 0
    assert running_background_procs(host) == []

    second = host._submit_session_worker("sync", ok_result)
    assert second is not None
    host.fail_session_worker(1)

    assert host._effective_proc_projection().rows == ()
    assert running_background_procs(host) == []


def test_session_and_durable_rows_dedup_and_exclude_across_overlay() -> None:
    host = ProcHost(
        ProcProjection(
            rows=(durable_row(scope="sase-update"),),
            active_count=1,
            session_id="session-mine",
        )
    )
    local = host._submit_session_worker(
        "agents-sync",
        ok_result,
        exclusive_scopes=("agents-sync",),
    )
    assert local is not None

    blocked_by_local = host._submit_session_worker(
        "agents-sync",
        ok_result,
        exclusive_scopes=("agents-sync",),
        duplicate_message="local already owns it",
    )
    blocked_by_durable = host._submit_session_worker(
        "sase-update",
        ok_result,
        exclusive_scopes=("sase-update",),
        duplicate_message="durable already owns it",
    )

    assert blocked_by_local is None
    assert blocked_by_durable is None
    assert host.notices == [
        ("local already owns it", "warning"),
        ("durable already owns it", "warning"),
    ]
    assert host._effective_proc_projection().scope_conflict({"agents-sync"}) is local
    assert host._effective_proc_projection().scope_conflict({"sase-update"}) is not None


def test_session_worker_retains_reporter_output_on_completion() -> None:
    host = ProcHost()
    completions: list[Any] = []

    def body(reporter: Any) -> TrackedProcResult[None]:
        reporter.phase("Doing work")
        reporter.log("live line")
        return TrackedProcResult(success=True, message="done")

    submitted = host._submit_session_worker(
        "sync",
        body,
        on_complete=completions.append,
    )
    assert submitted is not None

    host.complete_session_worker()

    assert len(completions) == 1
    completion = completions[0]
    assert completion.success is True
    assert "live line" in completion.output
    assert "==> Doing work" in completion.output
    assert "OK: done" in completion.output


def test_session_worker_logs_error_terminal_record() -> None:
    host = ProcHost()
    completions: list[Any] = []

    def body(_reporter: Any) -> TrackedProcResult[None]:
        raise RuntimeError("exploded")

    host._submit_session_worker("sync", body, on_complete=completions.append)
    host.complete_session_worker()

    assert completions[0].success is False
    assert "exploded" in completions[0].output
    assert "ERROR: exploded" in completions[0].output


def test_session_overlay_never_registers_observer_or_writes_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[object] = []
    monkeypatch.setattr(
        proc_store,
        "append_proc",
        lambda *args, **kwargs: writes.append((args, kwargs)),
    )
    host = ProcHost(ProcProjection(session_id="session-mine"))

    submitted = host._submit_session_worker("sync", ok_result)

    assert submitted is not None
    assert host.pending_count == 0
    assert host.submitted_handles == []
    assert writes == []
    assert submitted.store_backed is False
