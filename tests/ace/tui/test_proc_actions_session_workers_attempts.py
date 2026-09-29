"""Update-attempt journal wiring for session and durable completions."""

from __future__ import annotations

from typing import Any

import pytest

from sase.ace.tui.actions.proc_actions import TrackedProcResult
from sase.ace.tui.proc_observer import ObservedProc, ProcProjection
from sase.core.time import local_now
from tests.ace.tui._proc_actions_session_workers_shared import (
    ProcHost,
    ok_result,
    sync_row,
)

__all__ = [
    "test_durable_delivery_skips_settle_for_collisions_and_other_lanes",
    "test_durable_plugin_update_delivery_schedules_settle",
    "test_non_update_session_worker_never_touches_journal",
    "test_session_worker_error_path_settles_failure_off_thread",
    "test_update_session_worker_begins_before_body_and_settles_before_complete",
    "test_update_session_worker_failure_view_then_success_clears",
]


class _AttemptHost(ProcHost):
    """Session host applying journal views with a direct thread hop."""

    def __init__(self, projection: ProcProjection | None = None) -> None:
        super().__init__(projection)
        self.applied_views: list[Any] = []

    def _apply_update_attempts_view(self, view: Any) -> None:
        self.applied_views.append(view)

    def call_from_thread(self, fn: Any, *args: Any) -> Any:
        return fn(*args)


def test_update_session_worker_begins_before_body_and_settles_before_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.actions._proc_action_submission as submission

    from sase.ace.update_attempts import UpdateAttemptsView

    events: list[str] = []
    sentinel = UpdateAttemptsView(revision=4, failure=None)
    monkeypatch.setattr(
        submission,
        "begin_update_attempt",
        lambda attempt: events.append("begin"),
    )
    monkeypatch.setattr(
        submission,
        "settle_update_attempt_for_result",
        lambda attempt, result, *, output: events.append("settle") or sentinel,
    )
    host = _AttemptHost()
    completions: list[Any] = []

    def body(_reporter: Any) -> TrackedProcResult[None]:
        events.append("body")
        return TrackedProcResult(success=True, message="done")

    def on_complete(completion: Any) -> None:
        events.append("complete")
        completions.append((completion, list(host.applied_views)))

    assert (
        host._submit_session_worker(
            "comprehensive-update", body, on_complete=on_complete
        )
        is not None
    )
    host.complete_session_worker()

    assert events == ["begin", "body", "settle", "complete"]
    assert completions[0][1] == [sentinel]
    assert completions[0][0].success is True


