"""Loader tests: a pending gate shell remains visible with a dead pid.

Coverage starts from artifact markers and calls the public loader. The
claim-only counterpart is
``test_load_agents_from_running_field_holds_pending_gate_claim``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest

from sase.ace.tui.models._agent_loader_normalization import normalize_loaded_agents
from sase.ace.tui.models._agent_clan import sase_agent_status_counts
from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_family_members import (
    agent_row_is_in_flight,
    row_is_family_shell,
    shell_lane_counts,
)
from sase.ace.tui.models.agent_groups import GroupingMode, grouping_keys_for_agents
from sase.ace.tui.models.agent_loader import load_all_agents
from sase.ace.tui.widgets._agent_list_render_agent import format_agent_option
from sase.ace.tui.widgets.prompt_panel._agent_gate_section import (
    GATE_PHASE_LABEL,
    build_gate_section,
)
from sase.core.paths import sase_projects_dir
from sase.gate_shell.state import GATE_GLYPH
from sase.monitor.claims import MONITOR_WORKSPACE_CLAIM_WORKFLOW
from sase.running_field import WorkspaceClaim

DEAD_PID = 99_999_999
_PROJECT = "demo"
_FAMILY = "alpha"
_ROOT_TS = "20260812090000"
_MEMBER_TS = "20260812090500"


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _artifact_dir(timestamp: str) -> Path:
    path = (
        sase_projects_dir()
        / _PROJECT
        / "artifacts"
        / "ace-run"
        / timestamp[:6]
        / timestamp[6:8]
        / timestamp
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


def _project_file() -> str:
    project_dir = sase_projects_dir() / _PROJECT
    project_dir.mkdir(parents=True, exist_ok=True)
    spec = project_dir / f"{_PROJECT}.sase"
    if not spec.exists():
        spec.write_text("# demo\n", encoding="utf-8")
    return str(spec)


def _write_root(*, outcome: str = "completed") -> Path:
    artifact_dir = _artifact_dir(_ROOT_TS)
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": _FAMILY,
            "agent_family": _FAMILY,
            "agent_family_role": "root",
            "role_suffix": "-plan",
            "plan_chain_root": True,
            "plan": True,
        },
    )
    _write_json(
        artifact_dir / "done.json",
        {
            "outcome": outcome,
            "cl_name": _FAMILY,
            "name": _FAMILY,
            "project_file": _project_file(),
        },
    )
    return artifact_dir


def _write_gate_member(
    *,
    gate_kind: str,
    start_status: str,
    stop_status: str,
    gate_state: str = "pending",
    pid: int | None = DEAD_PID,
    done: dict[str, Any] | None = None,
) -> Path:
    artifact_dir = _artifact_dir(_MEMBER_TS)
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": f"{_FAMILY}--gate",
            "agent_family": _FAMILY,
            "agent_family_role": "gate",
            "role_suffix": "--gate",
            "parent_timestamp": _ROOT_TS,
            "shell_kind": "gate",
            "gate_id": "g123",
            "gate_kind": gate_kind,
            "gate_state": gate_state,
            "gate_start_status": start_status,
            "gate_stop_status": stop_status,
            "pid": None,
        },
    )
    state: dict[str, Any] = {
        "workflow_name": "run",
        "status": "running",
        "current_step_index": 0,
        "steps": [],
        "context": {"cl_name": f"{_FAMILY}--gate"},
        "appears_as_agent": True,
        "pid": pid,
    }
    _write_json(artifact_dir / "workflow_state.json", state)
    if done is not None:
        _write_json(artifact_dir / "done.json", done)
    return artifact_dir


def _load() -> list[Agent]:
    _project_file()
    return load_all_agents(patch_snapshot=[])


def _root_and_gate(agents: list[Agent]) -> tuple[Agent, Agent]:
    gates = [agent for agent in agents if agent.is_gate]
    roots = [agent for agent in agents if agent.is_family_root_entry]
    assert len(gates) == 1, [agent.cl_name for agent in agents]
    assert len(roots) == 1, [agent.cl_name for agent in agents]
    return roots[0], gates[0]


@pytest.mark.parametrize(
    ("gate_kind", "start_status", "stop_status"),
    [
        ("approval", "EPIC", "EPIC APPROVED"),
        ("question", "QUESTION", "ANSWERED"),
        ("custom", "APPROVE", "APPROVED"),
    ],
)
def test_pending_gate_with_dead_pid_yields_gate_row(
    gate_kind: str,
    start_status: str,
    stop_status: str,
) -> None:
    """A pending gate member with a dead workflow pid still produces a row."""
    _write_root()
    _write_gate_member(
        gate_kind=gate_kind,
        start_status=start_status,
        stop_status=stop_status,
        pid=DEAD_PID,
    )

    agents = _load()
    root, gate = _root_and_gate(agents)

    assert gate.status == start_status
    assert gate.gate_state == "pending"
    assert gate.status_bucket == "Stopped"
    assert gate.error_message is None
    assert gate.output_path is None
    assert agent_row_is_in_flight(gate) is False
    assert root.status == start_status
    assert root.gate_state == "pending"
    lanes = shell_lane_counts(root)
    assert lanes.gate.running == 1
    assert lanes.gate.settled == 0
    assert lanes.gate.failed == 0

    counts = sase_agent_status_counts(agents, ())
    assert counts.stopped >= 1
    assert counts.running == 0

    keys = grouping_keys_for_agents(agents, GroupingMode.BY_STATUS)
    root_key = next(
        key for agent, key in zip(agents, keys, strict=True) if agent is root
    )
    assert root_key.project == "Stopped"

    left, _, _ = format_agent_option(root, 0, is_selected=False)
    assert f"{GATE_GLYPH}1" in left.plain
    section = "".join(
        part.plain if hasattr(part, "plain") else str(part)
        for part in build_gate_section(gate)
    )
    assert GATE_PHASE_LABEL in section


def test_pending_gate_without_pid_is_visible() -> None:
    _write_root()
    _write_gate_member(
        gate_kind="approval",
        start_status="EPIC",
        stop_status="EPIC APPROVED",
        pid=None,
    )

    _root, gate = _root_and_gate(_load())
    assert gate.status == "EPIC"
    assert gate.gate_state == "pending"


def test_settled_gate_yields_exactly_one_row() -> None:
    _write_root()
    _write_gate_member(
        gate_kind="approval",
        start_status="TALE",
        stop_status="TALE APPROVED",
        gate_state="answered",
        pid=DEAD_PID,
        done={
            "outcome": "gated",
            "cl_name": f"{_FAMILY}--gate",
            "name": f"{_FAMILY}--gate",
            "project_file": _project_file(),
            "gate_id": "g123",
            "gate_state": "answered",
            "status_label": "TALE APPROVED",
        },
    )

    agents = _load()
    _root, gate = _root_and_gate(agents)
    assert gate.status == "TALE APPROVED"
    assert gate.gate_state == "answered"
    assert sum(1 for agent in agents if agent.is_gate) == 1


def test_running_monitor_with_dead_workflow_pid_merges_to_one_live_row() -> None:
    """A running monitor's claim and workflow row collapse to one live pid."""
    live_pid = os.getpid()
    _write_root()
    artifact_dir = _artifact_dir(_MEMBER_TS)
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": f"{_FAMILY}--mon",
            "agent_family": _FAMILY,
            "agent_family_role": "monitor",
            "role_suffix": "--mon",
            "parent_timestamp": _ROOT_TS,
            "shell_kind": "proc",
            "monitor_id": "m123",
            "monitor_state": "running",
            "monitor_start_status": "MONITORING",
            "monitor_stop_status": "MONITORED",
            "pid": None,
        },
    )
    _write_json(
        artifact_dir / "workflow_state.json",
        {
            "workflow_name": "run",
            "status": "running",
            "current_step_index": 0,
            "steps": [],
            "context": {"cl_name": f"{_FAMILY}--mon"},
            "appears_as_agent": True,
            "pid": DEAD_PID,
        },
    )
    spec = Path(_project_file())
    spec.write_text(
        "# demo\nRUNNING:\n"
        + WorkspaceClaim(
            workspace_num=3,
            workflow=MONITOR_WORKSPACE_CLAIM_WORKFLOW,
            cl_name=f"{_FAMILY}--mon",
            pid=live_pid,
            artifacts_timestamp=_MEMBER_TS,
        ).to_line()
        + "\n",
        encoding="utf-8",
    )

    agents = load_all_agents(patch_snapshot=[])
    monitors = [agent for agent in agents if agent.is_monitor]
    assert len(monitors) == 1
    assert monitors[0].pid == live_pid


def test_normalization_keeps_family_shell_rows_keyed_on_state_not_pid() -> None:
    """No normalization step drops a family-shell row because its pid is dead."""
    gate = Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=f"{_FAMILY}--gate",
        project_file="/tmp/demo.sase",
        status="EPIC",
        start_time=None,
        pid=DEAD_PID,
        agent_family_role="gate",
        gate_id="g123",
        gate_state="pending",
        appears_as_agent=True,
    )
    stale_agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="orphan",
        project_file="/tmp/demo.sase",
        status="RUNNING",
        start_time=None,
        pid=DEAD_PID,
    )
    assert row_is_family_shell(gate) is True
    assert row_is_family_shell(stale_agent) is False

    kept = normalize_loaded_agents(
        [gate, stale_agent],
        [],
        is_process_running=lambda _pid: False,
    )
    assert [agent.cl_name for agent in kept] == [f"{_FAMILY}--gate"]
