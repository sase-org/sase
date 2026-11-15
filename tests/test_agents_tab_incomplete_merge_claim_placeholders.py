"""Focused merge tests for stale workspace-claim placeholders.

A long-running TUI must never count or hide agents because of stale
RUNNING-field claim rows. These tests pin the roster-cache maintenance from
``202611/phantom_starting_claim_rows.md`` next to the existing merge suites
without growing ``tests/test_agents_tab_incomplete_merge.py``.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from sase.ace.tui.models._dedup import (
    dedup_by_pid,
    dedup_running_vs_workflow,
)
from sase.ace.tui.models._loaders._running_loaders import (
    ResolvedRunningFieldClaim,
    load_agents_from_resolved_running_claims,
)
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState
from sase.ace.tui.models.agent_panel_index import build_agent_panel_index

from tests._agents_tab_incomplete_merge_helpers import (
    _artifact_delta_load_state,
    _incomplete_tier1_snapshot,
    _merge_tier1_patch,
)

_DISMISSABLE = {"DONE", "FAILED"}
_PROJECT = "/tmp/test.sase"
_STARTED = datetime(2026, 11, 15, 12, 30, 45)
_SUFFIX = "20261115123045"


def _claim_scanning_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        running_claims_scanned=True,
    )


def _workflow_row() -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="my_cl",
        project_file=_PROJECT,
        status="RUNNING",
        start_time=_STARTED,
        raw_suffix=_SUFFIX,
        agent_name="my_cl",
        artifacts_dir=f"/tmp/projects/sase/artifacts/ace-run/{_SUFFIX}",
    )


def _preclaim_placeholder(*, pid: int = 424242) -> Agent:
    """Launcher-PID pre-claim: no artifacts timestamp, never rendered."""
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file=_PROJECT,
        status="STARTING",
        start_time=_STARTED,
        workspace_num=16,
        workflow="ace(run)-261115_123045",
        pid=pid,
        runner_is_live=True,
        raw_suffix=None,
        from_running_claim=True,
    )


def _suffixed_claim_placeholder() -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name="my_cl",
        project_file=_PROJECT,
        status="STARTING",
        start_time=_STARTED,
        workspace_num=16,
        workflow="ace(run)",
        pid=424243,
        runner_is_live=True,
        raw_suffix=_SUFFIX,
        from_running_claim=True,
    )


def test_preclaim_placeholder_is_dropped_by_claim_scanning_load() -> None:
    cached = [_workflow_row(), _preclaim_placeholder()]
    rows = _merge_tier1_patch(
        cached,
        [_workflow_row()],
        load_state=_claim_scanning_state(),
    )

    assert all(agent.status != "STARTING" for agent in rows)
    assert all(not agent.from_running_claim for agent in rows)
    index = build_agent_panel_index(rows, dismissable_statuses=_DISMISSABLE)
    assert index.hidden_starting_indices == []


def test_live_placeholder_is_not_duplicated() -> None:
    cached = [_workflow_row(), _preclaim_placeholder()]
    rows = _merge_tier1_patch(
        cached,
        [_workflow_row(), _preclaim_placeholder(pid=424244)],
        load_state=_claim_scanning_state(),
    )

    placeholders = [agent for agent in rows if agent.status == "STARTING"]
    assert len(placeholders) == 1
    assert placeholders[0].from_running_claim is True


def test_suffixed_claim_yields_to_artifact_row_on_claim_scanning_load() -> None:
    cached = [_suffixed_claim_placeholder()]
    incoming = [_workflow_row()]
    rows = _merge_tier1_patch(
        cached,
        incoming,
        load_state=_claim_scanning_state(),
    )

    by_suffix = {
        agent.raw_suffix: agent for agent in rows if not agent.is_workflow_child
    }
    assert by_suffix[_SUFFIX].agent_type == AgentType.WORKFLOW
    assert by_suffix[_SUFFIX].status == "RUNNING"
    assert by_suffix[_SUFFIX].agent_name == "my_cl"
    assert all(agent.status != "STARTING" for agent in rows)


def test_suffixed_claim_yields_to_artifact_row_on_artifact_delta() -> None:
    cached = [_suffixed_claim_placeholder()]
    incoming = [_workflow_row()]
    rows = _merge_tier1_patch(
        cached,
        incoming,
        load_state=_artifact_delta_load_state(),
    )

    by_suffix = {
        agent.raw_suffix: agent for agent in rows if not agent.is_workflow_child
    }
    assert by_suffix[_SUFFIX].agent_type == AgentType.WORKFLOW
    assert by_suffix[_SUFFIX].status == "RUNNING"
    assert all(agent.status != "STARTING" for agent in rows)


def test_artifact_delta_keeps_unsuperseded_claim_row() -> None:
    cached = [_suffixed_claim_placeholder()]
    rows = _merge_tier1_patch(
        cached,
        [],
        load_state=_artifact_delta_load_state(),
    )

    assert len(rows) == 1
    assert rows[0].status == "STARTING"
    assert rows[0].from_running_claim is True
    assert rows[0].raw_suffix == _SUFFIX


def test_claim_provenance_through_dedup() -> None:
    records = [
        ResolvedRunningFieldClaim(
            project_file=_PROJECT,
            workspace_num=16,
            workflow="ace(run)",
            cl_name="my_cl",
            pid=424245,
            normalized_timestamp=_SUFFIX,
            start_time=_STARTED,
            agent_type=AgentType.RUNNING,
        )
    ]
    claims = load_agents_from_resolved_running_claims(records, {}, {})
    assert len(claims) == 1
    assert claims[0].from_running_claim is True

    # Copy helpers must preserve provenance for cached rows.
    from sase.ace.tui.models._agent_graph import (
        copy_agent_graph,
        copy_agent_rows_relinked,
    )

    assert copy_agent_rows_relinked(claims)[0].from_running_claim is True
    assert copy_agent_graph(claims)[0].from_running_claim is True

    merged = dedup_running_vs_workflow([*claims, _workflow_row()])
    assert len(merged) == 1
    assert merged[0].agent_type == AgentType.WORKFLOW
    assert merged[0].from_running_claim is False

    # PID dedup also keeps WORKFLOW survivors artifact-backed.
    pid_claim = _suffixed_claim_placeholder()
    pid_claim.pid = 424246
    pid_workflow = _workflow_row()
    pid_workflow.pid = 424246
    # Same artifact suffix so PID dedup collapses them.
    pid_merged = dedup_by_pid([pid_claim, pid_workflow])
    assert len(pid_merged) == 1
    assert pid_merged[0].agent_type == AgentType.WORKFLOW
    assert pid_merged[0].from_running_claim is False


def test_load_state_flag_claim_scanning_vs_delta_and_short_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import sase.ace.tui.models.agent_loader as loader

    from sase.core.agent_scan_wire import (
        AgentArtifactScanStatsWire,
        AgentArtifactScanWire,
    )

    from sase.ace.tui.models import _agent_loader_artifact_config as loader_config

    snapshot = AgentArtifactScanWire(
        schema_version=1,
        projects_root="/tmp",
        options=loader_config.TUI_SCAN_OPTIONS,
        stats=AgentArtifactScanStatsWire(),
        records=[],
    )
    scanned_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
    )

    monkeypatch.setattr(
        loader,
        "_artifact_snapshot_for_tui_load",
        lambda **_kwargs: (snapshot, scanned_state),
    )
    monkeypatch.setattr(
        loader,
        "_load_agents_from_all_sources",
        lambda **_kwargs: ([], []),
    )
    result = loader._load_agents_with_load_state()
    assert result.state.running_claims_scanned is True

    # Keeps-displayed-roster short-circuit never scans claims.
    from sase.ace.tui.models._agent_loader_artifact_state import (
        LOCK_BUSY_KEEP_ROSTER_REASON,
    )

    keep_state = AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=False,
        repair_reason=LOCK_BUSY_KEEP_ROSTER_REASON,
    )
    monkeypatch.setattr(
        loader,
        "_artifact_snapshot_for_tui_load",
        lambda **_kwargs: (snapshot, keep_state),
    )
    kept = loader._load_agents_with_load_state()
    assert kept.agents == []
    assert kept.state.running_claims_scanned is False

    # Artifact deltas never scan the RUNNING field.
    monkeypatch.setattr(
        loader,
        "_scan_artifact_dirs_for_loader",
        lambda _dirs, _options=None: snapshot,
    )
    monkeypatch.setattr(
        loader,
        "_update_artifact_index_from_delta",
        lambda _snapshot, **_kwargs: None,
    )
    monkeypatch.setattr(
        loader,
        "_load_agents_from_artifact_snapshot_sources",
        lambda _snapshot, **_kwargs: ([], []),
    )
    monkeypatch.setattr(
        loader,
        "_normalize_loaded_agents",
        lambda agents, _steps, **_kwargs: list(agents),
    )
    monkeypatch.setattr(
        loader,
        "_mark_live_artifact_delta_runners",
        lambda _agents: None,
    )
    _, delta_state = loader.load_artifact_delta_agents(
        ["/tmp/projects/sase/artifacts/ace-run/20261115123045"],
        patch_snapshot=[],
        update_index=False,
    )
    assert delta_state.running_claims_scanned is False


def test_bounded_prefix_shadow_still_loses_to_richer_cache() -> None:
    """Guard: the artifact-wins rule must not weaken the reverse direction."""
    from tests.test_agents_tab_incomplete_merge import (
        _settled_gate_merge_rows,
        _gate_shadow_row,
        _gate_rows,
    )
    from tests._agents_tab_incomplete_merge_helpers import (
        _bounded_prefix_load_state,
    )

    root, cached_gate, _, completed_coder = _settled_gate_merge_rows()
    shadow = _gate_shadow_row()

    rows = _merge_tier1_patch(
        [root, cached_gate, completed_coder],
        [shadow],
        load_state=_bounded_prefix_load_state(),
    )

    published_gates = _gate_rows(rows)
    assert [agent.identity for agent in published_gates] == [cached_gate.identity]
    assert all(agent is not shadow for agent in rows)


def test_filtered_merge_keeps_capacity_recursion_consistent() -> None:
    """A dropped claim placeholder must not shadow capacity rows either."""
    holder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="holder",
        project_file=_PROJECT,
        status="RUNNING",
        start_time=_STARTED,
        raw_suffix="20261115123100",
        artifacts_dir="/tmp/projects/sase/artifacts/ace-run/20261115123100",
        pid=111,
        runner_is_live=True,
    )
    cached = [_workflow_row(), _preclaim_placeholder()]
    snapshot = _incomplete_tier1_snapshot(
        cached,
        load_state=_claim_scanning_state(),
        capacity_agents_with_children=[holder, _preclaim_placeholder(pid=999)],
    )
    from sase.ace.tui.actions.agents._loading_compute import (
        PreparedApplyData,
        merge_incomplete_load_after_complete_history,
    )

    prep = PreparedApplyData(
        filtered_agents=[_workflow_row()],
        has_always_visible=True,
        hidden_count=0,
        hideable_agents=[],
        dismissed_agent_objects=[],
        capacity_agents=[holder],
    )
    merge_incomplete_load_after_complete_history(prep, snapshot)

    assert all(agent.status != "STARTING" for agent in prep.filtered_agents)
    assert holder in prep.capacity_agents
    assert all(not agent.from_running_claim for agent in prep.capacity_agents) or all(
        agent.status != "STARTING" for agent in prep.capacity_agents
    )
