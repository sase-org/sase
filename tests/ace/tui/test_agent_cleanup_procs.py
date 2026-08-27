"""Tracked-proc tests for Agents-tab kill/dismiss persistence.

Kill (``x``) and cleanup-panel (``X``) persistence must run as first-class
proc-queue procs: visible in the queue with readable labels, counted by the
quit flow, completed without a broad reload, and killable from the proc queue
modal without leaking inflight identities.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from textual.css.query import NoMatches

from sase.ace.tui.actions.agents import AgentsMixin
from sase.ace.tui.actions.proc_actions import (
    TrackedProcCompletion,
    TrackedProcResult,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.proc_observer import ObservedProc as ProcInfo
from tests.ace.tui._compat_proc_queue import ProcQueue


def _make_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "my_feature",
        "project_file": "/tmp/test.sase",
        "status": "RUNNING",
        "start_time": datetime(2026, 1, 1, 12, 0, 0),
        "workflow": "fix-hook",
        "pid": 12345,
        "raw_suffix": "fix_hook-12345-251230_151429",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _CleanupProcApp(AgentsMixin):
    """Harness driving the real proc queue with deferred worker execution."""

    def __init__(self, agents: list[Agent]) -> None:
        self._proc_queue = ProcQueue()
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._kill_persistence_inflight = set()
        self._dismiss_persistence_inflight = set()
        self._agent_status_overrides = {}
        self._dismissed_agents = set()
        self._dismissed_agent_objects = []
        self._marked_agents = set()
        self._scheduled: list[tuple[object, tuple[object, ...]]] = []
        self.notifications: list[tuple[str, str]] = []
        self.refresh_sources: list[str] = []
        self.reloads = 0
        self.pending_workers: list[Any] = []

    def notify(self, msg: str, severity: str = "information") -> None:
        self.notifications.append((msg, severity))

    def call_later(self, callback: object, *args: object) -> None:
        self._scheduled.append((callback, args))

    def query_one(self, *_args: Any, **_kwargs: Any) -> Any:
        raise NoMatches("no DOM in tests")

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail

    def _refilter_agents(self, *, prior_pos: int | None = None) -> None:
        del prior_pos

    def _refresh_notification_count(self) -> None:
        return

    async def _refresh_notification_count_async(self) -> None:
        return

    def _schedule_notification_snapshot_refresh(self) -> None:
        self._scheduled.append((self._refresh_notification_count_async, ()))

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        self.refresh_sources.append(source)

    def _reload_and_reposition(self) -> None:
        self.reloads += 1

    def _submit_durable_proc(
        self,
        argv: Any,
        *,
        operation: str = "",
        request: Any = None,
        request_fingerprint: str = "",
        concurrency_keys: Any = (),
        proc_type: str | None = None,
        display_name: str | None = None,
        cl_name: str = "",
        project_file: str = "",
        on_complete: Any = None,
        reload_on_complete: bool = False,
        notify_on_complete: bool = False,
        live_body: Any = None,
        on_settled: Any = None,
        **kwargs: Any,
    ) -> Any:
        del argv, request_fingerprint, concurrency_keys, kwargs
        from sase.ace.tui.actions.agents._cleanup_procs import _CleanupProcOutcome
        from sase.ace.tui.actions.proc_actions import TrackedProcResult
        from sase.ops.commands.agent import _apply_cleanup_payload_for_result
        from sase.ops.names import AGENT_CLEANUP

        payload = dict(request or {})

        def _callable() -> TrackedProcResult[Any]:
            try:
                if live_body is not None:
                    outcome = live_body()
                    if isinstance(outcome, _CleanupProcOutcome):
                        return TrackedProcResult(
                            success=outcome.success,
                            message=outcome.message,
                            payload=outcome,
                            error=outcome.message if not outcome.success else None,
                        )
                    return outcome
                if operation == AGENT_CLEANUP:
                    success, message, result_payload = (
                        _apply_cleanup_payload_for_result(payload)
                    )
                    return TrackedProcResult(
                        success=success,
                        message=message,
                        payload=dict(result_payload),
                        error=None if success else message,
                    )
                return TrackedProcResult(success=True, message="ok")
            finally:
                if on_settled is not None:
                    on_settled()

        return self._submit_tracked_proc(
            proc_type or "cleanup",
            cl_name,
            project_file,
            _callable,
            display_name=display_name,
            on_complete=on_complete,
            reload_on_complete=reload_on_complete,
            notify_on_complete=notify_on_complete,
        )

    def _submit_tracked_proc(
        self,
        proc_type: str,
        cl_name: str,
        project_file: str,
        proc_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> ProcInfo:
        del duplicate_message, reload_on_complete, notify_on_complete
        proc_info = self._proc_queue.submit(
            proc_type,
            cl_name,
            project_file,
            display_name=display_name,
            dedup_key=dedup_key,
        )

        def _worker_body() -> TrackedProcResult[Any]:
            result = proc_callable()
            if isinstance(result, TrackedProcResult):
                return result
            return TrackedProcResult(
                success=getattr(result, "success", True),
                message=str(getattr(result, "message", "ok")),
                payload=result,
                error=None if getattr(result, "success", True) else str(result),
            )

        worker = self.run_worker(_worker_body, thread=True)
        worker.proc_info = proc_info
        worker.on_complete = on_complete
        return proc_info

    def run_worker(self, fn: Any, *, thread: bool = False) -> Any:
        """Defer the worker body so tests can observe the running proc."""
        assert thread is True
        worker = SimpleNamespace(result=None, error=None, _fn=fn, cancelled=False)

        def _cancel() -> None:
            worker.cancelled = True

        worker.cancel = _cancel
        self.pending_workers.append(worker)
        return worker

    def run_pending_worker(self, idx: int = 0) -> None:
        """Run a deferred worker body and dispatch its completion."""
        worker = self.pending_workers[idx]
        worker.result = worker._fn()
        self._on_proc_worker_completed(worker)

    def _on_proc_worker_completed(self, worker: Any) -> None:
        proc_info = worker.proc_info
        if getattr(worker, "cancelled", False):
            return
        result = worker.result
        proc_info.status = "success" if result.success else "error"
        proc_info.message = result.message
        proc_info.error = result.error
        completion: TrackedProcCompletion[Any] = TrackedProcCompletion(
            proc_info=proc_info,
            success=result.success,
            message=result.message,
            output="",
            payload=result.payload,
            error=result.error,
        )
        on_complete = getattr(worker, "on_complete", None)
        if on_complete is not None:
            on_complete(completion)

    def _kill_proc(self, proc_id: str) -> bool:
        proc = self._proc_queue.get(proc_id)
        if proc is None:
            return False
        proc.status = "error"
        proc.message = "Killed by user"
        proc.error = "Killed by user"
        for worker in self.pending_workers:
            if getattr(worker, "proc_info", None) is proc:
                worker.cancel()
                break
        return True


_KILL_PATCHES = (
    "sase.ace.tui.actions.agents._killing.persist_kill_side_effects",
    "sase.ace.dismissed_agents.save_dismissed_agents",
    "sase.ace.tui.actions.agents._killing.sync_dismissed_agent_artifact_index",
    "sase.ace.tui.actions.agents._killing.dismiss_notifications_for_agents",
)


def test_kill_agent_submits_tracked_proc_counted_by_quit_flow() -> None:
    """``x`` persistence appears as a running proc until the worker completes."""
    agent = _make_agent()
    app = _CleanupProcApp([agent])

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)

    # Optimistic stage already ran; persistence is a visible running proc.
    assert app._agents == []
    assert app._proc_queue.running_count == 1
    proc = app._proc_queue.get_all()[0]
    assert proc.proc_type == "kill"
    assert proc.label == f"kill {agent.display_name}"
    toasts_before_completion = list(app.notifications)

    with (
        patch(_KILL_PATCHES[0]),
        patch(_KILL_PATCHES[1]),
        patch(_KILL_PATCHES[2]),
        patch(_KILL_PATCHES[3]),
    ):
        app.run_pending_worker()

    assert app._proc_queue.running_count == 0
    assert proc.status == "success"
    # Success stays quiet (the optimistic toast already fired) and performs
    # no broad reload; only the off-thread notification refresh is scheduled.
    assert app.notifications == toasts_before_completion
    assert app.reloads == 0
    assert app.refresh_sources == []
    assert (app._refresh_notification_count_async, ()) in app._scheduled
    assert app._kill_persistence_inflight == set()


def test_bulk_kill_mixed_cleanup_uses_combined_label() -> None:
    """Mixed bulk cleanups read as ``kill N + dismiss M agents``."""
    running = _make_agent(cl_name="feature_one", pid=111)
    done = _make_agent(
        cl_name="feature_two",
        status="DONE",
        pid=None,
        workflow=None,
        raw_suffix="20260101120000",
    )
    app = _CleanupProcApp([running, done])

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_bulk_kill_agents([running], [done])

    assert app._proc_queue.running_count == 1
    assert app._proc_queue.get_all()[0].label == "kill 1 + dismiss 1 agents"


def test_dismiss_done_agent_submits_tracked_dismiss_proc() -> None:
    """Single dismiss-only cleanup runs as a tracked ``dismiss`` proc."""
    agent = _make_agent(status="DONE", pid=None, workflow=None)
    app = _CleanupProcApp([agent])

    app._dismiss_done_agent(agent)

    assert app._proc_queue.running_count == 1
    proc = app._proc_queue.get_all()[0]
    assert proc.proc_type == "dismiss"
    assert proc.label == f"dismiss {agent.display_name}"

    with patch(
        "sase.ace.tui.actions.agents._dismissing.persist_single_dismiss_transaction"
    ) as mock_persist:
        app.run_pending_worker()

    mock_persist.assert_called_once()
    assert app._proc_queue.running_count == 0
    assert proc.status == "success"
    assert app._dismiss_persistence_inflight == set()


def test_do_dismiss_all_submits_tracked_bulk_dismiss_proc() -> None:
    """Bulk dismiss-done runs as one tracked ``dismiss N agents`` proc."""
    a1 = _make_agent(cl_name="a", status="DONE", pid=None, workflow=None)
    a2 = _make_agent(
        cl_name="b",
        status="DONE",
        pid=None,
        workflow=None,
        raw_suffix="20260101130000",
    )
    app = _CleanupProcApp([a1, a2])

    app._do_dismiss_all([a1, a2])

    assert app._proc_queue.running_count == 1
    assert app._proc_queue.get_all()[0].label == "dismiss 2 agents"


def test_kill_persistence_failure_preserves_toast_and_recovery_refresh() -> None:
    """Worker failure keeps today's error toast and recovery refresh."""
    agent = _make_agent()
    app = _CleanupProcApp([agent])

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)

    with patch(
        "sase.ace.tui.actions.agents._kill_transactions.persist_single_kill_transaction",
        side_effect=RuntimeError("boom"),
    ):
        app.run_pending_worker()

    proc = app._proc_queue.get_all()[0]
    assert proc.status == "error"
    assert ("Kill cleanup failed: boom", "error") in app.notifications
    assert app.refresh_sources == ["kill_error_recovery"]
    assert app._kill_persistence_inflight == set()


