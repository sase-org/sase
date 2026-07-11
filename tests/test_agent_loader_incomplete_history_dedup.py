"""Tests for incomplete-history patch dedup behavior."""

from __future__ import annotations

import pytest

from sase.ace.tui.models.agent import AgentType
from tests._agent_loader_self_heal_helpers import (
    INCOMPLETE_INDEX_STATE,
    SOURCE_SCAN_STATE,
    FakeLoadingApp,
    clear_cleaned_artifact_cache,
    make_agent,
)


@pytest.fixture(autouse=True)
def _clear_cleaned_artifact_cache() -> None:
    clear_cleaned_artifact_cache()


def test_incomplete_load_after_complete_history_drops_running_duplicate_root() -> None:
    """A Tier 1 RUNNING row must not duplicate a cached WORKFLOW parent."""
    app = FakeLoadingApp()
    raw_suffix = "20260202120000"
    workflow_parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="ace-run",
        appears_as_agent=True,
    )
    workflow_child = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active.step",
        status="RUNNING",
        raw_suffix="20260202120001",
        parent_workflow="ace-run",
        parent_timestamp=raw_suffix,
        step_name="prompt",
        step_type="agent",
        step_index=0,
        total_steps=1,
    )
    incoming_running = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="run",
    )

    app._agent_load_state = SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [workflow_parent, workflow_child]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_running],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [workflow_parent, workflow_child]


def test_incomplete_load_after_complete_history_keeps_non_workflow_suffix_guard() -> (
    None
):
    """Suffix shadows not handled by canonical dedup are still suppressed."""
    app = FakeLoadingApp()
    raw_suffix = "20260202120000"
    cached_running = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="run",
    )
    incoming_running = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="unknown",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="run",
    )

    app._agent_load_state = SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [cached_running]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_running],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [cached_running]


def test_incomplete_load_after_complete_history_merges_running_shadow_metadata() -> (
    None
):
    """A dropped Tier 1 RUNNING shadow still donates metadata to the parent."""
    app = FakeLoadingApp()
    raw_suffix = "20260202120000"
    workflow_parent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="ace-run",
        appears_as_agent=True,
    )
    workflow_child = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active.step",
        status="RUNNING",
        raw_suffix="20260202120001",
        parent_workflow="ace-run",
        parent_timestamp=raw_suffix,
        step_name="prompt",
        step_type="agent",
        step_index=0,
        total_steps=1,
    )
    incoming_running = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix=raw_suffix,
        workflow="run",
        workspace_num=7,
        response_path="/tmp/response.md",
        model="claude-opus-4-20250514",
        vcs_provider="GitHub",
        agent_name="active-agent",
        step_output={"meta_workspace": "7", "stdout": "done"},
    )

    app._agent_load_state = SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [workflow_parent, workflow_child]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_running],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [workflow_parent, workflow_child]
    assert workflow_parent.workspace_num == 7
    assert workflow_parent.response_path == "/tmp/response.md"
    assert workflow_parent.model == "claude-opus-4-20250514"
    assert workflow_parent.vcs_provider == "GitHub"
    assert workflow_parent.agent_name == "active-agent"
    assert workflow_parent.step_output == {"meta_workspace": "7", "stdout": "done"}


def test_incomplete_load_after_complete_history_dedups_cross_snapshot_same_pid() -> (
    None
):
    """Post-history Tier 1 patches keep loader-level same-PID invariants."""
    app = FakeLoadingApp()
    cached_vcs_claim = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120000",
        workflow="git-active",
        pid=4242,
        workspace_num=9,
        model="cached-model",
    )
    incoming_non_vcs = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120100",
        workflow="custom",
        pid=4242,
    )

    app._agent_load_state = SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [cached_vcs_claim]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_non_vcs],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [incoming_non_vcs]
    assert incoming_non_vcs.workspace_num == 9
    assert incoming_non_vcs.model == "cached-model"


def test_incomplete_load_after_complete_history_reattaches_pid_dedup_children() -> None:
    """Children of a removed same-PID parent stay attached to the survivor."""
    app = FakeLoadingApp()
    cached_suffix = "20260202120000"
    incoming_suffix = "20260202120100"
    cached_running = make_agent(
        agent_type=AgentType.RUNNING,
        cl_name="active",
        status="RUNNING",
        raw_suffix=cached_suffix,
        workflow="ace(run)",
        pid=4243,
        workspace_num=11,
    )
    cached_child = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active.step",
        status="RUNNING",
        raw_suffix="20260202120001",
        parent_timestamp=cached_suffix,
        step_name="prompt",
        step_type="agent",
        step_index=0,
        total_steps=1,
    )
    incoming_workflow = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="active",
        status="RUNNING",
        raw_suffix=incoming_suffix,
        workflow="run",
        appears_as_agent=True,
        pid=4243,
    )

    app._agent_load_state = SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [cached_running, cached_child]
    app._agents = list(app._agents_with_children)

    app._apply_loaded_agents(
        [incoming_workflow],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [incoming_workflow, cached_child]
    assert incoming_workflow.workspace_num == 11
    assert cached_child.parent_timestamp == incoming_suffix
