"""Host-owned epic launch status regressions for plan-family rows."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_loader import (
    _apply_status_overrides,
    load_artifact_delta_agents,
)
from sase.bead.epic_launch import _update_epic_launch_metadata


ROOT_TIMESTAMP = "20260715120000"


def _root(*, status: str = "EPIC APPROVED") -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="a1",
        project_file="/tmp/test.sase",
        status=status,
        start_time=datetime(2026, 7, 15, 12, 0, 0),
        raw_suffix=ROOT_TIMESTAMP,
        role_suffix="--plan",
        agent_name="a1",
        agent_family="a1",
        agent_family_role="root",
        plan_chain_root=True,
        plan_action="epic",
        plan_times=[datetime(2026, 7, 15, 12, 5, 0)],
    )


def _concrete_planner(root: Agent) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        project_file=root.project_file,
        status="DONE",
        start_time=root.start_time,
        raw_suffix=root.raw_suffix,
        parent_workflow="agent-family",
        parent_timestamp=root.raw_suffix,
        step_type="agent",
        role_suffix="--plan",
        agent_name="a1--plan",
        agent_family="a1",
        agent_family_role="plan",
    )


def test_host_owned_epic_metadata_advances_concrete_planner_family() -> None:
    root = _root()
    planner = _concrete_planner(root)

    _apply_status_overrides([root], [planner])

    assert root.status == "EPIC APPROVED"
    assert planner.status == "EPIC APPROVED"

    root.epic_bead_id = "sase-64"
    _apply_status_overrides([root], [planner])

    assert root.status == "EPIC CREATED"
    assert planner.status == "EPIC CREATED"
    assert planner.epic_bead_id == "sase-64"


def test_host_owned_epic_metadata_advances_synthetic_planner_family() -> None:
    root = _root(status="DONE")
    agents = [root]

    _apply_status_overrides(agents)

    planner = next(
        agent for agent in agents if agent.parent_timestamp == ROOT_TIMESTAMP
    )
    assert root.status == "EPIC APPROVED"
    assert planner.status == "EPIC APPROVED"

    root.epic_bead_id = "sase-64"
    _apply_status_overrides(agents)

    assert root.status == "EPIC CREATED"
    assert planner.status == "EPIC CREATED"
    assert planner.epic_bead_id == "sase-64"


def test_epic_bead_id_without_epic_approval_does_not_create_epic_status() -> None:
    root = _root(status="DONE")
    root.plan_action = "approve"
    root.epic_bead_id = "sase-64"
    agents = [root]

    _apply_status_overrides(agents)

    planner = next(
        agent for agent in agents if agent.parent_timestamp == ROOT_TIMESTAMP
    )
    assert root.status == "PLAN APPROVED"
    assert planner.status == "PLAN APPROVED"


def test_host_epic_metadata_reload_crosses_real_artifact_loader_boundary(
    tmp_path: Path,
    monkeypatch,
) -> None:
    sase_home = tmp_path / "sase-home"
    project_dir = sase_home / "projects" / "demo"
    artifacts_dir = project_dir / "artifacts" / "ace-run" / ROOT_TIMESTAMP
    workspace_dir = tmp_path / "workspace"
    artifacts_dir.mkdir(parents=True)
    workspace_dir.mkdir()
    monkeypatch.setenv("SASE_HOME", str(sase_home))

    project_file = project_dir / "demo.sase"
    project_file.write_text(
        f"WORKSPACE_DIR: {workspace_dir}\nRUNNING:\n\nNAME: demo\n",
        encoding="utf-8",
    )
    (artifacts_dir / "workflow_state.json").write_text(
        json.dumps(
            {
                "status": "completed",
                "context": {"cl_name": "demo"},
                "steps": [],
                "current_step_index": 0,
                "workflow_name": "agent-family",
                "appears_as_agent": True,
            }
        ),
        encoding="utf-8",
    )
    (artifacts_dir / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "a1",
                "agent_family": "a1",
                "agent_family_role": "root",
                "plan_chain_root": True,
                "role_suffix": "--plan",
                "plan": True,
                "plan_approved": True,
                "plan_action": "epic",
                "plan_submitted_at": "2026-07-15T12:05:00+00:00",
            }
        ),
        encoding="utf-8",
    )

    before, _ = load_artifact_delta_agents(
        [artifacts_dir],
        patch_snapshot=[],
        update_index=False,
    )
    assert {agent.agent_name: agent.status for agent in before} == {
        "a1": "EPIC APPROVED",
        "a1--plan": "EPIC APPROVED",
    }

    _update_epic_launch_metadata(
        artifacts_dir,
        epic_id="sase-64",
        sdd_plan_path="/plans/202607/epic.md",
    )
    after, _ = load_artifact_delta_agents(
        [artifacts_dir],
        patch_snapshot=[],
        update_index=False,
    )

    assert {agent.agent_name: agent.status for agent in after} == {
        "a1": "EPIC CREATED",
        "a1--plan": "EPIC CREATED",
    }
    assert all(agent.epic_bead_id == "sase-64" for agent in after)
