"""Shared builders for tribe display tests."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.models.agent_tribe_summary import (
    AgentTribeSummarySnapshot,
    build_agent_tribe_summary_snapshot,
)

NOW = datetime(2026, 7, 18, 15, 0, 0)


def make_tribe_agent(
    name: str,
    status: str,
    *,
    suffix: str,
    family: str | None = None,
    role: str | None = None,
    parent: str | None = None,
) -> Agent:
    return Agent(
        agent_type=AgentType.RUNNING,
        cl_name=name,
        project_file="/tmp/demo.sase",
        status=status,
        start_time=datetime(2026, 7, 18, 14, 0, 0),
        run_start_time=datetime(2026, 7, 18, 14, 0, 0),
        stop_time=NOW if status == "FAILED" else None,
        raw_suffix=suffix,
        agent_name=name,
        agent_family=family,
        agent_family_role="root" if role == "plan" else role,
        role_suffix=f"--{role}" if role else None,
        plan_chain_root=role == "plan",
        parent_timestamp=parent,
        model="gpt-5",
    )


def make_tribe_snapshot() -> AgentTribeSummarySnapshot:
    root = make_tribe_agent(
        "build--plan",
        "RUNNING",
        suffix="root",
        family="build",
        role="plan",
    )
    child = make_tribe_agent(
        "build--code",
        "WAITING",
        suffix="child",
        family="build",
        role="code",
        parent="root",
    )
    child.activity = "writing tests"
    child.workspace_num = 8
    root.followup_agents = [child]
    failed = make_tribe_agent("failed", "FAILED", suffix="failed")
    failed.error_message = "Build failed\nSecond error detail"
    failed.error_traceback = "Traceback line one\nValueError: broken"
    failed.output_variables = {
        "report": {
            "findings": [{"file": "src/a.py", "severity": "high"}],
            "passed": True,
            "ratio": 2.5,
            "summary": "summary line",
        }
    }
    failed.step_output = {"meta_release_notes": "ready\nrelease detail"}
    return build_agent_tribe_summary_snapshot(
        "epic",
        [root, child, failed],
        panel_collapsed=True,
        marked_ids={child.identity},
        now=NOW,
    )
