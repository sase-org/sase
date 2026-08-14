"""Tests for optimistic in-memory agent dismissal.

The dismiss path used to end with a full disk rescan via ``_load_agents``
which took ~11s with many dismissed bundles. These tests cover the row-cache
updates that now happen before the deferred persistence worker runs.
"""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.models.agent import AgentType
from sase.core.notification_store_wire import NotificationUpdateOutcomeWire

from tests._agent_dismiss_helpers import (
    FakeDismissApp,
    make_agent,
    patch_isolated_home,
)

_make_agent = make_agent
_patch_isolated_home = patch_isolated_home


def test_apply_dismissal_removes_agent_from_cached_list() -> None:
    """Dismissing an agent removes it from _agents_with_children."""
    app = FakeDismissApp()
    target = make_agent(cl_name="feature_a", raw_suffix="20240101120000")
    other = make_agent(cl_name="feature_b", raw_suffix="20240101130000")
    app._agents_with_children = [target, other]

    app._apply_dismissal_in_memory([target])

    assert [a.identity for a in app._agents_with_children] == [other.identity]


def test_apply_dismissal_appends_to_dismissed_agent_objects() -> None:
    """Dismissed agent is appended to _dismissed_agent_objects for revive."""
    app = FakeDismissApp()
    target = make_agent()
    app._agents_with_children = [target]

    app._apply_dismissal_in_memory([target])

    assert target in app._dismissed_agent_objects


def test_apply_dismissal_dedupes_dismissed_agent_objects() -> None:
    """Appending is idempotent on identity."""
    app = FakeDismissApp()
    target = make_agent()
    app._agents_with_children = [target]
    app._dismissed_agent_objects = [target]

    app._apply_dismissal_in_memory([target])

    assert len(app._dismissed_agent_objects) == 1


def test_apply_dismissal_includes_workflow_children() -> None:
    """Dismissing a workflow parent also dispatches its children."""
    app = FakeDismissApp()
    parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="20240101120000",
        workflow="wf",
    )
    child = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="feature_a",
        raw_suffix="child_suffix_1",
        parent_workflow="wf",
        parent_timestamp="20240101120000",
    )
    unrelated = make_agent(cl_name="other", raw_suffix="20240101130000")
    app._agents_with_children = [parent, child, unrelated]

    app._apply_dismissal_in_memory([parent])

    remaining = [a.identity for a in app._agents_with_children]
    assert remaining == [unrelated.identity]
    dismissed_ids = {a.identity for a in app._dismissed_agent_objects}
    assert dismissed_ids == {parent.identity, child.identity}


def test_apply_dismissal_includes_parallel_family_members_not_serial_children() -> None:
    """Only explicitly parallel family members follow a root dismissal."""
    app = FakeDismissApp()
    root = make_agent(
        cl_name="sase-6g",
        raw_suffix="root-ts",
        agent_family_parallel=True,
    )
    member = make_agent(
        cl_name="sase-6g.1",
        raw_suffix="member-ts",
        parent_timestamp="root-ts",
        agent_family_parallel=True,
    )
    serial_child = make_agent(
        cl_name="sase-6g--code",
        raw_suffix="serial-ts",
        parent_timestamp="root-ts",
    )
    app._agents_with_children = [root, member, serial_child]

    app._apply_dismissal_in_memory([root])

    assert [agent.identity for agent in app._agents_with_children] == [
        serial_child.identity
    ]
    assert {agent.identity for agent in app._dismissed_agent_objects} == {
        root.identity,
        member.identity,
    }


def test_apply_dismissal_calls_refilter_not_load() -> None:
    """The in-memory path triggers _refilter_agents instead of _load_agents."""
    app = FakeDismissApp()
    target = make_agent()
    app._agents_with_children = [target]

    app._apply_dismissal_in_memory([target])

    assert app.refilter_count == 1
    assert app.load_count == 0


def test_apply_dismissal_batch_removes_all() -> None:
    """Batch dismiss atomically removes all listed identities."""
    app = FakeDismissApp()
    a1 = make_agent(cl_name="a", raw_suffix="20240101120000")
    a2 = make_agent(cl_name="b", raw_suffix="20240101130000")
    a3 = make_agent(cl_name="c", raw_suffix="20240101140000")
    app._agents_with_children = [a1, a2, a3]

    app._apply_dismissal_in_memory([a1, a2])

    assert [a.identity for a in app._agents_with_children] == [a3.identity]
    assert {a.identity for a in app._dismissed_agent_objects} == {
        a1.identity,
        a2.identity,
    }


def test_apply_dismissal_clears_revived_visibility_pin() -> None:
    """Dismissing a revived agent stops preserving it across Tier 1 loads."""
    app = FakeDismissApp()
    target = make_agent(raw_suffix="20240101120000")
    app._agents_with_children = [target]
    app._revived_agent_raw_suffixes = {"20240101120000", "20240101130000"}

    app._apply_dismissal_in_memory([target])

    assert app._revived_agent_raw_suffixes == {"20240101130000"}


def test_persist_dismissed_agent_syncs_projection() -> None:
    """Legacy direct dismissed persistence keeps the Tier 1 projection fresh."""
    app = FakeDismissApp()
    identity = make_agent(raw_suffix="20240101120000").identity
    app._revived_agent_raw_suffixes = {"20240101120000"}

    with (
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
        patch(
            "sase.ace.tui.actions.agents._dismiss_memory."
            "sync_dismissed_agent_artifact_index"
        ) as mock_sync_index,
    ):
        app._persist_dismissed_agent(identity)

    assert identity in app._dismissed_agents
    assert app._revived_agent_raw_suffixes == set()
    mock_save.assert_called_once_with(app._dismissed_agents)
    mock_sync_index.assert_called_once_with(app._dismissed_agents, added={identity})


