"""Tests for Agents-tab wait/fork actions."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.base import BaseActionsMixin
from sase.ace.tui.actions.agents._wait_resume import (
    AgentWaitResumeMixin,
    _prompt_wait_spec,
    _wait_modal_candidates,
)
from sase.ace.tui.actions.task_actions import TrackedTaskCompletion, TrackedTaskResult
from sase.ace.tui.actions.hints._hooks import HookEditingMixin
from sase.ace.tui.modals import WaitModalResult
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.task_queue import TaskInfo
from sase.xprompt.directive_edit import PromptWaitDirective, set_prompt_wait


def _make_waiting_agent(**overrides: object) -> Agent:
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.sase",
        "status": "WAITING",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
        "waiting_for": ["old_dep"],
        "wait_duration": 300.0,
        "wait_until": "2026-05-01T12:00:00",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class _FakeWaitResumeApp(AgentWaitResumeMixin):
    """Minimal app implementing what _apply_wait touches."""

    def __init__(self) -> None:
        self.notifications: list[tuple[str, str]] = []
        self.refresh_calls = 0
        self.pushed_screens: list[tuple[object, object]] = []
        self.killed_agents: list[Agent] = []
        self.launch_prompts: list[str] = []
        self.prompt_contexts: list[dict[str, str | None]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _refresh_agents_display(
        self, *, list_changed: bool = False, defer_detail: bool = False
    ) -> None:
        del list_changed, defer_detail
        self.refresh_calls += 1

    def push_screen(self, screen: object, callback: object = None) -> None:
        self.pushed_screens.append((screen, callback))

    def _submit_tracked_task(
        self,
        task_type: str,
        cl_name: str,
        project_file: str,
        task_callable: Any,
        *,
        display_name: str | None = None,
        dedup_key: str | None = None,
        duplicate_message: str | None = None,
        on_complete: Any = None,
        reload_on_complete: bool = True,
        notify_on_complete: bool = True,
    ) -> TaskInfo:
        del duplicate_message, reload_on_complete, notify_on_complete
        task_info = TaskInfo(
            task_id="task-0",
            task_type=task_type,
            cl_name=cl_name,
            project_file=project_file,
            status="running",
            message="running",
            started_at=datetime.now(),
            display_name=display_name,
            dedup_key=dedup_key,
        )
        try:
            result = task_callable()
        except Exception as exc:
            result = TrackedTaskResult(
                success=False,
                message=str(exc),
                error=str(exc),
            )
        task_info.status = "success" if result.success else "error"
        task_info.message = result.message
        task_info.error = result.error
        if on_complete is not None:
            on_complete(
                TrackedTaskCompletion(
                    task_info=task_info,
                    success=result.success,
                    message=result.message,
                    output="",
                    payload=result.payload,
                    error=result.error,
                )
            )
        return task_info

    def _do_kill_agent(self, agent: Agent) -> None:
        self.killed_agents.append(agent)

    def _setup_home_prompt_context(
        self,
        *,
        display_name: str | None,
        history_sort_key: str | None,
    ) -> None:
        self.prompt_contexts.append(
            {
                "display_name": display_name,
                "history_sort_key": history_sort_key,
            }
        )

    def _finish_agent_launch(self, prompt: str) -> None:
        self.launch_prompts.append(prompt)


class _FakeResumeActionApp(AgentWaitResumeMixin):
    """Minimal app implementing what action_fork_agent touches."""

    def __init__(self, agents: list[Agent]) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self._agents = list(agents)
        self._agents_with_children = list(agents)
        self._marked_agents: set[tuple[AgentType, str, str | None]] = set()
        self.notifications: list[tuple[str, str]] = []
        self.prompt_bar_calls: list[dict[str, str | None]] = []

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _get_selected_agent(self) -> Agent | None:
        if 0 <= self.current_idx < len(self._agents):
            return self._agents[self.current_idx]
        return None

    def _show_prompt_input_bar_for_home(
        self,
        *,
        initial_text: str = "",
        display_name: str | None = None,
        history_sort_key: str | None = None,
    ) -> None:
        self.prompt_bar_calls.append(
            {
                "initial_text": initial_text,
                "display_name": display_name,
                "history_sort_key": history_sort_key,
            }
        )


def test_apply_wait_overwrites_wait_conditions(tmp_path: Path) -> None:
    waiting_path = tmp_path / "waiting.json"
    waiting_path.write_text(
        json.dumps(
            {
                "waiting_for": ["old_dep"],
                "wait_duration": 300.0,
                "wait_until": "2026-05-01T12:00:00",
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
            }
        ),
        encoding="utf-8",
    )
    agent = _make_waiting_agent()
    app = _FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=["alice", "bob"], time_token=None),
        )

    data = json.loads(waiting_path.read_text(encoding="utf-8"))
    assert data == {
        "cl_name": "test_cl",
        "timestamp": "20240101120000",
        "waiting_for": ["alice", "bob"],
    }
    assert agent.waiting_for == ["alice", "bob"]
    assert agent.wait_duration is None
    assert agent.wait_until is None
    assert app.notifications == [("Now waiting for: alice, bob", "information")]
    assert app.refresh_calls == 1
    assert update_index.call_count == 2
    update_index.assert_any_call(str(tmp_path))


def test_apply_wait_empty_submission_keeps_run_now_behavior(tmp_path: Path) -> None:
    agent = _make_waiting_agent(waiting_for=["old_dep"], wait_duration=None)
    app = _FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ) as update_index:
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, run_now=True),
        )

    ready_path = tmp_path / "ready.json"
    assert json.loads(ready_path.read_text(encoding="utf-8")) == {
        "resolved_deps": ["old_dep"],
        "unwait": True,
    }
    assert agent.waiting_for == []
    assert app.notifications == [("Wait: test_cl", "information")]
    update_index.assert_not_called()


def test_apply_wait_updates_parked_runner_threshold_in_place(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text("Do work", encoding="utf-8")
    (tmp_path / "agent_meta.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": [],
                "cl_name": "test_cl",
                "timestamp": "20240101120000",
                "wait_runners": 9,
                "wait_runners_explicit": False,
                "slot_requested_at": "2026-07-12T12:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    agent = _make_waiting_agent(
        artifacts_dir=str(tmp_path),
        waiting_for=[],
        wait_duration=None,
        wait_until=None,
        wait_runners=9,
        wait_runners_explicit=False,
        slot_requested_at="2026-07-12T12:00:00Z",
    )
    app = _FakeWaitResumeApp()

    with patch(
        "sase.ace.tui.actions.agents._directive_persistence."
        "update_agent_artifact_index_for_marker_mutation"
    ):
        app._apply_wait(
            str(tmp_path),
            agent,
            WaitModalResult(agents=[], time_token=None, runners=0),
        )

    waiting = json.loads((tmp_path / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["wait_runners"] == 0
    assert waiting["wait_runners_explicit"] is True
    assert waiting["slot_requested_at"] == "2026-07-12T12:00:00Z"
    assert (tmp_path / "raw_xprompt.md").read_text(encoding="utf-8") == (
        "%wait(runners=0)\nDo work"
    )
    assert json.loads((tmp_path / "agent_meta.json").read_text())["wait_runners"] == 0
    assert agent.wait_runners == 0
    assert agent.wait_runners_explicit is True
    assert app.killed_agents == []


def test_prompt_wait_spec_builds_canonical_forms() -> None:
    assert _prompt_wait_spec(
        WaitModalResult(agents=["alice", "bob"], time_token="5m")
    ) == PromptWaitDirective(agents=("alice", "bob"), time_token="5m")
    assert (
        set_prompt_wait(
            "Do work",
            _prompt_wait_spec(WaitModalResult(agents=[], time_token="5m")),
        )
        == "%wait(time=5m)\nDo work"
    )
    assert (
        set_prompt_wait(
            "Do work",
            _prompt_wait_spec(WaitModalResult(agents=["alice"], time_token=None)),
        )
        == "%wait(alice)\nDo work"
    )


def test_wait_modal_candidates_excludes_self_unnamed_and_duplicates() -> None:
    selected = _make_waiting_agent(
        cl_name="selected",
        raw_suffix="20240101120000",
        agent_name="selected",
    )
    planner = _make_waiting_agent(
        cl_name="planner",
        raw_suffix="20240101120100",
        agent_name="planner",
        llm_provider="claude",
        model="sonnet",
        reasoning_effort="xhigh",
    )
    duplicate = _make_waiting_agent(
        cl_name="planner-2",
        raw_suffix="20240101120200",
        agent_name="planner",
    )
    unnamed = _make_waiting_agent(
        cl_name="unnamed",
        raw_suffix="20240101120300",
        agent_name=None,
    )

    candidates = _wait_modal_candidates(
        selected,
        [selected, planner, duplicate, unnamed],
    )

    assert [candidate.wait_name for candidate in candidates] == ["planner"]
    assert candidates[0].model == "claude / sonnet@xhigh"


def test_strip_existing_wait_directives_removes_wait_and_time_refs() -> None:
    raw_prompt = "%w:old #t:5m %time:1430 do the thing"

    assert set_prompt_wait(raw_prompt, None) == "do the thing"


def test_apply_wait_with_time_relaunches_with_replacement_directive(
    tmp_path: Path,
) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%w:old #t:5m do the thing",
        encoding="utf-8",
    )
    agent = _make_waiting_agent(
        artifacts_dir=str(tmp_path),
        wait_duration=300.0,
        waiting_for=["old"],
    )
    app = _FakeWaitResumeApp()

    app._apply_wait(
        str(tmp_path),
        agent,
        WaitModalResult(agents=["new"], time_token="10m"),
    )

    assert len(app.pushed_screens) == 1
    modal, callback = app.pushed_screens[0]
    assert "waiting for new, then 10m" in modal.agent_description  # type: ignore[attr-defined]
    assert callable(callback)
    callback(True)

    assert app.killed_agents == [agent]
    assert app.launch_prompts == ["%wait(new, time=10m)\ndo the thing"]
    assert "%w:old" not in app.launch_prompts[0]
    assert "#t:5m" not in app.launch_prompts[0]


def test_apply_wait_running_relaunches_with_canonical_wait(tmp_path: Path) -> None:
    (tmp_path / "raw_xprompt.md").write_text(
        "%name:kept do the thing", encoding="utf-8"
    )
    agent = _make_waiting_agent(
        status="RUNNING",
        artifacts_dir=str(tmp_path),
        agent_name="runner",
    )
    app = _FakeWaitResumeApp()

    app._apply_wait_running(agent, WaitModalResult(agents=["dep"], time_token=None))

    assert len(app.pushed_screens) == 1
    _modal, callback = app.pushed_screens[0]
    assert callable(callback)
    callback(True)

    assert app.killed_agents == [agent]
    assert app.launch_prompts == ["%wait(dep)\n%name:kept do the thing"]


def test_apply_wait_running_run_now_is_noop() -> None:
    agent = _make_waiting_agent(status="RUNNING")
    app = _FakeWaitResumeApp()

    app._apply_wait_running(
        agent,
        WaitModalResult(agents=[], time_token=None, run_now=True),
    )

    assert app.notifications == [("Agent is already running", "warning")]
    assert app.pushed_screens == []


class _FakeAgentForkDispatchApp(BaseActionsMixin, HookEditingMixin):
    """Minimal app for Agents-tab key dispatch assertions."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.changespecs = [object()]
        self.fork_calls = 0
        self.retry_edit_calls = 0

    def action_fork_agent(self) -> None:
        self.fork_calls += 1

    def _retry_edit_agent(self) -> None:
        self.retry_edit_calls += 1


