"""Tests for deferred dismiss persistence and cleanup transactions."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any
from unittest.mock import call, patch

from sase.ace.tui.models.agent import AgentType
from sase.core.agent_cleanup_wire import AgentCleanupIdentityWire
from sase.running_field import ClaimResult, WorkspaceClaim

from tests._agent_cleanup_task_helpers import run_tracked_task
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
        run_tracked_task(app, app.tracked_tasks[0])

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
        "sase.ace.tui.actions.agents._dismissing._persist_single_dismiss_transaction",
        side_effect=RuntimeError("boom"),
    ):
        run_tracked_task(app, app.tracked_tasks[0])

    # The failure-path notification-count refresh now rides the same
    # off-thread async path as success.
    assert app.notification_refreshes_async == 1
    assert app.notification_refreshes == 0
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
        patch("sase.ace.dismissed_agents.record_recent_dismissed_agent_group"),
    ):
        run_tracked_task(app, app.tracked_tasks[0])

    mock_persist_intents.assert_called_once()
    assert mock_persist_intents.call_args[0][1] == [parent, child]
    mock_dismiss_many.assert_not_called()
    mock_save.assert_called_once_with({parent.identity, child.identity})
    assert app.notification_refreshes_async == 1
    assert app.notification_refreshes == 0
    assert app.async_refreshes == 0


def _find_bulk_persistence_task(app: FakeDismissApp) -> dict[str, Any]:
    for task in app.tracked_tasks:
        display_name = task["display_name"] or ""
        if task["task_type"] == "dismiss" and display_name.endswith(
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
        run_tracked_task(app, _find_bulk_persistence_task(app))

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
        run_tracked_task(app, _find_bulk_persistence_task(app))

    assert app.async_refreshes == 1
    assert app.notification_refreshes_async == 0
    assert any(sev == "error" for _, sev in app.notifications)
    assert any("in memory" in msg for msg, _ in app.notifications)


def test_dismiss_side_effects_delete_artifact_index_row(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Marker deletion also removes the stale SQLite index row best-effort."""
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        persist_dismiss_side_effects,
    )

    agent = make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence.delete_agent_artifacts"
        ) as mock_delete_artifacts,
    ):
        persist_dismiss_side_effects(agent, [agent])

    mock_delete_index.assert_called_once_with([str(tmp_path / "artifacts")])
    mock_delete_artifacts.assert_called_once_with(str(tmp_path / "artifacts"))


def test_dismiss_side_effects_register_expected_delete_before_artifact_cleanup(
    tmp_path,
) -> None:  # type: ignore[no-untyped-def]
    """Dismiss persistence can notify the watcher before deleting artifacts."""
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        persist_dismiss_side_effects,
    )

    agent = make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    registered: list[str | None] = []

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "delete_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence.delete_agent_artifacts"
        ) as mock_delete_artifacts,
    ):
        persist_dismiss_side_effects(
            agent,
            [agent],
            register_expected_deletion=registered.append,
        )

    mock_delete_artifacts.assert_called_once_with(
        str(tmp_path / "artifacts"),
        before_delete=registered.append,
    )


def test_delete_agent_artifacts_deletes_artifact_index_row(  # type: ignore[no-untyped-def]
    tmp_path,
) -> None:
    """Shared marker cleanup deletes the stale SQLite index row itself."""
    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    done_marker = artifacts_dir / "done.json"
    done_marker.write_text("{}", encoding="utf-8")

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils."
            "delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            return_value=False,
        ),
    ):
        delete_agent_artifacts(str(artifacts_dir))

    mock_delete_index.assert_called_once_with([str(artifacts_dir)])
    assert not done_marker.exists()


def test_delete_agent_artifacts_resolves_waiters_before_deleting_done_marker(  # type: ignore[no-untyped-def]
    tmp_path,
    monkeypatch,
) -> None:
    """Dismissing a completed dependency should not strand active waiters."""
    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    parent_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706130831"
    waiter_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706131004"
    parent_dir.mkdir(parents=True)
    waiter_dir.mkdir(parents=True)
    (parent_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b"}),
        encoding="utf-8",
    )
    (parent_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    (waiter_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b--launch"}),
        encoding="utf-8",
    )
    (waiter_dir / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": ["b"],
                "wait_for_artifacts": [
                    {
                        "project_name": "proj",
                        "timestamp": parent_dir.name,
                        "artifact_dir": str(parent_dir),
                        "name": "b",
                    }
                ],
                "cl_name": "waiter-cl",
                "timestamp": waiter_dir.name,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils."
            "delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            return_value=False,
        ),
    ):
        delete_agent_artifacts(str(parent_dir))

    ready = json.loads((waiter_dir / "ready.json").read_text(encoding="utf-8"))
    assert ready == {"resolved_deps": ["b"]}
    mock_delete_index.assert_called_once_with([str(parent_dir)])
    assert not (parent_dir / "done.json").exists()


