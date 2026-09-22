"""Tests for shared process-boundary environment hygiene."""

from sase.agent.env_hygiene import (
    scrub_agent_identity_env,
    scrub_chop_context_env,
    scrub_executor_ownership_env,
)
from sase.agent.launch_spawn import _remove_inherited_agent_identity_env
from sase.agent.launch_spawn import _remove_inherited_executor_ownership_env
from sase.agent.launch_spawn import _remove_inherited_sase_plan_env


def test_scrub_agent_identity_env_removes_complete_identity_family() -> None:
    env = {
        "SASE_AGENT": "1",
        "SASE_AGENT_NAME": "worker",
        "SASE_AGENT_PLANNED_NAME": "worker",
        "SASE_AGENT_AUTO_APPROVE": "1",
        "SASE_AGENTISH": "keep",
        "SASE_CHOP_NAME": "keep",
        "OTHER": "keep",
    }

    scrub_agent_identity_env(env)

    assert env == {
        "SASE_AGENTISH": "keep",
        "SASE_CHOP_NAME": "keep",
        "OTHER": "keep",
    }


def test_scrub_chop_context_env_removes_only_chop_family() -> None:
    env = {
        "SASE_CHOP_NAME": "workflow_checks",
        "SASE_CHOP_RUN_ID": "run-1",
        "SASE_JOB_NAME": "workflow_checks",
        "SASE_JOB_RUN_ID": "run-1",
        "SASE_CHOPPER": "keep",
        "SASE_AGENT_NAME": "keep",
    }

    scrub_chop_context_env(env)

    assert env == {
        "SASE_CHOPPER": "keep",
        "SASE_AGENT_NAME": "keep",
    }


def test_followup_spawn_keeps_bead_association_env() -> None:
    """Plan-family follow-ups retain the phase/epic attribution variables."""
    env = {
        "SASE_AGENT": "1",
        "SASE_AGENT_NAME": "sase-7z.5--plan",
        "SASE_PHASE_BEAD_ID": "sase-7z.5",
        "SASE_EPIC_BEAD_ID": "sase-7z",
    }

    _remove_inherited_agent_identity_env(env)

    assert env == {
        "SASE_PHASE_BEAD_ID": "sase-7z.5",
        "SASE_EPIC_BEAD_ID": "sase-7z",
    }


def test_scrub_executor_ownership_env_removes_tool_monitor_proc() -> None:
    env = {
        "SASE_TOOL_RUN_ID": "run-1",
        "SASE_TOOL_NAME": "check",
        "SASE_TOOL_PROJECT_ROOT": "/repo",
        "SASE_TOOL_RUN_AGENT": "starter",
        "SASE_MONITOR_ID": "mon-1",
        "SASE_MONITOR_ARTIFACTS_DIR": "/artifacts",
        "SASE_PROC_ID": "proc-1",
        "SASE_PROC_LOG_PATH": "/tmp/proc.log",
        "SASE_AGENT": "keep",
        "SASE_AGENT_NAME": "keep",
        "OTHER": "keep",
    }

    scrub_executor_ownership_env(env)

    assert env == {
        "SASE_AGENT": "keep",
        "SASE_AGENT_NAME": "keep",
        "OTHER": "keep",
    }


def test_launch_spawn_drops_inherited_executor_ownership_env() -> None:
    """A spawned agent is a new ownership root (fake agent launch)."""
    env = {
        "SASE_TOOL_RUN_ID": "run-1",
        "SASE_TOOL_NAME": "check",
        "SASE_MONITOR_ID": "mon-1",
        "SASE_MONITOR_ARTIFACTS_DIR": "/artifacts",
        "SASE_PROC_ID": "proc-1",
        "SASE_AGENT_NAME": "parent-agent",
        "OTHER": "keep",
    }

    _remove_inherited_executor_ownership_env(env)

    assert env == {"SASE_AGENT_NAME": "parent-agent", "OTHER": "keep"}


def test_launch_spawn_drops_ambient_sase_plan_env() -> None:
    env = {
        "SASE_PLAN": "sdd/plans/202607/done.md",
        "SASE_PLANNER": "keep",
        "OTHER": "keep",
    }

    _remove_inherited_sase_plan_env(env)

    assert env == {
        "SASE_PLANNER": "keep",
        "OTHER": "keep",
    }
