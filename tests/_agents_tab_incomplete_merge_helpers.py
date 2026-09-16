"""Shared helpers for agents-tab incomplete merge tests."""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path

from sase.ace.tui.actions.agents._loading_compute import (
    PreparedApplyData,
    PreparedApplySelectionInputs,
    PreparedApplySnapshot,
    merge_incomplete_load_after_complete_history,
)
from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent import AgentType
from sase.ace.tui.models.agent_loader import AgentLoadState

_SHELL_FAMILY = "settled-gate"
_ROOT_TS = "20260915090000"
_GATE_TS = "20260915090100"
_CODE_TS = "20260915090200"
_STARTED = datetime(2026, 9, 15, 9, 0, 0)


def _incomplete_tier1_snapshot(
    cached_agents_with_children: Sequence[Agent],
    *,
    artifact_source: str = "artifact_index",
    used_artifact_index: bool = True,
    load_state: AgentLoadState | None = None,
    capacity_agents_with_children: Sequence[Agent] = (),
    deleted_artifact_dirs: frozenset[str] = frozenset(),
) -> PreparedApplySnapshot:
    if load_state is None:
        load_state = AgentLoadState(
            tier="tier1",
            complete_history=False,
            artifact_source=artifact_source,
            used_artifact_index=used_artifact_index,
            deleted_artifact_dirs=deleted_artifact_dirs,
        )

    return PreparedApplySnapshot(
        cached_agents_with_children=list(cached_agents_with_children),
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
        capacity_agents_with_children=list(capacity_agents_with_children),
    )


def _bounded_prefix_load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_index",
        used_artifact_index=True,
        bounded_prefix=True,
        requested_limit=50,
        returned_count=50,
        has_more=True,
    )


def _artifact_delta_load_state() -> AgentLoadState:
    return AgentLoadState(
        tier="tier1",
        complete_history=False,
        artifact_source="artifact_delta",
        used_artifact_index=False,
    )


def _merge_tier1_patch(
    cached: list[Agent],
    incoming: list[Agent],
    *,
    load_state: AgentLoadState | None = None,
) -> list[Agent]:
    prep = PreparedApplyData(
        filtered_agents=incoming,
        has_always_visible=bool(incoming),
        hidden_count=0,
        hideable_agents=list(incoming),
        dismissed_agent_objects=[],
    )
    snapshot = _incomplete_tier1_snapshot(cached, load_state=load_state)

    merge_incomplete_load_after_complete_history(prep, snapshot)
    return prep.filtered_agents


def _settled_gate_merge_rows(
    *,
    cached_type: AgentType = AgentType.RUNNING,
    incoming_type: AgentType = AgentType.WORKFLOW,
) -> tuple[Agent, Agent, Agent, Agent]:
    root = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=_SHELL_FAMILY,
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_STARTED,
        run_start_time=_STARTED,
        raw_suffix=_ROOT_TS,
        role_suffix="--plan",
        agent_name=_SHELL_FAMILY,
        agent_family=_SHELL_FAMILY,
        agent_family_role="root",
        plan_chain_root=True,
        plan_action="tale",
    )
    cached_gate = _gate_row(
        agent_type=cached_type,
        status="TALE",
        gate_state="pending",
        status_bucket="Stopped",
    )
    settled_gate = _gate_row(
        agent_type=incoming_type,
        status="TALE APPROVED",
        gate_state="answered",
        status_bucket="Running",
    )
    completed_coder = Agent(
        agent_type=AgentType.RUNNING,
        cl_name=f"{_SHELL_FAMILY}--code",
        project_file="/tmp/test.sase",
        status="DONE",
        start_time=_STARTED + timedelta(minutes=2),
        run_start_time=_STARTED + timedelta(minutes=2),
        stop_time=_STARTED + timedelta(minutes=3),
        raw_suffix=_CODE_TS,
        parent_timestamp=_ROOT_TS,
        role_suffix="--code",
        agent_name=f"{_SHELL_FAMILY}--code",
        agent_family=_SHELL_FAMILY,
        agent_family_role="code",
    )
    return root, cached_gate, settled_gate, completed_coder


def _gate_row(
    *,
    agent_type: AgentType,
    status: str,
    gate_state: str,
    status_bucket: str,
) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=f"{_SHELL_FAMILY}--gate",
        project_file="/tmp/test.sase",
        status=status,
        status_bucket=status_bucket,
        start_time=_STARTED + timedelta(minutes=1),
        run_start_time=_STARTED + timedelta(minutes=1),
        raw_suffix=_GATE_TS,
        parent_timestamp=_ROOT_TS,
        role_suffix="--gate",
        agent_name=f"{_SHELL_FAMILY}--gate",
        agent_family=_SHELL_FAMILY,
        agent_family_role="gate",
        gate_id="gate-1",
        gate_kind="approval",
        gate_state=gate_state,
        gate_start_status="TALE",
        gate_stop_status="TALE APPROVED",
    )


def _gate_shadow_row(*, agent_type: AgentType = AgentType.WORKFLOW) -> Agent:
    return Agent(
        agent_type=agent_type,
        cl_name=f"{_SHELL_FAMILY}--gate",
        project_file="/tmp/test.sase",
        status="RUNNING",
        start_time=_STARTED + timedelta(minutes=1),
        run_start_time=_STARTED + timedelta(minutes=1),
        raw_suffix=_GATE_TS,
        parent_timestamp=_ROOT_TS,
        role_suffix="--gate",
        agent_name=f"{_SHELL_FAMILY}--gate",
        agent_family=_SHELL_FAMILY,
        agent_family_role="gate",
    )


def _gate_rows(rows: Sequence[Agent]) -> list[Agent]:
    return [agent for agent in rows if agent.raw_suffix == _GATE_TS]


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
