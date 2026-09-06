"""In-flight ``,X`` deferred kill: restore the prompt now, kill at T4.

Phase 3 of the kill-and-edit-last-launch epic. These tests cover the
completion-callback kill, the replacement-launch hold, timeout, failure,
typed-admission scoping, and WAITING/QUEUED dismiss routing.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from types import SimpleNamespace
from typing import Any

from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
    KillAndEditLastLaunchMixin,
    apply_deferred_launch_kill_on_completion,
)
from sase.ace.tui.actions.agent_workflow._launch_procs import (
    LaunchProcMixin,
    _LaunchProcOutcome,
)
from sase.ace.tui.actions.agent_workflow._launch_records import (
    LaunchRecordState,
    has_pending_launch_kill,
    latest_live_launch_record,
    push_launch_record,
)
from sase.ace.tui.actions.agent_workflow._relaunch_barrier import (
    hold_launch_for_relaunch_cleanup,
    release_relaunch_holds_if_idle,
)
from sase.ace.tui.actions.proc_actions import TrackedProcCompletion
from sase.ace.tui.proc_observer import ObservedProc

from tests.ace.tui._kill_and_edit_last_launch_helpers import (
    _FakeAgent,
    _artifacts_dir,
    _context,
    _matchable_result,
)


def _completion(
    proc_id: str,
    payload: object,
    *,
    success: bool = True,
) -> TrackedProcCompletion[object]:
    return TrackedProcCompletion(
        proc_info=ObservedProc(
            proc_id=proc_id,
            proc_type="launch",
            cl_name="demo",
            project_file="/tmp/projects/demo/demo.sase",
            status="success" if success else "error",
            message="done",
            started_at=datetime.now(),
            display_name="launch demo",
        ),
        success=success,
        message="done",
        output="",
        payload=payload,
        error=None if success else "failed",
    )


class _DeferredKillApp(KillAndEditLastLaunchMixin, LaunchProcMixin):
    """Records kill/dismiss/hold effects of the deferred-kill completion path."""

    def __init__(self) -> None:
        self._agents_with_children: list[Any] = []
        self._agents: list[Any] = []
        self.notifications: list[tuple[str, str | None]] = []
        self.killed: list[Any] = []
        self.dismissed: list[Any] = []
        self.bulk_kill_calls: list[tuple[list[Any], list[Any]]] = []
        self.edit_calls: list[tuple[str, str, str, bool]] = []
        self.bulk_edit_calls: list[list[str]] = []
        self.delta_calls: list[Any] = []
        self.stash_calls: list[str] = []
        self.timers: list[Any] = []
        self.resumed: list[str] = []
        self._prompt_context: object | None = SimpleNamespace()
        self._prompt_bar: Any | None = None
        self._settle_immediately = True

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _handle_launch_results_delta(self, results: object) -> None:
        self.delta_calls.append(results)

    def request_agents_refresh(self, source: str) -> None:
        del source

    def _schedule_agents_async_refresh(self, *, source: str = "launch") -> None:
        del source

    def _schedule_prompt_stash_badge_refresh(self) -> None:
        pass

    def _schedule_failed_launch_prompt_recovery(self, submitted_prompt: str) -> None:
        self.stash_calls.append(submitted_prompt)

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.edit_calls.append((raw_prompt, project_file, cl_name, is_project_agent))

    def _edit_and_relaunch_agents_bulk(
        self,
        raw_prompts: list[str],
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        del project_file, cl_name, is_project_agent
        self.bulk_edit_calls.append(list(raw_prompts))

    def _mounted_prompt_bar(self) -> Any | None:
        return self._prompt_bar

    def set_timer(
        self, delay: float, callback: Callable[[], None], name: str = ""
    ) -> Any:
        timer = SimpleNamespace(
            stop=lambda: None, callback=callback, delay=delay, name=name
        )
        self.timers.append(timer)
        return timer

    def _do_kill_agent(
        self,
        agent: Any,
        cleanup_plan: Any = None,
        *,
        on_settled: Callable[[], None] | None = None,
    ) -> bool:
        del cleanup_plan
        self.killed.append(agent)
        if self._settle_immediately and on_settled is not None:
            on_settled()
        return True

    def _dismiss_done_agent(
        self, agent: Any, *, on_settled: Callable[[], None] | None = None
    ) -> bool:
        self.dismissed.append(agent)
        if self._settle_immediately and on_settled is not None:
            on_settled()
        return True

    def _do_bulk_kill_agents(
        self,
        killable: list[Any],
        dismissable: list[Any] | None = None,
        *,
        on_settled: Callable[[], None] | None = None,
    ) -> bool:
        dismissable = dismissable or []
        self.bulk_kill_calls.append((list(killable), list(dismissable)))
        if self._settle_immediately and on_settled is not None:
            on_settled()
        return True


def _running_row(name: str, timestamp: str) -> _FakeAgent:
    return _FakeAgent(
        name,
        status="RUNNING",
        pid=111,
        artifacts_dir_value=_artifacts_dir("proj", timestamp),
    )


def test_pending_placeholder_kill_intent_is_found_exactly_once() -> None:
    app = _DeferredKillApp()
    placeholder = "pending-abc-uuid"
    record = push_launch_record(
        app,
        proc_ids=(placeholder,),
        prompt="do work",
        context=_context("demo"),
    )
    assert record is not None
    agent = _running_row("solo", "20260903170000")
    app._agents_with_children = [agent]

    app._kill_and_edit_last_launch()
    assert record.state is LaunchRecordState.KILL_PENDING

    result = _matchable_result("proj", "20260903170000")
    outcome = _LaunchProcOutcome("Started 1 agent", results=(result,))
    app._on_launch_proc_complete(_completion(placeholder, outcome))

    assert app.killed == [agent]
    assert record.state is LaunchRecordState.CONSUMED
    assert latest_live_launch_record(app) is None

    app._on_launch_proc_complete(_completion(placeholder, outcome))
    assert app.killed == [agent]


def test_inflight_kill_parks_replacement_until_cleanup_settles() -> None:
    app = _DeferredKillApp()
    app._settle_immediately = False
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="%id:foo\nDo work", context=_context("foo")
    )
    assert record is not None
    agent = _running_row("foo", "20260903170000")
    app._agents_with_children = [agent]

    app._kill_and_edit_last_launch()
    assert has_pending_launch_kill(app)

    parked: list[str] = []
    held = hold_launch_for_relaunch_cleanup(app, lambda: parked.append("replayed"))
    assert held is True
    assert parked == []
    assert any("last launch to finish" in message for message, _ in app.notifications)

    app._on_launch_proc_complete(
        _completion(
            "p1",
            _LaunchProcOutcome(
                "Started 1 agent",
                results=(_matchable_result("proj", "20260903170000"),),
            ),
        )
    )
    assert app.killed == [agent]
    assert parked == []
    assert record.state is LaunchRecordState.CONSUMED

    barriers = getattr(app, "_relaunch_cleanup_barriers", [])
    assert len(barriers) == 1
    from sase.ace.tui.actions.agent_workflow._relaunch_barrier import (
        settle_relaunch_cleanup_barrier,
    )

    settle_relaunch_cleanup_barrier(app, barriers[0])
    assert parked == ["replayed"]


def test_failed_launch_with_pending_intent_discards_and_stashes_once() -> None:
    app = _DeferredKillApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="do work", context=_context("demo")
    )
    assert record is not None
    app._launch_submitted_prompts = {"p1": "do work"}

    app._kill_and_edit_last_launch()
    assert record.state is LaunchRecordState.KILL_PENDING

    app._on_launch_proc_complete(_completion("p1", None, success=False))

    assert app.killed == []
    assert app.dismissed == []
    assert app.stash_calls == ["do work"]
    assert record.state is LaunchRecordState.FAILED
    assert not has_pending_launch_kill(app)
    assert any(
        "kill-on-finish was cancelled" in message for message, _ in app.notifications
    )

    parked: list[str] = []
    held = hold_launch_for_relaunch_cleanup(app, lambda: parked.append("replayed"))
    assert held is False


def test_fan_out_n_results_n_kills_in_order() -> None:
    app = _DeferredKillApp()
    record = push_launch_record(
        app,
        proc_ids=("p1",),
        prompt="one ---\n two",
        context=_context("fan"),
    )
    assert record is not None
    first = _running_row("first", "20260903170001")
    second = _running_row("second", "20260903170002")
    app._agents_with_children = [second, first]

    app._kill_and_edit_last_launch()
    app._on_launch_proc_complete(
        _completion(
            "p1",
            _LaunchProcOutcome(
                "Started 2 agents",
                results=(
                    _matchable_result("proj", "20260903170001"),
                    _matchable_result("proj", "20260903170002"),
                ),
            ),
        )
    )

    assert len(app.bulk_kill_calls) == 1
    killable, dismissable = app.bulk_kill_calls[0]
    assert [agent.name for agent in killable] == ["first", "second"]
    assert dismissable == []
    assert app.killed == []


def test_budget_expiry_abandons_auto_kill_and_replays_held_launch() -> None:
    app = _DeferredKillApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="do work", context=_context("slow")
    )
    assert record is not None
    agent = _running_row("slow", "20260903170000")
    app._agents_with_children = [agent]

    app._kill_and_edit_last_launch()
    parked: list[str] = []
    assert hold_launch_for_relaunch_cleanup(app, lambda: parked.append("replayed"))

    timeout = next(
        timer for timer in app.timers if timer.name == "pending-launch-kill-timeout"
    )
    timeout.callback()

    assert record.state is LaunchRecordState.IN_FLIGHT
    assert not has_pending_launch_kill(app)
    assert parked == ["replayed"]
    assert any("took too long" in message for message, _ in app.notifications)

    app._on_launch_proc_complete(
        _completion(
            "p1",
            _LaunchProcOutcome(
                "Started 1 agent",
                results=(_matchable_result("proj", "20260903170000"),),
            ),
        )
    )
    assert app.killed == []
    assert record.state is LaunchRecordState.RESOLVED


def test_admission_complete_false_kills_returned_results_and_warns() -> None:
    app = _DeferredKillApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="%if:gated", context=_context("gated")
    )
    assert record is not None
    agent = _running_row("gated", "20260903170000")
    app._agents_with_children = [agent]

    app._kill_and_edit_last_launch()
    app._on_launch_proc_complete(
        _completion(
            "p1",
            _LaunchProcOutcome(
                "Accepted 2 launch units; admission continues in the background",
                results=(_matchable_result("proj", "20260903170000"),),
                admission_complete=False,
            ),
        )
    )

    assert app.killed == [agent]
    assert any(
        "gated units continue in the background" in message
        for message, _ in app.notifications
    )


def test_waiting_row_takes_dismiss_path() -> None:
    """WAITING/QUEUED rows are admission-deferred: dismiss, don't signal-kill.

    Plain ``,x`` on such a row shares this question today: ACE has no
    operation that tears down a typed-admission coordinator still launching
    remaining units after the launch proc exits.
    """
    app = _DeferredKillApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="wait", context=_context("waiting")
    )
    assert record is not None
    waiting = _FakeAgent(
        "waiting",
        status="WAITING",
        pid=None,
        artifacts_dir_value=_artifacts_dir("proj", "20260903170000"),
    )
    queued = _FakeAgent(
        "queued",
        status="QUEUED",
        pid=None,
        artifacts_dir_value=_artifacts_dir("proj", "20260903170001"),
    )
    app._agents_with_children = [waiting]

    apply_deferred_launch_kill_on_completion(
        app,
        "p1",
        (_matchable_result("proj", "20260903170000"),),
        failed=False,
    )
    # Record is not KILL_PENDING yet, so this is a no-op until we mark it.
    assert app.dismissed == []

    app._kill_and_edit_last_launch()
    apply_deferred_launch_kill_on_completion(
        app,
        "p1",
        (_matchable_result("proj", "20260903170000"),),
        failed=False,
    )
    assert app.dismissed == [waiting]
    assert app.killed == []

    app2 = _DeferredKillApp()
    push_launch_record(
        app2, proc_ids=("p2",), prompt="queue", context=_context("queued")
    )
    app2._agents_with_children = [queued]
    app2._kill_and_edit_last_launch()
    apply_deferred_launch_kill_on_completion(
        app2,
        "p2",
        (_matchable_result("proj", "20260903170001"),),
        failed=False,
    )
    assert app2.dismissed == [queued]
    assert app2.killed == []


def test_release_relaunch_holds_if_idle_is_noop_while_pending_kill_exists() -> None:
    app = _DeferredKillApp()
    push_launch_record(app, proc_ids=("p1",), prompt="p", context=_context("demo"))
    app._kill_and_edit_last_launch()
    parked: list[str] = []
    hold_launch_for_relaunch_cleanup(app, lambda: parked.append("replayed"))
    release_relaunch_holds_if_idle(app)
    assert parked == []