def test_duplicate_submission_for_inflight_identity_is_skipped() -> None:
    """A second submission for an inflight identity is silently dropped."""
    agent = _make_agent()
    app = _CleanupProcApp([agent])

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)
    toasts = list(app.notifications)

    app._submit_kill_persistence_proc(agent, "hook", [agent], {agent.identity})

    assert app._proc_queue.running_count == 1
    assert app.notifications == toasts


def test_killing_cleanup_proc_from_modal_releases_inflight() -> None:
    """Proc-queue kill marks the proc killed, fires no completion effects,
    and the worker body's finally still releases the inflight identity."""
    agent = _make_agent()
    app = _CleanupProcApp([agent])

    with patch("sase.ace.tui.actions.agents._killing.os.killpg"):
        app._do_kill_agent(agent)
    proc = app._proc_queue.get_all()[0]
    toasts = list(app.notifications)

    assert app._kill_proc(proc.proc_id)
    assert proc.status == "error"
    assert proc.error == "Killed by user"
    assert app._proc_queue.running_count == 0

    # Thread cancellation is cooperative: the worker body still runs to
    # completion, releasing the inflight identity without completion effects.
    with (
        patch(_KILL_PATCHES[0]),
        patch(_KILL_PATCHES[1]),
        patch(_KILL_PATCHES[2]),
        patch(_KILL_PATCHES[3]),
    ):
        app.pending_workers[0]._fn()

    assert app._kill_persistence_inflight == set()
    assert app.notifications == toasts
    assert app.reloads == 0

    # The same agent can be cleaned up again once the identity is released.
    app._submit_kill_persistence_proc(agent, "hook", [agent], {agent.identity})
    assert app._proc_queue.running_count == 1
