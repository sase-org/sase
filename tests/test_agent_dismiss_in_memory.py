"""Tests for in-memory dismiss (Fix 1 of fast_dismiss plan).

The dismiss path used to end with a full disk rescan via ``_load_agents``
which took ~11s with many dismissed bundles.  The new flow updates the
cached agent list in-memory and re-runs only the filter pipeline.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._dismissing import AgentDismissingMixin
from sase.ace.tui.models.agent import Agent, AgentType


def _make_agent(**overrides: object) -> Agent:
    """Create a minimal Agent for dismiss tests."""
    defaults: dict[str, object] = {
        "agent_type": AgentType.RUNNING,
        "cl_name": "test_cl",
        "project_file": "/tmp/projects/myproj/myproj.gp",
        "status": "DONE",
        "start_time": datetime(2024, 1, 1, 12, 0, 0),
        "raw_suffix": "20240101120000",
    }
    defaults.update(overrides)
    return Agent(**defaults)  # type: ignore[arg-type]


class FakeDismissApp(AgentDismissingMixin):
    """Minimal app implementing just what the dismiss flow touches."""

    def __init__(self) -> None:
        self.current_tab = "agents"
        self.current_idx = 0
        self.changespecs = []  # type: ignore[assignment]
        self._agents: list[Agent] = []
        self._dismissed_agents: set[tuple[AgentType, str, str | None]] = set()
        self._dismissed_agent_objects: list[Agent] = []
        self._pinned_agents: set[tuple[AgentType, str, str | None]] = set()
        self._agents_with_children: list[Agent] = []
        self._agent_status_overrides: dict[tuple[AgentType, str, str | None], str] = {}
        self._agent_pre_question_status: dict[
            tuple[AgentType, str, str | None], str | None
        ] = {}
        self._dismiss_persistence_inflight: set[tuple[AgentType, str, str | None]] = (
            set()
        )
        self._scheduled: list[tuple[object, tuple[object, ...]]] = []
        self.notifications: list[tuple[str, str]] = []
        self.load_count = 0
        self.refilter_count = 0
        self.notification_refreshes = 0
        self.async_refreshes = 0

    def notify(self, message: str, *, severity: str = "information") -> None:
        self.notifications.append((message, severity))

    def _load_agents(self) -> None:
        self.load_count += 1

    def _refilter_agents(self) -> None:
        self.refilter_count += 1

    def _refresh_notification_count(self) -> None:
        self.notification_refreshes += 1

    def _schedule_agents_async_refresh(self) -> None:
        self.async_refreshes += 1

    def call_later(self, callback: object, *args: object) -> None:
        self._scheduled.append((callback, args))


def test_apply_dismissal_removes_agent_from_cached_list() -> None:
    """Dismissing an agent removes it from _agents_with_children."""
    app = FakeDismissApp()
    target = _make_agent(cl_name="feature_a", raw_suffix="20240101120000")
    other = _make_agent(cl_name="feature_b", raw_suffix="20240101130000")
    app._agents_with_children = [target, other]

    app._apply_dismissal_in_memory([target])

    assert [a.identity for a in app._agents_with_children] == [other.identity]


def test_apply_dismissal_appends_to_dismissed_agent_objects() -> None:
    """Dismissed agent is appended to _dismissed_agent_objects for revive."""
    app = FakeDismissApp()
    target = _make_agent()
    app._agents_with_children = [target]

    app._apply_dismissal_in_memory([target])

    assert target in app._dismissed_agent_objects


def test_apply_dismissal_dedupes_dismissed_agent_objects() -> None:
    """Appending is idempotent on identity."""
    app = FakeDismissApp()
    target = _make_agent()
    app._agents_with_children = [target]
    app._dismissed_agent_objects = [target]

    app._apply_dismissal_in_memory([target])

    assert len(app._dismissed_agent_objects) == 1


def test_apply_dismissal_includes_workflow_children() -> None:
    """Dismissing a workflow parent also dispatches its children."""
    app = FakeDismissApp()
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="20240101120000",
        workflow="wf",
    )
    child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20240101120000",
    )
    unrelated = _make_agent(cl_name="other", raw_suffix="20240101130000")
    app._agents_with_children = [parent, child, unrelated]

    app._apply_dismissal_in_memory([parent])

    remaining = [a.identity for a in app._agents_with_children]
    assert remaining == [unrelated.identity]
    dismissed_ids = {a.identity for a in app._dismissed_agent_objects}
    assert dismissed_ids == {parent.identity, child.identity}


def test_apply_dismissal_calls_refilter_not_load() -> None:
    """The in-memory path triggers _refilter_agents instead of _load_agents."""
    app = FakeDismissApp()
    target = _make_agent()
    app._agents_with_children = [target]

    app._apply_dismissal_in_memory([target])

    assert app.refilter_count == 1
    assert app.load_count == 0


def test_apply_dismissal_batch_removes_all() -> None:
    """Batch dismiss atomically removes all listed identities."""
    app = FakeDismissApp()
    a1 = _make_agent(cl_name="a", raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="b", raw_suffix="20240101130000")
    a3 = _make_agent(cl_name="c", raw_suffix="20240101140000")
    app._agents_with_children = [a1, a2, a3]

    app._apply_dismissal_in_memory([a1, a2])

    assert [a.identity for a in app._agents_with_children] == [a3.identity]
    assert {a.identity for a in app._dismissed_agent_objects} == {
        a1.identity,
        a2.identity,
    }


def test_dismiss_done_agent_is_optimistic_and_schedules_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """_dismiss_done_agent removes the row before persistence callbacks run."""
    app = FakeDismissApp()
    agent = _make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    app._agents_with_children = [agent]
    app._agents = [agent]

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agent"
        ) as mock_dismiss_one,
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch(
            "sase.ace.tui.actions.agents._dismissing.delete_agent_artifacts"
        ) as mock_delete,
        patch("sase.ace.dismissed_agents.save_dismissed_bundle") as mock_bundle,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        app._dismiss_done_agent(agent)

    mock_dismiss_one.assert_not_called()
    mock_dismiss_many.assert_not_called()
    mock_delete.assert_not_called()
    mock_bundle.assert_not_called()
    mock_save.assert_not_called()
    assert app.load_count == 0
    assert app.refilter_count == 1
    assert app.notification_refreshes == 0
    assert agent.identity in app._dismissed_agents
    assert agent in app._dismissed_agent_objects
    assert app._agents_with_children == []
    assert len(app._scheduled) == 1
    callback, args = app._scheduled[0]
    assert callback == app._run_dismiss_persistence_async
    assert args[0] == agent
    assert agent.identity in args[1]
    assert args[2] == [agent]


def test_dismiss_persistence_callback_runs_deferred_work(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The scheduled dismiss callback performs cleanup and refreshes afterward."""
    app = FakeDismissApp()
    agent = _make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    app._agents_with_children = [agent]
    app._agents = [agent]

    app._dismiss_done_agent(agent)

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.persist_dismiss_side_effects"
        ) as mock_persist,
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]

    mock_persist.assert_called_once_with(agent, [agent])
    mock_dismiss_many.assert_called_once_with([agent])
    mock_save.assert_called_once_with({agent.identity})
    assert app.notification_refreshes == 1
    assert app.async_refreshes == 1


