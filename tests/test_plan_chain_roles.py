"""Tests for plan-chain naming and metadata classification."""

import pytest

from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
    agent_family_base,
    agent_family_phase_name,
    agent_family_role_for_suffix,
    canonical_plan_chain_suffix,
    is_agent_family_member,
    is_plan_chain_artifact_meta,
    plan_chain_agent_name,
    plan_chain_feedback_suffix,
    _plan_chain_suffix_from_meta,
)


def test_plan_chain_agent_names_use_canonical_suffixes() -> None:
    assert plan_chain_agent_name("agent", PLAN_CHAIN_PLAN_SUFFIX) == "agent-plan"
    assert plan_chain_agent_name("agent", PLAN_CHAIN_QUESTION_SUFFIX) == "agent-q"
    assert plan_chain_agent_name("agent", plan_chain_feedback_suffix(1)) == "agent-2"
    assert plan_chain_agent_name("agent", PLAN_CHAIN_CODER_SUFFIX) == "agent-code"


def test_agent_family_role_for_suffix_accepts_new_and_legacy_suffixes() -> None:
    assert agent_family_role_for_suffix("-plan") == "plan"
    assert agent_family_role_for_suffix(".q") == "q"
    assert agent_family_role_for_suffix("-2") == "feedback"
    assert agent_family_role_for_suffix(".code") == "code"
    assert agent_family_role_for_suffix(".unknown") is None


def test_coder_suffix_classifies_as_code() -> None:
    assert canonical_plan_chain_suffix(PLAN_CHAIN_CODER_SUFFIX) == "-code"
    assert (
        _plan_chain_suffix_from_meta(
            {
                "name": "agent.code",
                "workflow_name": "agent",
            }
        )
        == "-code"
    )
    assert is_plan_chain_artifact_meta({"role_suffix": ".code"})


def test_coder_suffix_is_not_a_supported_alias() -> None:
    assert canonical_plan_chain_suffix(".coder") is None
    assert (
        _plan_chain_suffix_from_meta(
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
    assert plan_chain_feedback_suffix(2) == "-3"
    with pytest.raises(ValueError):
        plan_chain_feedback_suffix(0)


def test_plan_chain_suffix_from_meta_prefers_role_suffix() -> None:
    assert (
        _plan_chain_suffix_from_meta(
            {
                "role_suffix": ".code",
                "name": "agent.code",
                "workflow_name": "agent",
            }
        )
        == "-code"
    )


def test_legacy_suffixes_canonicalize_to_hyphen_suffixes() -> None:
    assert canonical_plan_chain_suffix(".plan") == "-plan"
    assert canonical_plan_chain_suffix(".q") == "-q"
    assert canonical_plan_chain_suffix(".code") == "-code"
    assert canonical_plan_chain_suffix(".2") == "-2"


def test_agent_family_helpers_parse_only_known_suffixes() -> None:
    assert agent_family_phase_name("agent", ".plan") == "agent-plan"
    assert agent_family_base("agent-code") == "agent"
    assert is_agent_family_member("agent-2")

    assert agent_family_base("sase-3r") is None
    assert not is_agent_family_member("historical-name")
