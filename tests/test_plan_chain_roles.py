"""Tests for plan-chain naming and metadata classification."""

import pytest

from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
    canonical_plan_chain_suffix,
    is_plan_chain_artifact_meta,
    plan_chain_agent_name,
    plan_chain_feedback_suffix,
    plan_chain_suffix_from_meta,
)


def test_plan_chain_agent_names_use_canonical_suffixes() -> None:
    assert plan_chain_agent_name("agent", PLAN_CHAIN_PLAN_SUFFIX) == "agent.plan"
    assert plan_chain_agent_name("agent", PLAN_CHAIN_QUESTION_SUFFIX) == "agent.q"
    assert plan_chain_agent_name("agent", plan_chain_feedback_suffix(1)) == "agent.2"
    assert plan_chain_agent_name("agent", PLAN_CHAIN_CODER_SUFFIX) == "agent.code"


def test_coder_suffix_classifies_as_code() -> None:
    assert canonical_plan_chain_suffix(PLAN_CHAIN_CODER_SUFFIX) == ".code"
    assert (
        plan_chain_suffix_from_meta(
            {
                "name": "agent.code",
                "workflow_name": "agent",
            }
        )
        == ".code"
    )
    assert is_plan_chain_artifact_meta({"role_suffix": ".code"})


def test_coder_suffix_is_not_a_supported_alias() -> None:
    assert canonical_plan_chain_suffix(".coder") is None
    assert (
        plan_chain_suffix_from_meta(
            {
                "name": "agent.coder",
                "workflow_name": "agent",
            }
        )
        is None
    )
    assert not is_plan_chain_artifact_meta({"role_suffix": ".coder"})
    with pytest.raises(ValueError):
        plan_chain_agent_name("agent", ".coder")


def test_plan_chain_feedback_suffix_is_one_based() -> None:
    assert plan_chain_feedback_suffix(2) == ".3"
    with pytest.raises(ValueError):
        plan_chain_feedback_suffix(0)


def test_plan_chain_suffix_from_meta_prefers_role_suffix() -> None:
    assert (
        plan_chain_suffix_from_meta(
            {
                "role_suffix": ".code",
                "name": "agent.code",
                "workflow_name": "agent",
            }
        )
        == ".code"
    )
