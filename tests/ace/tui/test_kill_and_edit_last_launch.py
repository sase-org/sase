"""Tests for ``,X`` — kill and edit this session's last launched agent.

Marks are always ignored: ``,X`` targets the newest launch record this ACE
session accepted, never the focused/marked row(s). These tests cover the
launch-record -> loaded-row join, the state-machine dispatch (in-flight
toast, resolved single/multi delegation, pop-to-next-record on a
already-dead target), and the bulk kill-and-edit composition for a
multi-result record.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pytest

from sase.ace.tui.actions.agent_workflow._entry_relaunch import EntryRelaunchMixin
from sase.ace.tui.actions.agent_workflow._kill_last_launch import (
    KillAndEditLastLaunchMixin,
    _agent_for_launch_result,
    _matched_agents_for_record,
)
from sase.ace.tui.actions.agent_workflow._launch_records import (
    LaunchRecordState,
    LaunchRecordContext,
    latest_live_launch_record,
    push_launch_record,
    stamp_launch_record_results,
)
from sase.ace.tui.actions.agents._marking import AgentMarkingMixin
from sase.ace.tui.modals import ConfirmKillModal
from sase.ace.tui.models.agent import AgentType
from sase.agent.launch_types import AgentLaunchResult

AgentIdentity = tuple[str, str, str | None]


@dataclass
class _FakeAgent:
    """Minimal duck-typed row used by the join and dispatch tests."""

    name: str
    raw_prompt: str | None = "Do work"
    status: str = "DONE"
    pid: int | None = None
    project_file: str = "/tmp/proj/proj.sase"
    cl_name: str = "branch"
    is_project_agent: bool = False
    restartable: bool = True
    is_clan_container: bool = False
    is_gate: bool = False
    agent_family: str | None = None
    agent_family_parallel: bool = False
    role_suffix: str | None = None
    phase_bead_id: str | None = None
    is_family_root_entry: bool = False
    artifacts_dir_value: str | None = None
    agent_type: AgentType = AgentType.RUNNING
    workspace_num: int | None = None

    @property
    def identity(self) -> AgentIdentity:
        return (self.agent_type, self.name, None)

    @property
    def display_name(self) -> str:
        return self.name

    @property
    def agent_name(self) -> str:
        return self.name

    def get_raw_xprompt_content(self) -> str | None:
        return self.raw_prompt

    def get_artifacts_dir(self) -> str | None:
        return self.artifacts_dir_value


def _context(display_name: str = "demo") -> LaunchRecordContext:
    return LaunchRecordContext(
        display_name=display_name,
        project_file=f"/tmp/projects/{display_name}/{display_name}.sase",
        cl_name=display_name,
        is_project_agent=True,
    )


def _artifacts_dir(project: str, timestamp: str) -> str:
    return f"/tmp/fake_projects/{project}/artifacts/ace-run/{timestamp}"


def _matchable_result(project: str, timestamp: str) -> AgentLaunchResult:
    """Build a result whose joinable artifact dir is a pure path computation.

    Leaving ``project_name``/``timestamp`` unset on the result routes
    ``artifact_dir_from_launch_result`` through its ``output_path`` fallback
    (a plain ``.../artifacts/<workflow>/<14-digit timestamp>`` parse), which
    needs no real project registration or on-disk fixture.
    """
    return AgentLaunchResult(
        pid=100,
        workspace_num=1,
        workspace_dir="/tmp/ws",
        output_path=f"{_artifacts_dir(project, timestamp)}/live_reply.md",
    )


# --- join: AgentLaunchResult -> loaded row ----------------------------------


def test_agent_for_launch_result_matches_on_artifacts_dir() -> None:
    target_dir = _artifacts_dir("proj", "20260903170000")
    agent = _FakeAgent("agent-a", artifacts_dir_value=target_dir)
    other = _FakeAgent("agent-b", artifacts_dir_value="/tmp/somewhere/else")
    result = _matchable_result("proj", "20260903170000")

    assert _agent_for_launch_result([other, agent], result) is agent


def test_agent_for_launch_result_returns_none_when_row_is_gone() -> None:
    result = _matchable_result("proj", "20260903170000")
    still_loaded = _FakeAgent("agent-a", artifacts_dir_value="/tmp/unrelated")

    assert _agent_for_launch_result([still_loaded], result) is None


def test_matched_agents_for_record_follows_proc_id_order_and_skips_gone_rows() -> None:
    record = push_launch_record(
        SimpleNamespace(),
        proc_ids=("p1", "p2"),
        prompt="prompt",
        context=_context(),
    )
    assert record is not None
    dir1 = _artifacts_dir("proj", "20260903170001")
    dir2 = _artifacts_dir("proj", "20260903170002")
    record.results["p1"] = (_matchable_result("proj", "20260903170001"),)
    record.results["p2"] = (_matchable_result("proj", "20260903170002"),)

    second_only = [_FakeAgent("second", artifacts_dir_value=dir2)]
    assert _matched_agents_for_record(record, second_only) == second_only

    both = [
        _FakeAgent("second", artifacts_dir_value=dir2),
        _FakeAgent("first", artifacts_dir_value=dir1),
    ]
    matched = _matched_agents_for_record(record, both)
    # Order follows proc_ids (p1, p2), i.e. launch order, not row order.
    assert [a.name for a in matched] == ["first", "second"]


# --- dispatch state machine -------------------------------------------------


class _DispatchApp(KillAndEditLastLaunchMixin):
    """Records which delegate the dispatcher chose, without exercising it."""

    def __init__(self) -> None:
        self._agents_with_children: list[_FakeAgent] = []
        self.notifications: list[tuple[str, str | None]] = []
        self.single_targets: list[_FakeAgent] = []
        self.set_targets: list[list[_FakeAgent]] = []
        self.revealed: list[Any] = []
        self.edit_calls: list[tuple[str, str, str, bool]] = []
        self.bulk_edit_calls: list[dict[str, Any]] = []
        self.timers: list[Any] = []
        self._prompt_bar: Any | None = None

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def _reveal_last_launch_target(self, target_identity: Any) -> None:
        self.revealed.append(target_identity)

    def _kill_and_edit_agent(
        self,
        target: _FakeAgent | None = None,
        *,
        on_initiated: Callable[[bool], None] | None = None,
    ) -> None:
        assert target is not None
        self.single_targets.append(target)
        if on_initiated is not None:
            on_initiated(True)

    def _kill_and_edit_last_launch_set(
        self,
        agents: list[_FakeAgent],
        *,
        on_initiated: Callable[[bool], None] | None = None,
    ) -> None:
        self.set_targets.append(agents)
        if on_initiated is not None:
            on_initiated(True)

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
        self.bulk_edit_calls.append(
            {
                "prompts": list(raw_prompts),
                "project_file": project_file,
                "cl_name": cl_name,
                "is_project_agent": is_project_agent,
            }
        )

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


def test_no_live_record_notifies_and_does_nothing() -> None:
    app = _DispatchApp()

    app._kill_and_edit_last_launch()

    assert app.notifications == [("No recent launch to kill and edit", "warning")]
    assert app.single_targets == []
    assert app.set_targets == []


def test_in_flight_record_restores_prompt_and_marks_kill_pending() -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="do the thing", context=_context("demo")
    )
    assert record is not None

    app._kill_and_edit_last_launch()

    assert app.edit_calls == [
        ("do the thing", record.context.project_file, record.context.cl_name, True)
    ]
    assert app.single_targets == []
    assert app.set_targets == []
    assert app.notifications == [('Will kill "demo" when its launch finishes', None)]
    from sase.ace.tui.actions.agent_workflow._launch_records import (
        LaunchRecordState,
    )

    assert record.state is LaunchRecordState.KILL_PENDING
    assert len(app.timers) == 1
    assert app.timers[0].name == "pending-launch-kill-timeout"


def test_kill_pending_repeat_refocuses_and_does_not_advance() -> None:
    app = _DispatchApp()
    older = push_launch_record(
        app, proc_ids=("older",), prompt="older", context=_context("older")
    )
    newer = push_launch_record(
        app, proc_ids=("newer",), prompt="newer", context=_context("newer")
    )
    assert older is not None and newer is not None
    bar = SimpleNamespace(focus_count=0)

    def focus() -> None:
        bar.focus_count += 1

    bar.focus = focus
    app._prompt_bar = bar

    app._kill_and_edit_last_launch()
    assert newer.state.value == "kill_pending"
    assert app.edit_calls == [
        ("newer", newer.context.project_file, newer.context.cl_name, True)
    ]

    app._kill_and_edit_last_launch()

    assert bar.focus_count == 1
    assert app.edit_calls == [
        ("newer", newer.context.project_file, newer.context.cl_name, True)
    ]
    assert app.single_targets == []
    assert len(app.timers) == 1
    from sase.ace.tui.actions.agent_workflow._launch_records import (
        LaunchRecordState,
        latest_live_launch_record,
    )

    assert newer.state is LaunchRecordState.KILL_PENDING
    assert older.state is LaunchRecordState.IN_FLIGHT
    assert latest_live_launch_record(app) is newer


def test_inflight_bulk_record_mounts_per_unit_prompts() -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app,
        proc_ids=("p1", "p2"),
        prompt="shared",
        context=_context("bulk 2 Patches"),
        submitted_prompts={"p1": "#gh:alpha shared", "p2": "#gh:beta shared"},
    )
    assert record is not None

    app._kill_and_edit_last_launch()

    assert app.edit_calls == []
    assert app.bulk_edit_calls == [
        {
            "prompts": ["#gh:alpha shared", "#gh:beta shared"],
            "project_file": record.context.project_file,
            "cl_name": record.context.cl_name,
            "is_project_agent": True,
        }
    ]


def test_inflight_handler_does_no_synchronous_disk_or_proc_store_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("demo")
    )
    assert record is not None

    def fail_disk(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("in-flight ,X must not touch disk or the proc store")

    monkeypatch.setattr("os.stat", fail_disk)
    monkeypatch.setattr("os.listdir", fail_disk)
    monkeypatch.setattr("pathlib.Path.exists", fail_disk)
    monkeypatch.setattr("pathlib.Path.is_dir", fail_disk)
    monkeypatch.setattr("pathlib.Path.read_text", fail_disk)

    app._kill_and_edit_last_launch()

    assert record.state.value == "kill_pending"
    assert app.edit_calls


def test_resolved_single_match_reveals_and_delegates_to_kill_and_edit_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("demo")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))

    agent = _FakeAgent("solo")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, agents: [agent],
    )

    app._kill_and_edit_last_launch()

    assert app.single_targets == [agent]
    assert app.set_targets == []
    assert app.revealed == [agent.identity]
    from sase.ace.tui.actions.agent_workflow._launch_records import (
        LaunchRecordState,
        latest_live_launch_record,
    )

    assert record.state is LaunchRecordState.CONSUMED
    assert latest_live_launch_record(app) is None


def test_resolved_multi_match_delegates_to_bulk_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    record = push_launch_record(
        app, proc_ids=("p1", "p2"), prompt="p", context=_context("bulk 2 Patches")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))

    agents = [_FakeAgent("alpha"), _FakeAgent("beta")]
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: agents,
    )

    app._kill_and_edit_last_launch()

    assert app.single_targets == []
    assert app.set_targets == [agents]
    assert app.revealed == [agents[0].identity]


def test_already_dead_target_pops_to_next_live_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _DispatchApp()
    stale = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("stale")
    )
    live = push_launch_record(
        app, proc_ids=("p2",), prompt="p", context=_context("live")
    )
    assert stale is not None and live is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))

    agent = _FakeAgent("still-here")
    calls: list[Any] = []

    def fake_matcher(record: Any, loaded: Any) -> list[_FakeAgent]:
        calls.append(record)
        # Newest record is already gone; pop it and take the older live one.
        return [] if record is live else [agent]

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        fake_matcher,
    )

    app._kill_and_edit_last_launch()

    assert calls == [live, stale]
    assert app.single_targets == [agent]
    from sase.ace.tui.actions.agent_workflow._launch_records import (
        LaunchRecordState,
    )

    assert stale.state is LaunchRecordState.CONSUMED
    assert live.state is LaunchRecordState.CONSUMED


def test_second_press_after_consumption_targets_next_record_via_fresh_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A repeat ``,X`` after a record is consumed only reaches an older one.

    Consuming the newest record makes it invisible to
    ``latest_live_launch_record``; a second dispatch call naturally falls
    through to whatever live record remains, exactly as a second keypress
    would after the first one already initiated a kill.
    """
    app = _DispatchApp()
    older = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("older")
    )
    newer = push_launch_record(
        app, proc_ids=("p2",), prompt="p", context=_context("newer")
    )
    assert older is not None and newer is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))

    older_agent = _FakeAgent("older-agent")
    newer_agent = _FakeAgent("newer-agent")
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [newer_agent] if rec is newer else [older_agent],
    )

    app._kill_and_edit_last_launch()
    assert app.single_targets == [newer_agent]

    app._kill_and_edit_last_launch()
    assert app.single_targets == [newer_agent, older_agent]


