"""Loader tests for gate-shell ownership of plan decision statuses."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from sase.ace.tui.models.agent import Agent
from sase.ace.tui.models.agent_loader import _apply_status_overrides, load_all_agents
from sase.core.paths import sase_projects_dir

DEAD_PID = 99_999_999
_PROJECT = "gate-decision-owner"
_FAMILY = "alpha"
_ROOT_TS = "20260812090000"
_GATE_TS = "20260812090500"
_CODE_TS = "20260812091000"
_GATE_ID = "gate-owner-123"
_PLAN_SUBMITTED_AT = "2026-08-12T09:03:00Z"


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
        spec.write_text("# gate decision owner\n", encoding="utf-8")
    return str(spec)


def _write_root() -> Path:
    artifact_dir = _artifact_dir(_ROOT_TS)
    project_file = _project_file()
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": _FAMILY,
            "agent_family": _FAMILY,
            "agent_family_role": "root",
            "role_suffix": "--plan",
            "plan_chain_root": True,
            "plan": True,
            "plan_submitted_at": _PLAN_SUBMITTED_AT,
            "plan_approved": True,
            "plan_action": "tale",
            "gate_id": _GATE_ID,
        },
    )
    _write_json(
        artifact_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "status": "completed",
            "current_step_index": 0,
            "steps": [],
            "context": {"cl_name": _FAMILY},
            "appears_as_agent": True,
        },
    )
    _write_json(
        artifact_dir / "prompt_step_main.json",
        {
            "workflow_name": "ace-run",
            "step_name": "plan",
            "step_type": "agent",
            "status": "completed",
            "parent_step_index": None,
            "artifacts_dir": str(artifact_dir),
        },
    )
    _write_json(
        artifact_dir / "done.json",
        {
            "outcome": "completed",
            "cl_name": _FAMILY,
            "name": _FAMILY,
            "project_file": project_file,
        },
    )
    return artifact_dir


def _write_gate_member(*, state: str) -> Path:
    artifact_dir = _artifact_dir(_GATE_TS)
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": f"{_FAMILY}--gate",
            "agent_family": _FAMILY,
            "agent_family_role": "gate",
            "role_suffix": "--gate",
            "shell_kind": "gate",
            "parent_timestamp": _ROOT_TS,
            "gate_id": _GATE_ID,
            "gate_kind": "approval",
            "gate_state": state,
            "gate_start_status": "TALE",
            "gate_stop_status": "TALE APPROVED",
        },
    )
    _write_json(
        artifact_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "status": "running",
            "current_step_index": 0,
            "steps": [],
            "context": {"cl_name": f"{_FAMILY}--gate"},
            "appears_as_agent": True,
            "pid": DEAD_PID,
        },
    )
    if state == "answered":
        _write_json(
            artifact_dir / "done.json",
            {
                "outcome": "gated",
                "cl_name": f"{_FAMILY}--gate",
                "name": f"{_FAMILY}--gate",
                "project_file": _project_file(),
                "gate_id": _GATE_ID,
                "gate_kind": "approval",
                "gate_state": "answered",
                "status_label": "TALE APPROVED",
            },
        )
    return artifact_dir


def _write_coder_member() -> Path:
    artifact_dir = _artifact_dir(_CODE_TS)
    _write_json(
        artifact_dir / "agent_meta.json",
        {
            "name": f"{_FAMILY}--code",
            "agent_family": _FAMILY,
            "agent_family_role": "code",
            "role_suffix": "--code",
            "parent_timestamp": _ROOT_TS,
        },
    )
    _write_json(
        artifact_dir / "workflow_state.json",
        {
            "workflow_name": "ace-run",
            "status": "running",
            "current_step_index": 0,
            "steps": [],
            "context": {"cl_name": f"{_FAMILY}--code"},
            "appears_as_agent": True,
            "pid": os.getpid(),
        },
    )
    return artifact_dir


def _load() -> list[Agent]:
    _project_file()
    return load_all_agents(patch_snapshot=[])


def _only_planner_step(rows: list[Agent]) -> Agent:
    planners = [
        row
        for row in rows
        if row.is_workflow_step_child and row.agent_family_role == "plan"
    ]
    assert len(planners) == 1, [(row.cl_name, row.status) for row in rows]
    return planners[0]


def _only_gate(rows: list[Agent]) -> Agent:
    gates = [row for row in rows if row.is_gate]
    assert len(gates) == 1, [(row.cl_name, row.status) for row in rows]
    return gates[0]


def _only_root(rows: list[Agent]) -> Agent:
    roots = [row for row in rows if row.is_family_root_entry]
    assert len(roots) == 1, [(row.cl_name, row.status) for row in rows]
    return roots[0]


def _only_coder(rows: list[Agent]) -> Agent:
    coders = [row for row in rows if row.agent_family_role == "code"]
    assert len(coders) == 1, [(row.cl_name, row.status) for row in rows]
    return coders[0]


def test_settled_gate_owns_decision_status_from_artifact_markers() -> None:
    _write_root()
    _write_gate_member(state="answered")

    rows = _load()
    planner = _only_planner_step(rows)
    gate = _only_gate(rows)
    root = _only_root(rows)

    _apply_status_overrides([root, gate], [planner])

    assert planner.status == "DONE"
    assert gate.status == "TALE APPROVED"
    assert gate.gate_state == "answered"
    assert root.status == "TALE APPROVED"


def test_pending_gate_owns_transient_decision_status_from_artifact_markers() -> None:
    _write_root()
    _write_gate_member(state="pending")

    rows = _load()
    planner = _only_planner_step(rows)
    gate = _only_gate(rows)
    root = _only_root(rows)

    assert planner.status == "DONE"
    assert gate.status == "TALE"
    assert root.status == "TALE"


def test_coder_after_settled_gate_moves_container_past_gate_status() -> None:
    _write_root()
    _write_gate_member(state="answered")
    _write_coder_member()

    rows = _load()
    planner = _only_planner_step(rows)
    gate = _only_gate(rows)
    root = _only_root(rows)
    coder = _only_coder(rows)

    assert planner.status == "DONE"
    assert gate.status == "TALE APPROVED"
    assert coder.status == "WORKING TALE"
    assert root.status == "WORKING TALE"