def test_fork_agent_tale_done_family_root_uses_family_name() -> None:
    agent = _make_waiting_agent(
        status="TALE DONE",
        agent_name="aww-plan",
        agent_family="aww",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = _FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls == [
        {
            "initial_text": "#fork:aww ",
            "display_name": "fork(aww)",
            "history_sort_key": "test_cl",
        }
    ]


def test_fork_agent_plan_done_family_root_uses_family_name() -> None:
    agent = _make_waiting_agent(
        status="PLAN DONE",
        agent_name="planner-plan",
        agent_family="planner",
        agent_family_role="root",
        plan_chain_root=True,
    )
    app = _FakeResumeActionApp([agent])

    app.action_fork_agent()

    assert app.notifications == []
    assert app.prompt_bar_calls[0]["initial_text"] == "#fork:planner "


def test_run_workflow_on_agents_dispatches_retry_edit_and_does_not_fork() -> None:
    app = _FakeAgentForkDispatchApp()

    BaseActionsMixin.action_run_workflow(app)

    assert app.retry_edit_calls == 1
    assert app.fork_calls == 0


def test_edit_hooks_on_agents_dispatches_to_fork() -> None:
    app = _FakeAgentForkDispatchApp()

    HookEditingMixin.action_edit_hooks(app)

    assert app.fork_calls == 1
