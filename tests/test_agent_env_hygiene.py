"""Tests for shared process-boundary environment hygiene."""

from sase.agent.env_hygiene import (
    scrub_agent_identity_env,
    scrub_chop_context_env,
)


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
        "SASE_CHOPPER": "keep",
        "SASE_AGENT_NAME": "keep",
    }

    scrub_chop_context_env(env)

    assert env == {
        "SASE_CHOPPER": "keep",
        "SASE_AGENT_NAME": "keep",
    }
