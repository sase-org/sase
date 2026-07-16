"""Tests for plan-chain naming and metadata classification."""

import pytest

from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    PLAN_CHAIN_QUESTION_SUFFIX,
    agent_family_base,
    agent_family_phase_name,
    agent_family_role_for_suffix,
    agent_family_suffix_token,
    canonical_plan_chain_suffix,
    is_agent_family_member,
    is_plan_feedback_suffix,
    is_root_question_suffix,
    is_plan_chain_artifact_meta,
    plan_chain_agent_name,
    plan_chain_feedback_round,
    question_followup_suffix_template,
    _parse_plan_chain_suffix,
    _plan_chain_feedback_suffix,
    _plan_chain_suffix_from_meta,
)


def test_plan_chain_agent_names_use_canonical_suffixes() -> None:
    assert plan_chain_agent_name("agent", PLAN_CHAIN_PLAN_SUFFIX) == "agent--plan"
    assert plan_chain_agent_name("agent", PLAN_CHAIN_QUESTION_SUFFIX) == "agent--q"
    assert plan_chain_agent_name("agent", _plan_chain_feedback_suffix(1)) == "agent--2"
    assert plan_chain_agent_name("agent", PLAN_CHAIN_CODER_SUFFIX) == "agent--code"


def test_agent_family_role_for_suffix_accepts_new_and_legacy_suffixes() -> None:
    assert agent_family_role_for_suffix("--plan") == "plan"
    assert agent_family_role_for_suffix("-plan") == "plan"
    assert agent_family_role_for_suffix(".q") == "q"
    assert agent_family_role_for_suffix("--2") == "feedback"
    assert agent_family_role_for_suffix("--2", agent_family_role="q") == "q"
    assert agent_family_role_for_suffix("--2", agent_family_role="phase") == "phase"
    assert agent_family_role_for_suffix("-2") == "feedback"
    assert agent_family_role_for_suffix(".code") == "code"
    assert agent_family_role_for_suffix(".unknown") is None


def test_agent_family_suffix_token_strips_known_separators() -> None:
    assert agent_family_suffix_token("--bar") == "bar"
    assert agent_family_suffix_token("--0") == "0"
    assert agent_family_suffix_token("--reviewer") == "reviewer"
    assert agent_family_suffix_token(".xyz") == "xyz"
    assert agent_family_suffix_token("-2") == "2"
    assert agent_family_suffix_token(None) is None
    assert agent_family_suffix_token("") is None
    assert agent_family_suffix_token("--") is None


def test_new_plan_feedback_suffixes_classify_as_feedback() -> None:
    assert canonical_plan_chain_suffix("--plan-0") == "--plan-0"
    assert agent_family_role_for_suffix("--plan-0") == "feedback"
    assert is_plan_feedback_suffix("--plan-0")
    assert plan_chain_feedback_round("--plan-0") == 2
    assert plan_chain_feedback_round("--plan-1") == 3
    assert plan_chain_agent_name("agent", "--plan-0") == "agent--plan-0"


def test_root_question_suffixes_are_role_aware() -> None:
    assert agent_family_role_for_suffix("--0") == "q"
    assert agent_family_role_for_suffix("--1") == "q"
    assert agent_family_role_for_suffix("--2") == "feedback"
    assert agent_family_role_for_suffix("--2", agent_family_role="q") == "q"
    assert is_root_question_suffix("--2", agent_family_role="q")
    assert not is_plan_feedback_suffix("--2", agent_family_role="q")


def test_phase_question_suffixes_keep_underlying_role() -> None:
    code = _parse_plan_chain_suffix("--code-0")
    assert code is not None
    assert code.role == "code"
    assert code.kind == "phase_question"
    assert code.parent_suffix == "--code"

    feedback = _parse_plan_chain_suffix("--plan-0-0")
    assert feedback is not None
    assert feedback.role == "feedback"
    assert feedback.kind == "phase_question"
    assert feedback.parent_suffix == "--plan-0"


def test_question_followup_suffix_templates() -> None:
    assert question_followup_suffix_template("--0") == "--@"
    assert question_followup_suffix_template("--2", agent_family_role="q") == "--@"
    assert question_followup_suffix_template("--code") == "--code-@"
    assert question_followup_suffix_template("--code-0") == "--code-@"
    assert question_followup_suffix_template("--plan-0") == "--plan-0-@"


def test_coder_suffix_classifies_as_code() -> None:
    assert canonical_plan_chain_suffix(PLAN_CHAIN_CODER_SUFFIX) == "--code"
    assert (
        _plan_chain_suffix_from_meta(
            {
                "name": "agent.code",
                "workflow_name": "agent",
            }
        )
        == "--code"
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
    assert _plan_chain_feedback_suffix(2) == "--3"
    with pytest.raises(ValueError):
        _plan_chain_feedback_suffix(0)


def test_plan_chain_suffix_from_meta_prefers_role_suffix() -> None:
    assert (
        _plan_chain_suffix_from_meta(
            {
                "role_suffix": ".code",
                "name": "agent.code",
                "workflow_name": "agent",
            }
        )
        == "--code"
    )


def test_legacy_suffixes_canonicalize_to_double_dash_suffixes() -> None:
    assert canonical_plan_chain_suffix(".plan") == "--plan"
    assert canonical_plan_chain_suffix("-plan") == "--plan"
    assert canonical_plan_chain_suffix(".q") == "--q"
    assert canonical_plan_chain_suffix("-q") == "--q"
    assert canonical_plan_chain_suffix(".code") == "--code"
    assert canonical_plan_chain_suffix("-code") == "--code"
    assert canonical_plan_chain_suffix(".2") == "--2"
    assert canonical_plan_chain_suffix("-2") == "--2"
    assert plan_chain_feedback_round("--10") == 10
    assert plan_chain_feedback_round("-10") == 10


def test_agent_family_helpers_parse_only_known_suffixes() -> None:
    assert agent_family_phase_name("agent", ".plan") == "agent--plan"
    assert agent_family_base("agent--code") == "agent"
    assert is_agent_family_member("agent--2")

    assert agent_family_base("agent-code") is None
    assert not is_agent_family_member("agent-2")
    assert agent_family_base("agent-code", include_legacy_dash=True) == "agent"
    assert is_agent_family_member("agent-2", include_legacy_dash=True)
    assert agent_family_base("sase-3r") is None
    assert not is_agent_family_member("historical-name")