def test_dismiss_done_agent_is_optimistic_and_schedules_once(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """_dismiss_done_agent removes the row before persistence callbacks run."""
    app = FakeDismissApp()
    agent = make_agent(
        raw_suffix="20240101120000",
        artifacts_dir=str(tmp_path / "artifacts"),
    )
    app._agents_with_children = [agent]
    app._agents = [agent]

    with (
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
    # Persistence is submitted as exactly one tracked proc; no ad
    # hoc call_later coroutine remains.
    assert app._scheduled == []
    assert len(app.tracked_procs) == 1
    task = app.tracked_procs[0]
    assert task["proc_type"] == "dismiss"
    assert task["display_name"] == f"dismiss {agent.display_name}"
    assert agent.identity in app._dismiss_persistence_inflight


def test_dismiss_done_workflow_parent_removes_children(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Dismissing a workflow parent removes both parent and child in memory."""
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

    with (
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

    mock_dismiss_many.assert_not_called()
    mock_delete.assert_not_called()
    mock_bundle.assert_not_called()
    mock_save.assert_not_called()
    assert app.load_count == 0
    assert app.refilter_count == 1
    assert parent.identity in app._dismissed_agents
    assert child.identity in app._dismissed_agents
    assert app._agents_with_children == []
    assert app._scheduled == []
    assert len(app.tracked_procs) == 1
    assert app.tracked_procs[0]["proc_type"] == "dismiss"
    assert len(app._recent_dismissed_agent_groups) == 1
    recent = app._recent_dismissed_agent_groups[0]
    assert recent.source == "recent_dismissal"
    assert [ref.raw_suffix for ref in recent.agent_refs] == [
        "20240101120000",
        "child_suffix_1",
    ]


def test_dismiss_done_patch_agent_does_not_full_reload() -> None:
    """Patch-sourced agents (hooks/mentors/CRS) take the in-memory path."""
    app = FakeDismissApp()
    agent = make_agent(raw_suffix="20240101120000")
    agent._from_patch = True
    app._agents_with_children = [agent]
    app._agents = [agent]

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.dismiss_notifications_for_agents"
        ) as mock_dismiss_many,
        patch("sase.ace.dismissed_agents.save_dismissed_agents") as mock_save,
    ):
        app._dismiss_done_agent(agent)

    mock_dismiss_many.assert_not_called()
    mock_save.assert_not_called()
    assert app.load_count == 0
    assert app.refilter_count == 1
    assert agent.identity in app._dismissed_agents
    assert app._scheduled == []
    assert len(app.tracked_procs) == 1


def test_do_dismiss_all_batch_does_not_full_reload() -> None:
    """Batch dismiss uses the in-memory path and defers disk I/O."""
    app = FakeDismissApp()
    a1 = make_agent(cl_name="a", raw_suffix="20240101120000")
    a2 = make_agent(cl_name="b", raw_suffix="20240101130000")
    app._agents_with_children = [a1, a2]
    app._agents = [a1, a2]

    app._do_dismiss_all([a1, a2])

    # The in-memory refilter is now deferred to the next tick so the
    # success toast can paint before the heavy agents-list rebuild blocks
    # the UI thread.
    assert app.load_count == 0
    assert app.refilter_count == 0
    assert app.notification_refreshes == 0
    assert a1.identity in app._dismissed_agents
    assert a2.identity in app._dismissed_agents
    assert len(app._scheduled) == 1

    refilter_callback, refilter_args = app._scheduled[0]
    assert refilter_callback == app._apply_dismissal_in_memory
    refilter_callback(*refilter_args)
    assert app.refilter_count == 1
    assert app._agents_with_children == []

    # Persistence rides a tracked proc, not a second call_later.
    assert len(app.tracked_procs) == 1
    task = app.tracked_procs[0]
    assert task["proc_type"] == "dismiss"
    assert task["display_name"] == "dismiss 2 agents"
    assert {a1.identity, a2.identity}.issubset(app._dismiss_persistence_inflight)


def test_bulk_dismiss_transaction_uses_one_notification_update() -> None:
    """Bulk dismiss cleanup batches notification dismissal into one Rust update."""
    from sase.ace.tui.actions.agents._dismissing import (
        _persist_bulk_dismiss_transaction,
    )

    a1 = make_agent(cl_name="feature_one", raw_suffix="20260501010101")
    a2 = make_agent(cl_name="feature_two", raw_suffix="20260501020202")
    outcome = NotificationUpdateOutcomeWire(
        schema_version=1,
        matched_count=2,
        changed_count=2,
        rewritten=True,
    )

    with (
        patch(
            "sase.ace.tui.actions.agents._dismissing.persist_bulk_dismiss_side_effects"
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch(
            "sase.notifications.store._rust_apply_notification_state_update",
            return_value=outcome,
        ) as mock_update,
    ):
        _persist_bulk_dismiss_transaction(
            [a1, a2],
            {a1.identity, a2.identity},
            [a1, a2],
        )

    mock_update.assert_called_once()
    update = mock_update.call_args.args[1]
    assert update.kind == "dismiss_matching_agents"
    assert [(agent.cl_name, agent.raw_suffix) for agent in update.agents] == [
        ("feature_one", "20260501010101"),
        ("feature_two", "20260501020202"),
    ]