# --- resolved single-result: same confirmation rule as ,x ------------------


class _SingleResultApp(KillAndEditLastLaunchMixin, EntryRelaunchMixin):
    """Exercises the real ``_kill_and_edit_agent`` delegation, unstubbed."""

    def __init__(
        self,
        agent: _FakeAgent,
        *,
        kill_result: bool = True,
        dismiss_result: bool = True,
    ) -> None:
        self._agents_with_children = [agent]
        self._agents = [agent]
        self.kill_result = kill_result
        self.dismiss_result = dismiss_result
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.notifications: list[tuple[str, str | None]] = []
        self.killed: list[Any] = []
        self.dismissed: list[Any] = []
        self.launched: tuple[str, str, str, bool] | None = None

    def notify(self, message: str, *, severity: str | None = None) -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_kill_agent(
        self, agent: Any, *, on_settled: Callable[[], None] | None = None
    ) -> bool:
        self.killed.append(agent)
        if self.kill_result and on_settled is not None:
            on_settled()
        return self.kill_result

    def _dismiss_done_agent(
        self, agent: Any, *, on_settled: Callable[[], None] | None = None
    ) -> bool:
        self.dismissed.append(agent)
        if self.dismiss_result and on_settled is not None:
            on_settled()
        return self.dismiss_result

    def _edit_and_relaunch_agent(
        self,
        raw_prompt: str,
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.launched = (raw_prompt, project_file, cl_name, is_project_agent)


def test_single_result_dismissable_row_skips_confirmation_like_plain_x(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("done-agent", status="DONE", pid=None)
    app = _SingleResultApp(agent)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("done-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    app._kill_and_edit_last_launch()

    assert app.dismissed == [agent]
    assert app.killed == []
    assert app.pushed_modals == []
    assert app.launched == ("Do work", agent.project_file, agent.cl_name, False)
    assert record.state is LaunchRecordState.CONSUMED


def test_single_result_live_pid_row_asks_for_confirmation_like_plain_x(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("running-agent", status="RUNNING", pid=111)
    app = _SingleResultApp(agent)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("running-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    app._kill_and_edit_last_launch()

    assert len(app.pushed_modals) == 1
    assert isinstance(app.pushed_modals[0], ConfirmKillModal)
    assert app.killed == []
    assert record.state is LaunchRecordState.RESOLVED_ACTION_PENDING

    app.pushed_callbacks[-1](True)

    assert app.killed == [agent]
    assert app.launched == ("Do work", agent.project_file, agent.cl_name, False)
    assert record.state is LaunchRecordState.CONSUMED


def test_single_result_confirmation_cancel_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("running-agent", status="RUNNING", pid=111)
    app = _SingleResultApp(agent)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("running-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    app._kill_and_edit_last_launch()
    app._kill_and_edit_last_launch()

    assert len(app.pushed_modals) == 1
    assert record.state is LaunchRecordState.RESOLVED_ACTION_PENDING

    app.pushed_callbacks[-1](False)

    assert app.killed == []
    assert app.launched is None
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record

    app._kill_and_edit_last_launch()

    assert len(app.pushed_modals) == 2
    assert latest_live_launch_record(app) is record


def test_single_result_initiation_refusal_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("running-agent", status="RUNNING", pid=111)
    app = _SingleResultApp(agent, kill_result=False)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("running-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    app._kill_and_edit_last_launch()
    app.pushed_callbacks[-1](True)

    assert app.killed == [agent]
    assert app.launched is None
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record


def test_single_result_prompt_resolution_failure_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    agent = _FakeAgent("running-agent", status="RUNNING", pid=111)
    app = _SingleResultApp(agent)
    record = push_launch_record(
        app, proc_ids=("p1",), prompt="p", context=_context("running-agent")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [agent],
    )

    def fail_prompt_resolution(*_args: object, **_kwargs: object) -> str:
        raise RuntimeError("prompt disk read failed")

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._entry_relaunch."
        "prepare_kill_edit_agent_prompt",
        fail_prompt_resolution,
    )

    app._kill_and_edit_last_launch()

    assert app.pushed_modals == []
    assert app.killed == []
    assert app.launched is None
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record
    assert app.notifications == [
        (
            "Unable to prepare agent relaunch prompt: prompt disk read failed",
            "error",
        )
    ]


class _DeferredPromptApp(_SingleResultApp):
    """Keeps scheduled prompt-resolution workers pending for repeat-key tests."""

    def __init__(self, agent: _FakeAgent) -> None:
        super().__init__(agent)
        self.workers: list[tuple[Any, dict[str, Any]]] = []

    def run_worker(self, worker: Any, **kwargs: Any) -> None:
        self.workers.append((worker, dict(kwargs)))
        worker.close()


def test_repeat_press_while_prompt_resolution_pending_does_not_advance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    newer_agent = _FakeAgent("newer-agent", status="RUNNING", pid=111)
    older_agent = _FakeAgent("older-agent", status="RUNNING", pid=222)
    app = _DeferredPromptApp(newer_agent)
    older = push_launch_record(
        app, proc_ids=("older",), prompt="older", context=_context("older")
    )
    newer = push_launch_record(
        app, proc_ids=("newer",), prompt="newer", context=_context("newer")
    )
    assert older is not None and newer is not None
    stamp_launch_record_results(app, "older", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "newer", (_matchable_result("proj", "2"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [newer_agent] if rec is newer else [older_agent],
    )

    app._kill_and_edit_last_launch()
    app._kill_and_edit_last_launch()

    assert len(app.workers) == 1
    assert newer.state is LaunchRecordState.RESOLVED_ACTION_PENDING
    assert older.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is newer
    assert app.pushed_modals == []
    assert app.killed == []


# --- resolved multi-result: bulk kill-and-edit composition ------------------


class _BulkSetApp(AgentMarkingMixin, KillAndEditLastLaunchMixin):
    """Exercises ``_kill_and_edit_last_launch_set`` with the real bulk modal."""

    def __init__(self, agents: list[_FakeAgent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._marked_agents: set[Any] = set()
        self._marked_agent_order: list[Any] = []
        self.notifications: list[tuple[str, str]] = []
        self.pushed_modals: list[Any] = []
        self.pushed_callbacks: list[Any] = []
        self.bulk_kill_calls: list[tuple[list[Any], list[Any]]] = []
        self.edit_calls: list[dict[str, Any]] = []
        self.bulk_kill_result = True

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.pushed_callbacks.append(callback)

    def _do_bulk_kill_agents(
        self,
        killable: list[Any],
        dismissable: list[Any] | None = None,
        *,
        on_settled: Callable[[], None] | None = None,
    ) -> bool:
        dismissable = dismissable or []
        self.bulk_kill_calls.append((list(killable), list(dismissable)))
        if not self.bulk_kill_result:
            return False
        ids = {a.identity for a in killable} | {a.identity for a in dismissable}
        self._agents = [a for a in self._agents if a.identity not in ids]
        self._agents_with_children = [
            a for a in self._agents_with_children if a.identity not in ids
        ]
        if on_settled is not None:
            on_settled()
        return True

    def _edit_and_relaunch_agents_bulk(
        self,
        prompts: list[str],
        project_file: str,
        cl_name: str,
        is_project_agent: bool,
    ) -> None:
        self.edit_calls.append(
            {
                "prompts": list(prompts),
                "project_file": project_file,
                "cl_name": cl_name,
                "is_project_agent": is_project_agent,
            }
        )


def test_multi_result_set_yields_n_kills_and_n_panes_in_order() -> None:
    running = _FakeAgent(
        "run", raw_prompt="%i:run\nWork run", status="RUNNING", pid=111
    )
    done = _FakeAgent("done", raw_prompt="%id:done\nWork done", status="DONE")
    app = _BulkSetApp([running, done])

    # Launch order is done, then running -- distinct from row order.
    app._kill_and_edit_last_launch_set([done, running])

    assert app.pushed_modals, "Expected the bulk confirmation modal"
    app.pushed_callbacks[-1](True)

    assert len(app.bulk_kill_calls) == 1
    killable, dismissable = app.bulk_kill_calls[0]
    assert [a.name for a in killable] == ["run"]
    assert [a.name for a in dismissable] == ["done"]

    assert len(app.edit_calls) == 1
    assert app.edit_calls[0]["prompts"] == [
        "%id:!done\nWork done",
        "%id:!run\nWork run",
    ]


def test_resolved_bulk_confirmation_cancel_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _FakeAgent(
        "run", raw_prompt="%i:run\nWork run", status="RUNNING", pid=111
    )
    done = _FakeAgent("done", raw_prompt="%id:done\nWork done", status="DONE")
    app = _BulkSetApp([running, done])
    record = push_launch_record(
        app, proc_ids=("p1", "p2"), prompt="p", context=_context("bulk")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [done, running],
    )

    app._kill_and_edit_last_launch()
    app._kill_and_edit_last_launch()

    assert len(app.pushed_modals) == 1
    assert record.state is LaunchRecordState.RESOLVED_ACTION_PENDING

    app.pushed_callbacks[-1](False)

    assert app.bulk_kill_calls == []
    assert app.edit_calls == []
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record


def test_resolved_bulk_initiation_refusal_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _FakeAgent(
        "run", raw_prompt="%i:run\nWork run", status="RUNNING", pid=111
    )
    done = _FakeAgent("done", raw_prompt="%id:done\nWork done", status="DONE")
    app = _BulkSetApp([running, done])
    app.bulk_kill_result = False
    record = push_launch_record(
        app, proc_ids=("p1", "p2"), prompt="p", context=_context("bulk")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [done, running],
    )

    app._kill_and_edit_last_launch()
    app.pushed_callbacks[-1](True)

    assert len(app.bulk_kill_calls) == 1
    assert app.edit_calls == []
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record


def test_resolved_bulk_identity_loss_leaves_record_targetable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    running = _FakeAgent(
        "run", raw_prompt="%i:run\nWork run", status="RUNNING", pid=111
    )
    done = _FakeAgent("done", raw_prompt="%id:done\nWork done", status="DONE")
    app = _BulkSetApp([running, done])
    record = push_launch_record(
        app, proc_ids=("p1", "p2"), prompt="p", context=_context("bulk")
    )
    assert record is not None
    stamp_launch_record_results(app, "p1", (_matchable_result("proj", "1"),))
    stamp_launch_record_results(app, "p2", (_matchable_result("proj", "2"),))
    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "_matched_agents_for_record",
        lambda rec, loaded: [done, running],
    )

    def resolve_then_lose_rows(
        _owner: object,
        resolver: Callable[[], list[str | None]],
        on_complete: Callable[[list[str | None]], None],
        **_kwargs: object,
    ) -> None:
        resolved = resolver()
        app._agents = []
        app._agents_with_children = []
        on_complete(resolved)

    monkeypatch.setattr(
        "sase.ace.tui.actions.agent_workflow._kill_last_launch."
        "schedule_relaunch_prompt_resolution",
        resolve_then_lose_rows,
    )

    app._kill_and_edit_last_launch()

    assert app.pushed_modals == []
    assert app.bulk_kill_calls == []
    assert app.edit_calls == []
    assert record.state is LaunchRecordState.RESOLVED
    assert latest_live_launch_record(app) is record
    assert app.notifications == [
        ("A launched agent is no longer available; nothing killed", "warning")
    ]
