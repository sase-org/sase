"""Tests for deferred dismiss persistence and cleanup transactions."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType

from tests._agent_dismiss_helpers import FakeDismissApp, make_agent


def test_dismiss_persistence_callback_runs_deferred_work(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The scheduled dismiss callback performs cleanup and refreshes afterward."""
    app = FakeDismissApp()
    agent = make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    app._agents_with_children = [agent]
    app._agents = [agent]

    app._dismiss_done_agent(agent)

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.persist_cleanup_side_effect_intents",
            return_value=True,
        ) as mock_persist_intents,
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]

    mock_persist_intents.assert_called_once()
    assert mock_persist_intents.call_args[0][1] == [agent]
    mock_dismiss_many.assert_not_called()
    mock_save.assert_called_once_with({agent.identity})
    assert app.notification_refreshes_async == 1
    assert app.notification_refreshes == 0
    assert app.async_refreshes == 0


def test_dismiss_persistence_callback_reloads_on_failure(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """If the persistence worker raises, the finally schedules a reload."""
    app = FakeDismissApp()
    agent = make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    app._agents_with_children = [agent]
    app._agents = [agent]

    app._dismiss_done_agent(agent)

    with patch(
        "sase.ace.tui.actions.agents._dismissing._persist_single_dismiss_transaction",
        side_effect=RuntimeError("boom"),
    ):
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]

    assert app.notification_refreshes == 1
    assert app.notification_refreshes_async == 0
    assert app.async_refreshes == 1
    assert any(sev == "error" for _, sev in app.notifications)


def test_dismiss_workflow_parent_persistence_uses_pre_removal_snapshot(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Workflow child rows removed immediately are still available to persistence."""
    app = FakeDismissApp()
    parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="20240101120000",
        workflow="wf",
        artifacts_dir=str(tmp_path / "parent_artifacts"),
    )
    child = make_agent(
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
            "sase.ace.tui.actions.agents._dismissing.persist_cleanup_side_effect_intents",
            return_value=True,
        ) as mock_persist_intents,
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]

    mock_persist_intents.assert_called_once()
    assert mock_persist_intents.call_args[0][1] == [parent, child]
    mock_dismiss_many.assert_not_called()
    mock_save.assert_called_once_with({parent.identity, child.identity})
    assert app.notification_refreshes_async == 1
    assert app.notification_refreshes == 0
    assert app.async_refreshes == 0


def test_do_dismiss_all_persistence_callback_runs_deferred_work() -> None:
    """Scheduled bulk dismiss callback persists via worker thread."""
    app = FakeDismissApp()
    a1 = make_agent(cl_name="a", raw_suffix="20240101120000")
    a2 = make_agent(cl_name="b", raw_suffix="20240101130000")
    app._agents_with_children = [a1, a2]
    app._agents = [a1, a2]

    app._do_dismiss_all([a1, a2])

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.persist_cleanup_side_effect_intents",
            return_value=True,
        ) as mock_persist_intents,
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]

    mock_persist_intents.assert_called_once()
    assert mock_persist_intents.call_args[0][1] == [a1, a2]
    mock_dismiss_many.assert_not_called()
    mock_save.assert_called_once()
    assert mock_save.call_args[0][0] == {a1.identity, a2.identity}
    assert app.notification_refreshes_async == 1
    assert app.notification_refreshes == 0


def test_do_dismiss_all_persistence_failure_notifies_and_refreshes() -> None:
    """Worker failure surfaces a toast and triggers an async refresh."""
    app = FakeDismissApp()
    a1 = make_agent(cl_name="a", raw_suffix="20240101120000")
    app._agents_with_children = [a1]
    app._agents = [a1]

    app._do_dismiss_all([a1])

    with patch(
        "sase.ace.tui.actions.agents._dismissing._persist_bulk_dismiss_transaction",
        side_effect=RuntimeError("boom"),
    ):
        callback, args = app._scheduled[0]
        asyncio.run(callback(*args))  # type: ignore[misc]

    assert app.async_refreshes == 1
    assert app.notification_refreshes_async == 0
    assert any(sev == "error" for _, sev in app.notifications)
