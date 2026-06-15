"""Tests for workflow prompt-step enrichment from parent metadata."""

from __future__ import annotations

import json
from datetime import datetime

from sase.ace.tui.models._loaders._meta_enrichment import enrich_agent_from_meta
from sase.ace.tui.models.agent import Agent, AgentType


def _workflow_step(step_type: str) -> Agent:
    return Agent(
        agent_type=AgentType.WORKFLOW,
        cl_name=step_type,
        project_file="/tmp/p.sase",
        status="DONE",
        start_time=datetime(2026, 5, 19, 9, 0, 0),
        parent_workflow="agent-family",
        parent_timestamp="20260519090000",
        step_type=step_type,
        step_index=0,
        total_steps=3,
    )


def test_workflow_child_enrichment_derives_planner_identity_only_for_main_agent(
    tmp_path,
) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "ap5",
                "agent_family": "ap5",
                "agent_family_role": "root",
                "plan_chain_root": True,
                "role_suffix": "-plan",
                "model": "gpt-test",
                "llm_provider": "codex",
                "workspace_dir": "/tmp/workspace",
                "plan_submitted_at": "2026-05-19T13:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    planner = _workflow_step("agent")
    bash = _workflow_step("bash")

    enrich_agent_from_meta(planner, str(tmp_path), workflow_child=True)
    enrich_agent_from_meta(bash, str(tmp_path), workflow_child=True)

    assert planner.agent_name == "ap5--plan"
    assert planner.agent_family == "ap5"
    assert planner.agent_family_role == "plan"
    assert planner.role_suffix == "--plan"
    assert planner.plan_chain_root is False

    assert bash.agent_name is None
    assert bash.agent_family is None
    assert bash.agent_family_role is None
    assert bash.role_suffix is None
    assert bash.plan_chain_root is False

    assert planner.model == "gpt-test"
    assert bash.model == "gpt-test"
    assert planner.plan_times
    assert bash.plan_times


def test_workflow_child_enrichment_uses_root_question_suffix(tmp_path) -> None:
    (tmp_path / "agent_meta.json").write_text(
        json.dumps(
            {
                "name": "ap5",
                "agent_family": "ap5",
                "agent_family_role": "root",
                "plan_chain_root": True,
                "role_suffix": "--0",
            }
        ),
        encoding="utf-8",
    )
    question_child = _workflow_step("agent")

    enrich_agent_from_meta(question_child, str(tmp_path), workflow_child=True)

    assert question_child.agent_name == "ap5--0"
    assert question_child.agent_family == "ap5"
    assert question_child.agent_family_role == "q"
    assert question_child.role_suffix == "--0"