def test_update_session_worker_failure_view_then_success_clears(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.actions._proc_action_submission as submission

    from sase.ace._update_attempts_model import UpdateAttemptsView, UpdateFailure

    failure = UpdateFailure(
        attempt_id="a1",
        label="sase update",
        proc_type="comprehensive-update",
        stage="apply",
        started_at=1700000000.0,
        finished_at=1700000010.0,
        error="boom",
        output_tail="",
        interrupted=False,
    )
    views = [
        UpdateAttemptsView(revision=1, failure=failure),
        UpdateAttemptsView(revision=2, failure=None),
    ]
    monkeypatch.setattr(submission, "begin_update_attempt", lambda attempt: None)
    monkeypatch.setattr(
        submission,
        "settle_update_attempt_for_result",
        lambda attempt, result, *, output: views.pop(0),
    )
    host = _AttemptHost()
    completions: list[Any] = []

    host._submit_session_worker(
        "comprehensive-update",
        lambda _reporter: TrackedProcResult(success=False, message="no"),
        on_complete=completions.append,
    )
    host.complete_session_worker()
    host._submit_session_worker(
        "comprehensive-update",
        lambda _reporter: TrackedProcResult(success=True, message="yes"),
        on_complete=completions.append,
    )
    host.complete_session_worker(index=1)

    assert [completion.success for completion in completions] == [False, True]
    assert host.applied_views == [
        UpdateAttemptsView(revision=1, failure=failure),
        UpdateAttemptsView(revision=2, failure=None),
    ]


def test_non_update_session_worker_never_touches_journal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.actions._proc_action_submission as submission

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("journal must not be touched")

    monkeypatch.setattr(submission, "begin_update_attempt", _boom)
    monkeypatch.setattr(submission, "settle_update_attempt_for_result", _boom)
    host = _AttemptHost()
    completions: list[Any] = []

    host._submit_session_worker("sync", ok_result, on_complete=completions.append)
    host.complete_session_worker()

    assert len(completions) == 1
    assert host.workers[0].result.update_attempts is None
    assert host.applied_views == []


def test_session_worker_error_path_settles_failure_off_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.actions._proc_action_completion as completion

    from sase.ace.update_attempts import UpdateAttemptsView

    seen: dict[str, Any] = {}
    sentinel = UpdateAttemptsView(revision=9, failure=None)

    def _fake_settle(attempt: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        seen["attempt"] = attempt
        return sentinel

    monkeypatch.setattr(completion, "settle_update_attempt", _fake_settle)
    host = _AttemptHost()
    completions: list[Any] = []

    host._submit_session_worker(
        "comprehensive-update", ok_result, on_complete=completions.append
    )
    assert len(host.workers) == 1
    host.fail_session_worker()

    assert len(host.workers) == 2
    host.workers[1]._fn()

    assert seen["success"] is False
    assert seen["error"] == "boom"
    assert seen["attempt"].proc_type == "comprehensive-update"
    assert host.applied_views == [sentinel]
    assert completions[0].success is False


def test_durable_plugin_update_delivery_schedules_settle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.actions._proc_action_completion as completion

    from sase.ace.tui.actions._proc_action_types import ProcCallbackConfig
    from sase.ace.update_attempts import UpdateAttemptsView

    seen: dict[str, Any] = {}
    sentinel = UpdateAttemptsView(revision=3, failure=None)
    monkeypatch.setattr(
        completion,
        "settle_update_attempt",
        lambda attempt, **kwargs: seen.update(kwargs) or sentinel,
    )
    host = _AttemptHost()
    completions: list[Any] = []
    row = ObservedProc(
        proc_id="durable-1",
        proc_type="plugin.update",
        cl_name="sase",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
        display_name="plugin update",
    )

    host._deliver_tracked_completion(
        proc_id="durable-1",
        proc_info=row,
        result=TrackedProcResult(success=False, message="bad", error="bad"),
        output="out",
        config=ProcCallbackConfig(
            on_complete=completions.append,
            reload_on_complete=False,
            notify_on_complete=False,
        ),
    )

    assert len(completions) == 1
    assert len(host.workers) == 1
    host.workers[0]._fn()

    assert seen == {"success": False, "error": "bad", "output": "out"}
    assert host.applied_views == [sentinel]


def test_durable_delivery_skips_settle_for_collisions_and_other_lanes() -> None:
    from sase.ace.tui.actions._proc_action_types import ProcCallbackConfig

    host = _AttemptHost()
    completions: list[Any] = []

    def _deliver(row: ObservedProc, result: TrackedProcResult[None]) -> None:
        host._deliver_tracked_completion(
            proc_id=row.proc_id,
            proc_info=row,
            result=result,
            output="out",
            config=ProcCallbackConfig(
                on_complete=completions.append,
                reload_on_complete=False,
                notify_on_complete=False,
            ),
        )

    plugin_row = ObservedProc(
        proc_id="durable-1",
        proc_type="plugin.update",
        cl_name="sase",
        project_file="",
        status="running",
        message="running",
        started_at=local_now(),
        display_name="plugin update",
    )
    _deliver(
        plugin_row,
        TrackedProcResult(success=True, message="dup", collision=True),
    )
    _deliver(
        sync_row("sync-9"),
        TrackedProcResult(success=False, message="bad", error="bad"),
    )

    assert len(completions) == 2
    assert host.workers == []
    assert host.applied_views == []
