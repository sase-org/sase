"""Tests for deferred dismiss persistence and cleanup transactions."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import call, patch

from sase.ace.tui.models.agent import AgentType
from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.running_field import ClaimResult, WorkspaceClaim

from tests._agent_cleanup_proc_helpers import run_tracked_proc
from tests._agent_dismiss_helpers import FakeDismissApp, make_agent


def test_release_held_workspace_claims_matches_timestamp_cl_and_dead_pid() -> None:
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        _release_held_workspace_claims,
    )

    project_file = "/tmp/projects/proj/proj.sase"
    claims = [
        WorkspaceClaim(
            17,
            "run",
            "feature",
            1001,
            artifacts_timestamp="20260712120000",
            pinned=True,
        ),
        WorkspaceClaim(
            18,
            "run",
            "feature",
            1002,
            artifacts_timestamp="20260712120000",
            pinned=True,
        ),
        WorkspaceClaim(
            19,
            "run",
            "other",
            1003,
            artifacts_timestamp="20260712120000",
            pinned=True,
        ),
        WorkspaceClaim(
            20,
            "run",
            "feature",
            1004,
            artifacts_timestamp="20260712120100",
            pinned=False,
        ),
    ]
    with (
        patch(
            "sase.running_field.get_claimed_workspaces",
            return_value=claims,
        ),
        patch(
            "sase.ace.hooks.processes.is_process_running",
            side_effect=lambda pid: pid == 1002,
        ),
        patch(
            "sase.running_field.release_workspace",
            return_value=ClaimResult(success=True),
        ) as release,
    ):
        released = _release_held_workspace_claims(
            project_file,
            "20260712120000",
            "feature",
        )

    assert released == 1
    assert release.call_args_list == [call(project_file, 17, "run", "feature")]


def test_dismiss_fallback_releases_hold_before_deleting_artifacts(tmp_path) -> None:
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        persist_dismiss_side_effects,
    )

    artifacts_dir = str(tmp_path / "artifacts")
    agent = make_agent(
        cl_name="feature",
        raw_suffix="20260712120000",
        artifacts_dir=artifacts_dir,
    )
    events: list[str] = []
    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "_release_held_workspace_claims",
            side_effect=lambda *_args: events.append("release") or 1,
        ) as release_hold,
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "delete_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence.delete_agent_artifacts",
            side_effect=lambda *_args, **_kwargs: events.append("delete"),
        ),
    ):
        persist_dismiss_side_effects(agent, [agent])

    release_hold.assert_called_once_with(
        agent.project_file,
        "20260712120000",
        "feature",
    )
    assert events == ["release", "delete"]


def test_cleanup_timestamp_intent_releases_hold() -> None:
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        persist_cleanup_side_effect_intents,
    )

    agent = make_agent(cl_name="feature", raw_suffix="20260712120000")
    identity = AgentCleanupIdentityWire(
        agent_type="run",
        cl_name="feature",
        raw_suffix="20260712120000",
    )
    intent = SimpleNamespace(
        identity=identity,
        project_file=agent.project_file,
        workspace=None,
        workflow=agent.workflow,
        cl_name=agent.cl_name,
        lookup_workflow=False,
        lookup_timestamp=True,
        artifacts_timestamp="20260712120000",
    )
    side_effects = SimpleNamespace(
        bundle_save_candidates=(),
        artifact_delete_paths=(),
        workspace_release_requests=(intent,),
        notification_dismiss_candidates=(),
    )
    cleanup_plan = SimpleNamespace(side_effects=side_effects)

    with patch(
        "sase.ace.tui.actions.agents._dismiss_persistence."
        "_release_held_workspace_claims",
        return_value=1,
    ) as release_hold:
        assert persist_cleanup_side_effect_intents(cleanup_plan, [agent]) is True

    release_hold.assert_called_once_with(
        agent.project_file,
        "20260712120000",
        "feature",
    )


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
        patch(
            "sase.ace.tui.actions.agents._dismissing."
            "sync_dismissed_agent_artifact_index"
        ) as mock_sync_index,
        patch(
            "sase.ace.dismissed_agents.record_recent_dismissed_agent_group"
        ) as mock_record_recent,
    ):
        run_tracked_proc(app, app.tracked_procs[0])

    mock_persist_intents.assert_called_once()
    assert mock_persist_intents.call_args[0][1] == [agent]
    mock_dismiss_many.assert_not_called()
    mock_record_recent.assert_called_once()
    assert mock_record_recent.call_args.args[0].source == "recent_dismissal"
    mock_save.assert_called_once_with({agent.identity})
    mock_sync_index.assert_called_once_with({agent.identity}, added={agent.identity})
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
        "sase.ace.tui.actions.agents._dismissing.persist_single_dismiss_transaction",
        side_effect=RuntimeError("boom"),
    ):
        run_tracked_proc(app, app.tracked_procs[0])

    # The failure-path notification-count refresh now rides the same
    # off-thread async path as success.
    assert app.notification_refreshes_async == 1
    assert app.notification_refreshes == 0
    assert app.async_refreshes == 1
    assert ("Dismiss cleanup failed: boom", "error") in app.notifications


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
        patch("sase.ace.dismissed_agents.record_recent_dismissed_agent_group"),
    ):
        run_tracked_proc(app, app.tracked_procs[0])

    mock_persist_intents.assert_called_once()
    assert mock_persist_intents.call_args[0][1] == [parent, child]
    mock_dismiss_many.assert_not_called()
    mock_save.assert_called_once_with({parent.identity, child.identity})
    assert app.notification_refreshes_async == 1
    assert app.notification_refreshes == 0
    assert app.async_refreshes == 0


def _find_bulk_persistence_task(app: FakeDismissApp) -> dict[str, Any]:
    for task in app.tracked_procs:
        display_name = task["display_name"] or ""
        if task["proc_type"] == "dismiss" and display_name.endswith(
            ("agent", "agents")
        ):
            return task
    raise AssertionError("bulk dismiss persistence task not submitted")


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
        patch("sase.ace.dismissed_agents.record_recent_dismissed_agent_group"),
    ):
        run_tracked_proc(app, _find_bulk_persistence_task(app))

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
        "sase.ace.tui.actions.agents._dismissing.persist_bulk_dismiss_transaction",
        side_effect=RuntimeError("boom"),
    ):
        run_tracked_proc(app, _find_bulk_persistence_task(app))

    assert app.async_refreshes == 1
    assert app.notification_refreshes_async == 0
    assert ("Dismiss cleanup failed: boom", "error") in app.notifications


def test_bulk_dismiss_passes_added_to_artifact_index_sync() -> None:
    """The bulk persistence runner forwards the new identity delta to the sync."""
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
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch(
            "sase.ace.tui.actions.agents._dismissing."
            "sync_dismissed_agent_artifact_index"
        ) as mock_sync_index,
        patch("sase.ace.dismissed_agents.record_recent_dismissed_agent_group"),
    ):
        run_tracked_proc(app, _find_bulk_persistence_task(app))

    mock_sync_index.assert_called_once()
    kwargs = mock_sync_index.call_args.kwargs
    assert kwargs["added"] == {a1.identity, a2.identity}


def test_do_dismiss_all_emits_toast_via_call_after_refresh() -> None:
    """The success toast must be routed through call_after_refresh."""
    app = FakeDismissApp()
    a1 = make_agent(cl_name="a", raw_suffix="20240101120000")
    a2 = make_agent(cl_name="b", raw_suffix="20240101130000")
    app._agents_with_children = [a1, a2]
    app._agents = [a1, a2]

    app._do_dismiss_all([a1, a2])

    assert any(msg == "Dismissed 2 agents" for msg, _ in app.notifications)