def test_dismiss_done_workflow_parent_removes_children(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Dismissing a workflow parent removes both parent and child in memory."""
    app = FakeDismissApp()
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="20240101120000",
        workflow="wf",
        artifacts_dir=str(tmp_path / "parent_artifacts"),
    )
    child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20240101120000",
    )
    app._agents_with_children = [parent, child]
    app._agents = [parent, child]

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agent"
        ) as mock_dismiss_one,
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch(
            "sase.ace.tui.actions.agents._dismissing.delete_agent_artifacts"
        ) as mock_delete,
        patch(
            "sase.ace.tui.actions.agents._dismissing."
            "find_workflow_workspace_from_running_field",
            return_value=None,
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_bundle") as mock_bundle,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        app._dismiss_done_agent(parent)

    mock_dismiss_one.assert_not_called()
    mock_dismiss_many.assert_not_called()
    mock_delete.assert_not_called()
    mock_bundle.assert_not_called()
    mock_save.assert_not_called()
    assert app.load_count == 0
    assert app.refilter_count == 1
    assert parent.identity in app._dismissed_agents
    assert child.identity in app._dismissed_agents
    assert app._agents_with_children == []
    assert len(app._scheduled) == 1
    assert app._scheduled[0][1][2] == [parent, child]


def test_dismiss_workflow_parent_persistence_uses_pre_removal_snapshot(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Workflow child rows removed immediately are still available to persistence."""
    app = FakeDismissApp()
    parent = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="20240101120000",
        workflow="wf",
        artifacts_dir=str(tmp_path / "parent_artifacts"),
    )
    child = _make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20240101120000",
    )
    app._agents_with_children = [parent, child]
    app._agents = [parent, child]

    app._dismiss_done_agent(parent)

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.persist_dismiss_side_effects"
        ) as mock_persist,
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]

    mock_persist.assert_called_once_with(parent, [parent, child])
    mock_dismiss_many.assert_called_once_with([parent, child])
    mock_save.assert_called_once_with({parent.identity, child.identity})
    assert app.notification_refreshes == 1
    assert app.async_refreshes == 1


def test_dismiss_done_changespec_agent_does_not_full_reload() -> None:
    """ChangeSpec-sourced agents (hooks/mentors/CRS) take the in-memory path."""
    app = FakeDismissApp()
    agent = _make_agent(
        raw_suffix="20240101120000",
    )
    agent._from_changespec = True
    app._agents_with_children = [agent]
    app._agents = [agent]

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agent"
        ) as mock_dismiss_one,
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        app._dismiss_done_agent(agent)

    mock_dismiss_one.assert_not_called()
    mock_dismiss_many.assert_not_called()
    mock_save.assert_not_called()
    assert app.load_count == 0
    assert app.refilter_count == 1
    assert agent.identity in app._dismissed_agents
    assert len(app._scheduled) == 1


def test_do_dismiss_all_batch_does_not_full_reload() -> None:
    """Batch dismiss uses the in-memory path, not _load_agents."""
    app = FakeDismissApp()
    a1 = _make_agent(cl_name="a", raw_suffix="20240101120000")
    a2 = _make_agent(cl_name="b", raw_suffix="20240101130000")
    app._agents_with_children = [a1, a2]
    app._agents = [a1, a2]

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agent"
        ),
        patch("sase.ace.tui.actions.agents._dismissing.delete_agent_artifacts"),
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
    ):
        app._do_dismiss_all([a1, a2])

    assert app.load_count == 0
    assert app.refilter_count == 1
    assert a1.identity in app._dismissed_agents
    assert a2.identity in app._dismissed_agents
    assert app._agents_with_children == []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
