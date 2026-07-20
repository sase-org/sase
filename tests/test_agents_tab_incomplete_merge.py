"""Tests for merging incomplete agents-tab loads with complete history."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    merge_incomplete_load_after_complete_history,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.core.agent_scan_wire import AgentClanContextWire

from tests._agents_tab_query_helpers import _make_agent


def test_incomplete_merge_refresh_preserves_child_derived_timestamps() -> None:
    """Tier-1 patch merge must rebuild parent fields derived from cached children."""
    parent_ts = "20260521090000"
    code_ts = "20260521090800"
    code_started = datetime(2026, 5, 21, 9, 8, 5)
    cached_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 21, 9, 0, 0),
        raw_suffix=parent_ts,
        role_suffix=".plan",
    )
    cached_parent.plan_times = [datetime(2026, 5, 21, 9, 4, 0)]
    cached_child = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl.code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=datetime(2026, 5, 21, 9, 8, 0),
        run_start_time=code_started,
        raw_suffix=code_ts,
        parent_timestamp=parent_ts,
        role_suffix=".code",
    )
    cached_parent.code_time = code_started
    cached_parent.runtime_children.append(cached_child)

    fresh_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 21, 9, 0, 0),
        raw_suffix=parent_ts,
        role_suffix=".plan",
    )
    fresh_parent.plan_times = list(cached_parent.plan_times)
    prep = PreparedApplyData(
        filtered_agents=[fresh_parent],
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=[fresh_parent],
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[cached_parent, cached_child],
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert prep.filtered_agents[0] is fresh_parent
    assert prep.filtered_agents.index(cached_child) > prep.filtered_agents.index(
        fresh_parent
    )
    assert fresh_parent.code_time == code_started
    assert cached_child in fresh_parent.runtime_children
    assert cached_child in prep.filtered_agents
    assert "CODE  | 2026-05-21 09:08:05" in fresh_parent.timestamps_display


def test_incomplete_merge_replaces_plan_chain_child_with_transient_cl_name() -> None:
    """Same artifact-backed child rows must merge even when ``cl_name`` changes."""
    parent_ts = "20260524113000"
    code_ts = "20260524114223"
    code_started = datetime(2026, 5, 24, 11, 42, 23)
    cached_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="PLAN APPROVED",
        start_time=datetime(2026, 5, 24, 11, 30, 0),
        raw_suffix=parent_ts,
        workflow="sase",
        pid=5150,
        role_suffix="-plan",
        agent_name="a90",
        agent_family="a90",
        agent_family_role="root",
        plan_chain_root=True,
    )
    cached_child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="a90-code",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=code_started,
        run_start_time=code_started,
        raw_suffix=code_ts,
        workflow="sase",
        pid=5150,
        parent_timestamp=parent_ts,
        role_suffix="-code",
        agent_name="a90-code",
        agent_family="a90",
        agent_family_role="code",
        model="cached-model",
    )
    refreshed_child = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="sase",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=code_started,
        run_start_time=code_started,
        raw_suffix=code_ts,
        workflow="sase",
        pid=5150,
        parent_timestamp=parent_ts,
        role_suffix="-code",
        agent_name="a90-code",
        agent_family="a90",
        agent_family_role="code",
        model="fresh-model",
        llm_provider="codex",
    )
    prep = PreparedApplyData(
        filtered_agents=[refreshed_child],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[cached_parent, cached_child],
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_index",
            used_artifact_index=True,
        ),
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    code_children = [
        agent
        for agent in prep.filtered_agents
        if agent.parent_timestamp == parent_ts and agent.raw_suffix == code_ts
    ]
    assert code_children == [refreshed_child]
    assert cached_child not in prep.filtered_agents
    assert refreshed_child.cl_name == "sase"
    assert refreshed_child.model == "fresh-model"
    assert refreshed_child.llm_provider == "codex"


def test_artifact_delta_deleted_dir_removes_cached_row() -> None:
    """A watcher deletion delta should delete the cached artifact-backed row."""
    artifact_dir = Path("/tmp/projects/sase/artifacts/ace-run/20260528120000")
    cached = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="feature",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=datetime(2026, 5, 28, 12, 0, 0),
        raw_suffix="20260528120000",
        artifacts_dir=str(artifact_dir),
    )
    prep = PreparedApplyData(
        filtered_agents=[],
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[cached],
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_delta",
            used_artifact_index=False,
            deleted_artifact_dirs=frozenset({str(artifact_dir)}),
        ),
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert prep.filtered_agents == []


def test_artifact_delta_preserves_cached_clan_context() -> None:
    """An exact joiner-only delta cannot erase reconciled clan context."""
    context = AgentClanContextWire(
        agent_clan="toobig-0",
        agent_clan_generation="g1",
        clan_tribe="chop",
        clan_tribe_source_launch_timestamp="20260701000000",
        clan_tribe_source_identity="/tmp/declarer",
    )
    cached = _make_agent(
        cl_name="toobig-0.joiner",
        raw_suffix="20260701000001",
        status="WAITING",
    )
    cached.agent_clan = "toobig-0"
    cached.agent_clan_generation = "g1"
    cached.clan_context = context
    refreshed = _make_agent(
        cl_name="toobig-0.joiner",
        raw_suffix="20260701000001",
        status="WAITING",
    )
    refreshed.agent_clan = "toobig-0"
    refreshed.agent_clan_generation = "g1"
    refreshed.clan_context = AgentClanContextWire(
        agent_clan="toobig-0",
        agent_clan_generation="g1",
    )
    prep = PreparedApplyData(
        filtered_agents=[refreshed],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[cached],
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_delta",
            used_artifact_index=False,
        ),
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert [agent for agent in prep.filtered_agents if not agent.is_clan_container] == [
        refreshed
    ]
    assert refreshed.clan_context is not None
    assert refreshed.clan_context.clan_tribe == "chop"
    container = project_clan_tree(prep.filtered_agents)[0]
    assert container.clan_tribes == ("chop",)


def test_artifact_delta_retry_projection_survives_cached_family_reattach() -> None:
    """An exact root retry delta must outrank its cached failed coder child."""
    root_timestamp = "20260706115800"
    cached_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retry-family",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 6, 11, 58, 0),
        raw_suffix=root_timestamp,
        role_suffix="--plan",
        plan_action="tale",
        agent_family="retry-family",
        agent_family_role="root",
        plan_chain_root=True,
    )
    cached_coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="retry-family--code",
        project_file="/tmp/test.sase",
        status="FAILED",
        start_time=datetime(2026, 7, 6, 11, 59, 0),
        raw_suffix="20260706115900",
        parent_timestamp=root_timestamp,
        role_suffix="--code",
        agent_family="retry-family",
        agent_family_role="code",
    )
    refreshed_parent = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="retry-family",
        project_file="/tmp/test.sase",
        status="RETRYING",
        start_time=datetime(2026, 7, 6, 11, 58, 0),
        raw_suffix=root_timestamp,
        role_suffix="--plan",
        plan_action="tale",
        agent_family="retry-family",
        agent_family_role="root",
        plan_chain_root=True,
        runner_is_live=True,
        retry_status="retrying",
        retry_count=2,
        max_retries=3,
        retry_next_at_epoch=1_800_000_000.0,
    )
    prep = PreparedApplyData(
        filtered_agents=[refreshed_parent],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=[cached_parent, cached_coder],
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source="artifact_delta",
            used_artifact_index=False,
        ),
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    root = next(
        agent
        for agent in prep.filtered_agents
        if agent.raw_suffix == root_timestamp and not agent.is_child_row
    )
    coder = next(
        agent for agent in prep.filtered_agents if agent.agent_family_role == "code"
    )
    assert root is refreshed_parent
    assert root.status == "RETRYING"
    assert (root.retry_count, root.max_retries) == (2, 3)
    assert root.retry_next_at_epoch == 1_800_000_000.0
    assert coder is cached_coder
    assert coder.status == "FAILED"
