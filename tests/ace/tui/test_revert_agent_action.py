"""Tests for the Agents-tab revert action gate and task submission."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.ace.revert_agent import RevertCommit, RevertPreview
from sase.ace.tui.actions.agents._revert import AgentRevertMixin
from sase.ace.tui.models.agent import Agent, AgentType


class _FakeApp(AgentRevertMixin):
    def __init__(self, agent: Agent | None, current_tab: str = "agents") -> None:
        self.current_tab = current_tab
        self._selected = agent
        self.notifications: list[tuple[str, str]] = []
        self.submitted: list[dict[str, Any]] = []
        self.pushed_modals: list[Any] = []
        self.modal_callbacks: list[Any] = []
        self.refresh_sources: list[str] = []

    def _get_selected_agent(self) -> Agent | None:
        return self._selected

    def notify(self, message: str, severity: str = "information", **_: Any) -> None:
        self.notifications.append((message, severity))

    def _submit_tracked_task(self, task_type: str, *args: Any, **kwargs: Any) -> object:
        self.submitted.append({"task_type": task_type, "kwargs": kwargs})
        return object()

    def push_screen(self, modal: Any, callback: Any = None) -> None:
        self.pushed_modals.append(modal)
        self.modal_callbacks.append(callback)

    def _schedule_agents_async_refresh(self, *, source: str = "unknown") -> None:
        self.refresh_sources.append(source)


def _agent(status: str, *, name: str | None = "foo", ws: str | None = None) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="cl",
        project_file="/proj/cl/spec",
        status=status,
        start_time=None,
        agent_name=name,
        workspace_num=0,
        workspace_dir=ws,
    )


def test_noop_on_non_agents_tab() -> None:
    app = _FakeApp(_agent("DONE"), current_tab="changespecs")
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert app.notifications == []


def test_notifies_when_no_agent_selected() -> None:
    app = _FakeApp(None)
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert app.notifications == [("No agent selected", "warning")]


def test_rejects_running_agent() -> None:
    app = _FakeApp(_agent("RUNNING"))
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert app.notifications[-1][1] == "warning"
    assert "done or failed" in app.notifications[-1][0]


def test_warns_when_no_agent_name(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name=None, ws=str(tmp_path)))
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert "agent name" in app.notifications[-1][0]


def test_warns_when_no_workspace() -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=None))
    app._start_revert_selected_agent()
    assert app.submitted == []
    assert "workspace" in app.notifications[-1][0].lower()


def test_submits_preview_task_for_done_agent(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=str(tmp_path)))
    app._start_revert_selected_agent()

    assert len(app.submitted) == 1
    submitted = app.submitted[0]
    assert submitted["task_type"] == "revert_preview"
    assert "foo" in submitted["kwargs"]["dedup_key"]
    assert submitted["kwargs"]["reload_on_complete"] is False


def test_failed_retried_agent_is_revertable(tmp_path: Path) -> None:
    app = _FakeApp(_agent("FAILED (RETRIED)", name="foo", ws=str(tmp_path)))
    app._start_revert_selected_agent()
    assert len(app.submitted) == 1
    assert app.submitted[0]["task_type"] == "revert_preview"


def test_confirm_modal_submits_revert_and_callback_refreshes(tmp_path: Path) -> None:
    app = _FakeApp(_agent("DONE", name="foo", ws=str(tmp_path)))
    preview = RevertPreview(
        agent_name="foo",
        scope="agent",
        workspace_dir=str(tmp_path),
        commits=(
            RevertCommit(sha="abc", full_sha="abc123", subject="s", agent_tag="foo"),
        ),
    )

    app._open_confirm_revert_modal(preview, app._selected, None)
    assert len(app.pushed_modals) == 1

    # Decline -> nothing submitted.
    app.modal_callbacks[0](False)
    assert app.submitted == []

    # Confirm -> a revert task is submitted.
    app.modal_callbacks[0](True)
    assert len(app.submitted) == 1
    assert app.submitted[0]["task_type"] == "revert_agent"

    # Simulate task completion success -> Agents tab refresh scheduled.
    on_complete = app.submitted[0]["kwargs"]["on_complete"]

    class _Completion:
        success = True

    on_complete(_Completion())
    assert app.refresh_sources == ["revert_agent"]