def test_delete_agent_artifacts_keeps_waiter_with_other_unresolved_dependency(  # type: ignore[no-untyped-def]
    tmp_path,
    monkeypatch,
) -> None:
    """Dismissing one completed dep must not unblock a multi-dep waiter early."""
    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    parent_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706130831"
    waiter_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706131004"
    parent_dir.mkdir(parents=True)
    waiter_dir.mkdir(parents=True)
    (parent_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b"}),
        encoding="utf-8",
    )
    (parent_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}),
        encoding="utf-8",
    )
    (waiter_dir / "agent_meta.json").write_text(
        json.dumps({"name": "multi-waiter"}),
        encoding="utf-8",
    )
    (waiter_dir / "waiting.json").write_text(
        json.dumps(
            {
                "waiting_for": ["b", "c"],
                "wait_for_artifacts": [
                    {
                        "project_name": "proj",
                        "timestamp": parent_dir.name,
                        "artifact_dir": str(parent_dir),
                        "name": "b",
                    }
                ],
                "cl_name": "waiter-cl",
                "timestamp": waiter_dir.name,
            }
        ),
        encoding="utf-8",
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils."
            "delete_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            return_value=False,
        ),
    ):
        delete_agent_artifacts(str(parent_dir))

    assert not (waiter_dir / "ready.json").exists()
    waiting = json.loads((waiter_dir / "waiting.json").read_text(encoding="utf-8"))
    assert waiting["resolved_deps"] == [
        "b",
        {
            "name": "b",
            "project_name": "proj",
            "timestamp": parent_dir.name,
            "artifact_dir": str(parent_dir),
        },
    ]
    assert not (parent_dir / "done.json").exists()

    c_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706131105"
    c_dir.mkdir()
    (c_dir / "agent_meta.json").write_text(json.dumps({"name": "c"}), encoding="utf-8")
    (c_dir / "done.json").write_text(
        json.dumps({"outcome": "completed"}), encoding="utf-8"
    )
    from sase.core.wait_dependency_resolution import (
        build_wait_dependency_index,
        dependency_resolution_status,
    )

    index = build_wait_dependency_index(
        "proj", projects_root=tmp_path / ".sase/projects"
    )
    assert dependency_resolution_status(
        index,
        waiting["waiting_for"],
        waiting["wait_for_artifacts"],
        waiting["resolved_deps"],
        self_artifact_dir=waiter_dir,
    ).resolved


def test_delete_failed_dependency_leaves_waiter_untouched(  # type: ignore[no-untyped-def]
    tmp_path,
    monkeypatch,
) -> None:
    from sase.ace.tui.actions.agents._killing_utils import delete_agent_artifacts

    monkeypatch.setenv("SASE_HOME", str(tmp_path / ".sase"))
    parent_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706130831"
    waiter_dir = tmp_path / ".sase/projects/proj/artifacts/ace-run/20260706131004"
    parent_dir.mkdir(parents=True)
    waiter_dir.mkdir(parents=True)
    (parent_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b"}), encoding="utf-8"
    )
    (parent_dir / "done.json").write_text(
        json.dumps({"outcome": "killed"}), encoding="utf-8"
    )
    (waiter_dir / "agent_meta.json").write_text(
        json.dumps({"name": "b--launch"}), encoding="utf-8"
    )
    original_waiting = {
        "waiting_for": ["b"],
        "wait_for_artifacts": [
            {
                "project_name": "proj",
                "timestamp": parent_dir.name,
                "artifact_dir": str(parent_dir),
                "name": "b",
            }
        ],
        "cl_name": "waiter-cl",
        "timestamp": waiter_dir.name,
    }
    (waiter_dir / "waiting.json").write_text(
        json.dumps(original_waiting), encoding="utf-8"
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._killing_utils."
            "delete_agent_artifact_index_artifacts"
        ),
        patch(
            "sase.ace.tui.actions.agents._killing_utils.try_delete_agent_artifacts",
            return_value=False,
        ),
    ):
        delete_agent_artifacts(str(parent_dir))

    assert not (waiter_dir / "ready.json").exists()
    assert json.loads((waiter_dir / "waiting.json").read_text()) == original_waiting


def test_bulk_dismiss_fallback_batches_artifact_index_deletes(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Per-agent fallback should issue a *single* artifact-index delete call."""
    from sase.ace.tui.actions.agents._dismiss_persistence import (
        persist_bulk_dismiss_side_effects,
    )

    a1 = make_agent(
        cl_name="a",
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "a1"),
    )
    a2 = make_agent(
        cl_name="b",
        raw_suffix="20240101130000",
        artifacts_dir=str(tmp_path / "a2"),
    )
    a3 = make_agent(
        cl_name="c",
        raw_suffix="20240101140000",
        artifacts_dir=str(tmp_path / "a3"),
    )

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_bundle"),
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence."
            "delete_agent_artifact_index_artifacts"
        ) as mock_delete_index,
        patch(
            "sase.ace.tui.actions.agents._dismiss_persistence.delete_agent_artifacts"
        ) as mock_delete_artifacts,
    ):
        persist_bulk_dismiss_side_effects([a1, a2, a3], [a1, a2, a3])

    mock_delete_index.assert_called_once()
    assert mock_delete_index.call_args[0][0] == [
        str(tmp_path / "a1"),
        str(tmp_path / "a2"),
        str(tmp_path / "a3"),
    ]
    assert mock_delete_artifacts.call_count == 3


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
        run_tracked_task(app, _find_bulk_persistence_task(app))

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
