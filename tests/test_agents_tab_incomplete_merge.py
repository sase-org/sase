"""Tests for merging incomplete agents-tab loads with complete history."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    merge_incomplete_load_after_complete_history,
)
from sase.ace.tui.models._agent_tree import project_clan_tree
from sase.ace.tui.models.agent_panels import panel_keys_for
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState, load_artifact_delta_agents
from sase.core.agent_scan_wire import AgentClanContextWire

from tests._agents_tab_query_helpers import _make_agent


def _merge_tier1_patch(cached: list[Agent], incoming: list[Agent]) -> list[Agent]:
    prep = PreparedApplyData(
        filtered_agents=incoming,
        has_always_visible=bool(incoming),
        hidden_count=0,
        hideable_agents=list(incoming),
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=cached,
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
    return prep.filtered_agents


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


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_exact_child_delta_remirrors_tale_family_root_to_done(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child-only exact delta must remirror the tale root to TALE DONE."""
    sase_home = tmp_path / ".sase"
    monkeypatch.setenv("SASE_HOME", str(sase_home))
    root_ts = "20260828135111"
    code_ts = "20260828140403"
    project_dir = sase_home / "projects" / "home"
    project_file = project_dir / "home.sase"
    project_file.parent.mkdir(parents=True)
    project_file.write_text("NAME: home\n", encoding="utf-8")
    root_dir = project_dir / "artifacts" / "ace-run" / root_ts
    code_dir = project_dir / "artifacts" / "ace-run" / code_ts

    _write_json(
        root_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "context": {"cl_name": "0fn"},
            "status": "completed",
            "appears_as_agent": True,
            "start_time": "2026-08-28T13:51:11",
            "steps": [],
        },
    )
    _write_json(
        root_dir / "agent_meta.json",
        {
            "name": "0fn",
            "agent_family": "0fn",
            "agent_family_role": "root",
            "plan_chain_root": True,
            "role_suffix": "--plan",
            "plan": True,
            "plan_approved": True,
            "plan_action": "tale",
            "plan_submitted_at": "2026-08-28T14:00:00Z",
            "run_started_at": "2026-08-28T13:51:11Z",
        },
    )
    _write_json(root_dir / "done.json", {"outcome": "completed", "cl_name": "0fn"})
    _write_json(
        code_dir / "running.json",
        {"pid": 4242, "cl_name": "0fn--code"},
    )
    _write_json(
        code_dir / "agent_meta.json",
        {
            "name": "0fn--code",
            "agent_family": "0fn",
            "agent_family_role": "code",
            "role_suffix": "--code",
            "parent_timestamp": root_ts,
            "plan_action": "tale",
            "run_started_at": "2026-08-28T14:04:03Z",
        },
    )

    with (
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=True,
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
            return_value=True,
        ),
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
    ):
        before, _ = load_artifact_delta_agents(
            [root_dir, code_dir],
            patch_snapshot=[],
            update_index=False,
        )

    by_name = {agent.agent_name: agent for agent in before if agent.agent_name}
    assert by_name["0fn"].status == "WORKING TALE"
    assert by_name["0fn--code"].status == "WORKING TALE"

    (code_dir / "running.json").unlink()
    _write_json(
        code_dir / "done.json",
        {"outcome": "completed", "cl_name": "0fn--code"},
    )

    with (
        patch("sase.ace.agent_tribes.load_agent_tribes", return_value={}),
        patch(
            "sase.ace.tui.models.agent_loader.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.models._loaders._running_loaders.is_process_running",
            return_value=False,
        ),
        patch(
            "sase.ace.tui.models._loaders._workflow_loaders.is_process_running",
            return_value=False,
        ),
    ):
        incoming, load_state = load_artifact_delta_agents(
            [code_dir],
            patch_snapshot=[],
            update_index=False,
        )

    assert load_state.artifact_source == "artifact_delta"
    prep = PreparedApplyData(
        filtered_agents=list(incoming),
        has_always_visible=False,
        hidden_count=0,
        hideable_agents=list(incoming),
        dismissed_agent_objects=[],
    )
    snapshot = PreparedApplySnapshot(
        cached_agents_with_children=list(before),
        dismissed_agents=set(),
        agents_seen_complete_history=True,
        hide_non_run_agents=False,
        load_state=load_state,
        fold_levels=None,
        selection=PreparedApplySelectionInputs(
            on_agents_tab=False,
            selected_identity=None,
            prior_visual_row=None,
        ),
    )

    merge_incomplete_load_after_complete_history(prep, snapshot)

    merged = {
        agent.agent_name: agent
        for agent in prep.filtered_agents
        if agent.agent_name and not agent.is_clan_container
    }
    assert merged["0fn"].status == "TALE DONE"
    assert merged["0fn--code"].status == "TALE DONE"
