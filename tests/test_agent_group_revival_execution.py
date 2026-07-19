"""Execution tests for saved dismissed-agent group revival."""

from __future__ import annotations

from unittest.mock import ANY, patch

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_panels import AgentPanelGroup
from sase.core.agent_group_archive_wire import (
    SavedAgentGroupRefWire,
    SavedAgentGroupWire,
)

from tests._agent_revive_helpers import FakeReviveApp, make_agent


def test_revive_saved_group_restores_parent_child_and_marks_group() -> None:
    app = FakeReviveApp()
    active = make_agent(cl_name="active", raw_suffix="active_suffix", tribe="alpha")
    parent = make_agent(
        cl_name="feature",
        raw_suffix="parent_suffix",
        workflow="wf",
        tribe="beta",
    )
    child = make_agent(
        cl_name="feature-step",
        raw_suffix="child_suffix",
        parent_workflow="wf",
        parent_timestamp="parent_suffix",
        step_index=0,
        tribe="beta",
    )
    app._agents = [active]
    app.loaded_agents = [active, child, parent]
    app._panel_group = AgentPanelGroup.from_agents(app._agents, focused_key="alpha")
    app._dismissed_agents = {
        parent.identity,
        child.identity,
        (AgentType.RUNNING, "alias_parent", "parent_suffix"),
        (AgentType.WORKFLOW, "alias_child", "child_suffix"),
        (AgentType.WORKFLOW, "keep_me", "other_suffix"),
    }

    group = _group("group-a", child, parent)

    with (
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agent_group",
            return_value=group,
        ),
        patch(
            "sase.ace.dismissed_agents.load_dismissed_bundles",
            return_value=[parent, child],
        ) as mock_load_bundles,
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch(
            "sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"
        ) as mock_mark_bundles,
        patch(
            "sase.ace.dismissed_agents.mark_dismissed_agent_group_revived"
        ) as mock_mark_group,
        patch(
            "sase.ace.tui.actions.agents._revive.sync_dismissed_agent_artifact_index"
        ),
        patch(
            "sase.ace.tui.actions.agents._revive.upsert_agent_artifact_index_artifacts"
        ),
    ):
        app._revive_saved_agent_group("group-a")

    mock_load_bundles.assert_called_once_with({"parent_suffix", "child_suffix"})
    mock_mark_bundles.assert_called_once_with({"parent_suffix", "child_suffix"})
    mock_mark_group.assert_called_once_with("group-a", revived_at=ANY)
    assert app._dismissed_agents == {(AgentType.WORKFLOW, "keep_me", "other_suffix")}
    assert app.restored == [
        (parent.identity, None),
        (child.identity, parent.artifacts_dir),
    ]
    assert app.load_count == 1
    assert app.delta_refresh_count == 1
    assert app.refresh_calls == [False]
    assert app.current_idx == 2
    assert app._agents[app.current_idx].raw_suffix == "parent_suffix"
    assert app._panel_group.focused_key == "beta"
    assert {agent.identity for agent in app._dismissed_agent_objects} == {
        parent.identity,
        child.identity,
    }


def test_revive_saved_group_warns_for_missing_refs_and_revives_valid_refs() -> None:
    app = FakeReviveApp()
    parent = make_agent(cl_name="feature", raw_suffix="parent_suffix")
    missing_ref = SavedAgentGroupRefWire(
        agent_type="workflow",
        cl_name="missing",
        raw_suffix="missing_suffix",
        display_name="missing",
    )
    group = _group("group-partial", parent, extra_refs=(missing_ref,))
    app._dismissed_agents = {parent.identity}

    with (
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agent_group",
            return_value=group,
        ),
        patch(
            "sase.ace.dismissed_agents.load_dismissed_bundles",
            return_value=[parent],
        ),
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
        patch(
            "sase.ace.dismissed_agents.mark_dismissed_agent_group_revived"
        ) as mock_mark_group,
        patch(
            "sase.ace.tui.actions.agents._revive.sync_dismissed_agent_artifact_index"
        ),
        patch(
            "sase.ace.tui.actions.agents._revive.upsert_agent_artifact_index_artifacts"
        ),
    ):
        app._revive_saved_agent_group("group-partial")

    assert any(
        message.startswith("Skipped 1 missing saved-group agent")
        and severity == "warning"
        for message, severity in app.notifications
    )
    assert parent.identity not in app._dismissed_agents
    assert app.restored == [(parent.identity, None)]
    mock_mark_group.assert_called_once_with("group-partial", revived_at=ANY)


