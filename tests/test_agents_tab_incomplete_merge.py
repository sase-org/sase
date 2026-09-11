"""Tests for merging incomplete agents-tab loads with complete history."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    merge_incomplete_load_after_complete_history,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_panels import panel_keys_for
from sase.ace.tui.models.agent import Agent, AgentType

from tests._agents_tab_incomplete_merge_helpers import (
    _incomplete_tier1_snapshot,
    _merge_tier1_patch,
)


def test_incomplete_merge_patches_capacity_source_independently() -> None:
    holder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="holder",
        project_file="/tmp/projects/sase/sase.sase",
        status="RUNNING",
        start_time=datetime(2026, 8, 29, 6, 0, 0),
        raw_suffix="20260829060000",
        artifacts_dir="/tmp/projects/sase/artifacts/ace-run/20260829060000",
        pid=111,
        run_start_time=datetime(2026, 8, 29, 6, 0, 0),
        runner_is_live=True,
    )
    cached_waiter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="waiter",
        project_file="/tmp/projects/sase/sase.sase",
        status="WAITING",
        start_time=datetime(2026, 8, 29, 6, 1, 0),
        raw_suffix="20260829060100",
        artifacts_dir="/tmp/projects/sase/artifacts/ace-run/20260829060100",
        pid=222,
        slot_requested_at="2026-08-29T06:01:00Z",
    )
    incoming_waiter = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="waiter",
        project_file="/tmp/projects/sase/sase.sase",
        status="WAITING",
        start_time=datetime(2026, 8, 29, 6, 1, 0),
        raw_suffix="20260829060100",
        artifacts_dir="/tmp/projects/sase/artifacts/ace-run/20260829060100",
        pid=333,
        slot_requested_at="2026-08-29T06:01:01Z",
    )
    prep = PreparedApplyData(
        filtered_agents=[incoming_waiter],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
        capacity_agents=[incoming_waiter],
    )
    snapshot = _incomplete_tier1_snapshot(
        [cached_waiter],
        artifact_source="artifact_delta",
        used_artifact_index=True,
        capacity_agents_with_children=[holder, cached_waiter],
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert prep.filtered_agents == [incoming_waiter]
    assert holder in prep.capacity_agents
    assert incoming_waiter in prep.capacity_agents
    assert cached_waiter not in prep.capacity_agents


def _pre_metadata_latch_rows() -> tuple[Agent, Agent, Agent]:
    project = "/tmp/projects/sase/sase.sase"
    parent_ts = "20260829061545"
    child_ts = "20260829072911"
    generation = "20260829061525"
    stale = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="gh_sase-org__sase",
        project_file=project,
        status="RUNNING",
        start_time=datetime(2026, 8, 29, 7, 29, 11),
        raw_suffix=child_ts,
        pid=3473413,
        runner_is_live=True,
    )
    parent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="toobig-4j.test_workflow_executor.0",
        project_file=project,
        status="RUNNING",
        start_time=datetime(2026, 8, 29, 6, 15, 45),
        raw_suffix=parent_ts,
        agent_name="toobig-4j.test_workflow_executor.0",
        agent_family="toobig-4j.test_workflow_executor.0",
        agent_family_role="root",
        agent_clan="toobig-4j",
        agent_clan_generation=generation,
        clan_tribe="chop",
        tribe="chop",
    )
    fresh = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="gh_sase-org__sase",
        project_file=project,
        status="RUNNING",
        start_time=datetime(2026, 8, 29, 7, 29, 11),
        raw_suffix=child_ts,
        pid=3473413,
        runner_is_live=True,
        agent_name="toobig-4j.test_workflow_executor.0--1",
        parent_timestamp=parent_ts,
        agent_family="toobig-4j.test_workflow_executor.0",
        agent_family_role="root",
        role_suffix="--1",
        agent_clan="toobig-4j",
        agent_clan_generation=generation,
        clan_tribe="chop",
        tribe="chop",
    )
    return stale, parent, fresh


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
    snapshot = _incomplete_tier1_snapshot([cached_parent, cached_child])

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
    snapshot = _incomplete_tier1_snapshot([cached_parent, cached_child])

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


def test_incomplete_merge_replaces_pre_metadata_row_with_fresh_placement() -> None:
    """A cached pre-metadata row must not survive metadata completion."""
    stale, parent, fresh = _pre_metadata_latch_rows()

    rows = _merge_tier1_patch([stale, parent], [fresh])

    matches = [
        agent
        for agent in rows
        if agent.raw_suffix == fresh.raw_suffix and not agent.is_clan_container
    ]
    assert matches == [fresh]
    assert fresh.agent_clan == "toobig-4j"
    assert fresh.agent_clan_generation == "20260829061525"
    assert fresh.parent_timestamp == parent.raw_suffix
    assert fresh.agent_family == "toobig-4j.test_workflow_executor.0"
    assert fresh.role_suffix == "--1"
    assert fresh.is_child_row is True


def test_incomplete_merge_places_metadata_completed_row_in_tribe_panel() -> None:
    """The real merge output must project into the clan's tribe panel."""
    stale, parent, fresh = _pre_metadata_latch_rows()

    rows = _merge_tier1_patch([stale, parent], [fresh])
    panel_keys = panel_keys_for(project_clan_tree(rows))

    assert "chop" in panel_keys
    assert None not in panel_keys
