"""Tests for partial agent-loader refreshes after complete history is known."""

from __future__ import annotations

from pathlib import Path

import pytest

from sase.ace.tui.models.agent import AgentType
from tests._agent_loader_self_heal_helpers import (
    INCOMPLETE_INDEX_STATE,
    SOURCE_SCAN_STATE,
    FakeLoadingApp,
    clear_cleaned_artifact_cache,
    make_agent,
)


pytestmark = pytest.mark.usefixtures(clear_cleaned_artifact_cache.__name__)


def test_incomplete_load_after_complete_history_patches_cached_rows() -> None:
    """Tier 1 refreshes after Tier 2 should not shrink the row universe."""
    app = FakeLoadingApp()
    active_cached = make_agent(
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120000",
    )
    active_updated = make_agent(
        cl_name="active",
        status="DONE",
        raw_suffix="20260202120000",
    )
    historical = make_agent(cl_name="historical", raw_suffix="20240102120000")
    dismissed = make_agent(cl_name="dismissed", raw_suffix="20240103120000")
    new_agent = make_agent(cl_name="new", raw_suffix="20260303120000")

    app._agent_load_state = SOURCE_SCAN_STATE
    app._agents_seen_complete_history = True
    app._agents_with_children = [active_cached, historical, dismissed]
    app._agents = list(app._agents_with_children)
    app._dismissed_agents = {dismissed.identity}

    app._apply_loaded_agents(
        [new_agent, active_updated],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260303120000",
        "20260202120000",
        "20240102120000",
    ]
    assert app._agents[1] is active_updated


def test_repeated_incomplete_load_after_complete_history_keeps_cached_rows() -> None:
    """The complete-history watermark survives multiple Tier 1 patches."""
    app = FakeLoadingApp()
    active_cached = make_agent(
        cl_name="active",
        status="RUNNING",
        raw_suffix="20260202120000",
    )
    historical = make_agent(cl_name="historical", raw_suffix="20240102120000")
    launched = make_agent(
        cl_name="launched",
        status="RUNNING",
        raw_suffix="20260303120000",
    )
    launched_updated = make_agent(
        cl_name="launched",
        status="DONE",
        raw_suffix="20260303120000",
    )

    app._apply_loaded_agents(
        [active_cached, historical],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=SOURCE_SCAN_STATE,
    )
    assert app._agents_seen_complete_history is True

    app._apply_loaded_agents(
        [launched],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    app._apply_loaded_agents(
        [launched_updated],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert [a.raw_suffix for a in app._agents] == [
        "20260303120000",
        "20260202120000",
        "20240102120000",
    ]
    assert app._agents[0] is launched_updated


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
        workflow="gh-active",
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


def test_incomplete_load_before_complete_history_still_replaces_list() -> None:
    """First-paint Tier 1 behavior stays capped until Tier 2 reconciles."""
    app = FakeLoadingApp()
    historical = make_agent(cl_name="historical", raw_suffix="20240102120000")
    current = make_agent(cl_name="current", raw_suffix="20260303120000")
    app._agents_with_children = [historical]
    app._agents = [historical]

    app._apply_loaded_agents(
        [current],
        [],
        on_agents_tab=False,
        selected_identity=None,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert app._agents == [current]


def test_incomplete_index_load_repairs_missing_selected_cached_artifact(
    tmp_path: Path,
) -> None:
    """A cached selected source row missing from Tier 1 gets a targeted upsert."""
    app = FakeLoadingApp()
    artifacts_dir = tmp_path / "sase-selected-artifacts"
    artifacts_dir.mkdir()
    selected = make_agent(
        cl_name="selected",
        raw_suffix="20260202120000",
        artifacts_dir=str(artifacts_dir),
    )
    incoming = make_agent(cl_name="incoming", raw_suffix="20260303120000")
    app._agents_with_children = [selected]
    app._agents = [selected]

    upsert_calls: list[tuple[str, str]] = []

    def _schedule_upsert(artifact_dir: str, *, source: str) -> None:
        upsert_calls.append((artifact_dir, source))

    app._schedule_artifact_index_upsert = _schedule_upsert  # type: ignore[method-assign]

    app._apply_loaded_agents(
        [incoming],
        [],
        on_agents_tab=True,
        selected_identity=selected.identity,
        load_state=INCOMPLETE_INDEX_STATE,
    )

    assert upsert_calls == [(str(artifacts_dir), "selected_agent_missing_from_tier1")]