def test_revive_saved_group_does_not_mark_group_when_no_refs_load() -> None:
    app = FakeReviveApp()
    missing = SavedAgentGroupRefWire(
        agent_type="workflow",
        cl_name="missing",
        raw_suffix="missing_suffix",
        display_name="missing",
    )
    group = SavedAgentGroupWire(
        group_id="group-missing",
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title="1 agent in missing",
        agent_count=1,
        top_level_agent_count=1,
        agent_refs=(missing,),
    )

    with (
        patch(
            "sase.ace.dismissed_agents.load_dismissed_agent_group",
            return_value=group,
        ),
        patch(
            "sase.ace.dismissed_agents.load_dismissed_bundles",
            return_value=[],
        ),
        patch(
            "sase.ace.dismissed_agents.mark_dismissed_agent_group_revived"
        ) as mock_mark_group,
    ):
        app._revive_saved_agent_group("group-missing")

    assert any(
        message == "No agents could be loaded for saved group 1 agent in missing"
        and severity == "warning"
        for message, severity in app.notifications
    )
    mock_mark_group.assert_not_called()
    assert app.load_count == 0


def test_revive_recent_group_loads_cache_first_and_marks_recent_and_saved() -> None:
    app = FakeReviveApp()
    parent = make_agent(cl_name="feature", raw_suffix="parent_suffix")
    group = _group("recent-a", parent)
    app._recent_dismissed_agent_groups = [group]
    app._dismissed_agents = {parent.identity}

    with (
        patch(
            "sase.ace.dismissed_agents.load_recent_dismissed_agent_group"
        ) as mock_load_recent,
        patch(
            "sase.ace.dismissed_agents.load_dismissed_bundles",
            return_value=[parent],
        ) as mock_load_bundles,
        patch("sase.ace.dismissed_agents.save_dismissed_agents"),
        patch("sase.ace.dismissed_agents.mark_bundles_revived_by_suffixes"),
        patch(
            "sase.ace.dismissed_agents.mark_recent_dismissed_agent_group_revived"
        ) as mock_mark_recent,
        patch(
            "sase.ace.dismissed_agents.mark_dismissed_agent_group_revived"
        ) as mock_mark_saved,
        patch(
            "sase.ace.tui.actions.agents._revive.sync_dismissed_agent_artifact_index"
        ),
        patch(
            "sase.ace.tui.actions.agents._revive.upsert_agent_artifact_index_artifacts"
        ),
    ):
        app._revive_saved_agent_group("recent-a", location="recent")

    mock_load_recent.assert_not_called()
    mock_load_bundles.assert_called_once_with({"parent_suffix"})
    mock_mark_recent.assert_called_once_with("recent-a", revived_at=ANY)
    mock_mark_saved.assert_called_once_with("recent-a", revived_at=ANY)
    assert app._recent_dismissed_agent_groups[0].times_revived == 1
    assert app._recent_dismissed_agent_groups[0].revived_at is not None


def _group(
    group_id: str,
    *agents: Agent,
    extra_refs: tuple[SavedAgentGroupRefWire, ...] = (),
) -> SavedAgentGroupWire:
    refs = tuple(_ref(agent) for agent in agents) + extra_refs
    return SavedAgentGroupWire(
        group_id=group_id,
        created_at="2026-05-27T12:00:00Z",
        source="marked_agents",
        title=f"{len(refs)} agents in feature",
        agent_count=len(refs),
        top_level_agent_count=sum(1 for agent in agents if not agent.is_workflow_child),
        status_counts={"DONE": len(refs)},
        project_names=("myproj",),
        cl_names=("feature",),
        agent_refs=refs,
    )


def _ref(agent: Agent) -> SavedAgentGroupRefWire:
    return SavedAgentGroupRefWire(
        agent_type=agent.agent_type.value,
        cl_name=agent.cl_name,
        raw_suffix=agent.raw_suffix,
        bundle_path=getattr(agent, "_dismissed_bundle_path", None),
        is_workflow_child=agent.is_workflow_child,
        parent_timestamp=agent.parent_timestamp,
        display_name=agent.display_name,
        agent_name=agent.agent_name,
        status=agent.status,
        model=agent.model,
        llm_provider=agent.llm_provider,
    )
