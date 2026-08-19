"""Agents-tab left-side titles appear only on bash/python steps and roots."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent import Agent, AgentType
from sase.ace.tui.widgets._agent_list_rendering import format_agent_option
from tests.ace.tui.widgets._agent_display_helpers import make_agent


def test_family_planner_agent_step_omits_main_title() -> None:
    agent = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="main",
        status="TALE APPROVED",
        parent_workflow="ace-run",
        parent_timestamp="20260819080000",
        step_name="main",
        step_type="agent",
        agent_name="08b--plan",
        llm_provider="claude",
    )

    left, _, _ = format_agent_option(agent, 0, is_selected=False)

    assert "main" not in left.plain
    assert "(TALE APPROVED)" in left.plain
    assert "08b--plan" in left.plain


def test_family_coder_project_child_omits_project_display_name() -> None:
    agent = make_agent(
        cl_name="sase",
        project_file="/workspace/sase/sase.sase",
        project_display_name="sase",
        status="RUNNING",
        parent_timestamp="20260819080000",
        agent_name="08b--code",
        agent_family="08b",
        agent_family_role="code",
        llm_provider="codex",
    )

    left, _, _ = format_agent_option(agent, 0, is_selected=False)

    assert "sase" not in left.plain
    assert "(RUNNING)" in left.plain
    assert "08b--code" in left.plain


def test_monitor_row_uses_glyph_without_label_or_command() -> None:
    started = datetime(2026, 8, 12, 9, 0, 0)
    agent = Agent(
        agent_type=AgentType.RUNNING,
        cl_name="monitor-row",
        project_file="/tmp/monitor.sase",
        status="TESTING",
        start_time=started,
        raw_suffix="20260812090000",
        parent_timestamp="20260812085900",
        agent_name="08b--mon",
        agent_family="08b",
        agent_family_role="monitor",
        role_suffix="--mon",
        monitor_id="m123",
        monitor_state="running",
        monitor_label="research-swarm priority check",
        monitor_command="just check-full",
        monitor_start_status="TESTING",
        monitor_stop_status="TESTED",
    )

    left, _, _ = format_agent_option(agent, 0, is_selected=False)

    assert "⚙" in left.plain
    assert "research-swarm priority check" not in left.plain
    assert "just check-full" not in left.plain
    assert "08b--mon" in left.plain


def test_bash_and_python_children_keep_step_name_and_glyph() -> None:
    bash = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="setup",
        parent_workflow="ace-run",
        parent_timestamp="20260819080000",
        step_name="setup",
        step_type="bash",
        status="DONE",
        llm_provider=None,
    )
    python = make_agent(
        agent_type=AgentType.WORKFLOW,
        cl_name="prepare",
        parent_workflow="ace-run",
        parent_timestamp="20260819080000",
        step_name="prepare",
        step_type="python",
        status="DONE",
        llm_provider=None,
    )

    bash_left, _, _ = format_agent_option(bash, 0, is_selected=False)
    python_left, _, _ = format_agent_option(python, 1, is_selected=False)

    assert "❯ setup (DONE)" in bash_left.plain
    assert "❯ prepare (DONE)" in python_left.plain


def test_family_container_and_standalone_root_keep_titles() -> None:
    root = make_agent(
        cl_name="08b",
        agent_name="08b--0",
        agent_family="08b",
        agent_family_role="root",
        plan_chain_root=True,
        llm_provider=None,
    )
    member = make_agent(
        cl_name="sase",
        project_file="/workspace/sase/sase.sase",
        parent_timestamp="ts",
        agent_name="08b--code",
        agent_family="08b",
        llm_provider=None,
    )
    root.followup_agents = [member]
    standalone = make_agent(
        cl_name="sase",
        project_file="/workspace/sase/sase.sase",
        project_display_name="sase",
        llm_provider=None,
    )

    family_left, _, _ = format_agent_option(root, 0, is_selected=False)
    standalone_left, _, _ = format_agent_option(standalone, 1, is_selected=False)

    assert root.is_family_container_row
    assert "08b" in family_left.plain
    assert standalone.display_name == "sase"
    assert "sase" in standalone_left.plain


def test_title_less_child_separates_status_parenthesis_from_glyph() -> None:
    agent = make_agent(
        cl_name="sase",
        project_file="/workspace/sase/sase.sase",
        parent_timestamp="20260819080000",
        agent_name="08b--code",
        llm_provider="codex",
    )

    left, _, _ = format_agent_option(agent, 0, is_selected=False)

    assert "  └─ 🤖 (RUNNING)" in left.plain
    assert "🤖(RUNNING)" not in left.plain
