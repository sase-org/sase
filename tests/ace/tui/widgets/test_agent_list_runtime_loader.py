"""Tests for workflow-step runtime metadata loading."""

from __future__ import annotations

import json
from pathlib import Path

from sase.ace.tui.models._loaders._workflow_step_loaders import (
    _load_workflow_agent_steps_for_dir,
)


def test_workflow_step_loader_marks_appears_as_agent_parent(tmp_path: Path) -> None:
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20260425143000"
    timestamp_dir.mkdir(parents=True)
    (timestamp_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": "running",
                "appears_as_agent": True,
            }
        )
    )
    (timestamp_dir / "prompt_step_main.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "step_name": "main",
                "step_type": "agent",
                "status": "in_progress",
            }
        )
    )

    agents, _ = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    assert len(agents) == 1
    assert agents[0].parent_workflow == "run"
    assert agents[0].parent_appears_as_agent is True


def _write_family_root_workflow(
    timestamp_dir: Path,
    *,
    step_status: str,
    plan_approved: bool,
    plan_action: str | None,
    step_name: str = "plan",
) -> None:
    timestamp_dir.mkdir(parents=True)
    (timestamp_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "status": "in_progress",
                "appears_as_agent": True,
            }
        )
    )
    (timestamp_dir / f"prompt_step_{step_name}.json").write_text(
        json.dumps(
            {
                "workflow_name": "run",
                "step_name": step_name,
                "step_type": "agent",
                "status": step_status,
            }
        )
    )
    meta = {
        "name": "sase",
        "plan": True,
        "plan_chain_root": True,
        "agent_family": "sase",
        "agent_family_role": "root",
        "role_suffix": "-plan",
    }
    if plan_approved:
        meta["plan_approved"] = True
    if plan_action is not None:
        meta["plan_action"] = plan_action
    (timestamp_dir / "agent_meta.json").write_text(json.dumps(meta))


def test_workflow_step_loader_marks_stuck_plan_done_when_family_advanced(
    tmp_path: Path,
) -> None:
    """A stuck in_progress plan step flips to DONE under EPIC APPROVED root."""
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20260523143000"
    _write_family_root_workflow(
        timestamp_dir,
        step_status="in_progress",
        plan_approved=True,
        plan_action="epic",
    )

    agents, _ = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    assert len(agents) == 1
    assert agents[0].step_name == "plan"
    assert agents[0].status == "DONE"


def test_workflow_step_loader_marks_stuck_plan_done_for_tale_legend_commit(
    tmp_path: Path,
) -> None:
    """tale / legend / commit all qualify as 'family advanced past plan'."""
    for action in ("tale", "legend", "commit"):
        project_dir = tmp_path / f"demo_{action}"
        timestamp_dir = project_dir / "artifacts" / "ace-run" / "20260523143000"
        _write_family_root_workflow(
            timestamp_dir,
            step_status="in_progress",
            plan_approved=True,
            plan_action=action,
        )

        agents, _ = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

        assert agents[0].status == "DONE", f"action={action}"


def test_workflow_step_loader_keeps_running_plan_without_family_signal(
    tmp_path: Path,
) -> None:
    """No plan_approved flag → plan step keeps its live RUNNING display."""
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20260523143000"
    _write_family_root_workflow(
        timestamp_dir,
        step_status="in_progress",
        plan_approved=False,
        plan_action=None,
    )

    agents, _ = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    assert agents[0].status == "RUNNING"


def test_workflow_step_loader_promotes_waiting_input_plan_under_advanced_family(
    tmp_path: Path,
) -> None:
    """waiting_hitl also qualifies as a non-terminal stuck plan status."""
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20260523143000"
    _write_family_root_workflow(
        timestamp_dir,
        step_status="waiting_hitl",
        plan_approved=True,
        plan_action="epic",
    )

    agents, _ = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    assert agents[0].status == "DONE"


def test_workflow_step_loader_does_not_override_non_plan_step(
    tmp_path: Path,
) -> None:
    """A non-plan step under an advanced family must not be marked DONE."""
    project_dir = tmp_path / "demo"
    timestamp_dir = project_dir / "artifacts" / "ace-run" / "20260523143000"
    _write_family_root_workflow(
        timestamp_dir,
        step_status="in_progress",
        plan_approved=True,
        plan_action="epic",
        step_name="main",
    )

    agents, _ = _load_workflow_agent_steps_for_dir(project_dir, timestamp_dir)

    # main is not the planner phase row — its live status is preserved.
    assert agents[0].status == "RUNNING"
