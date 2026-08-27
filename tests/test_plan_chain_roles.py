"""Tests for plan-chain naming and metadata classification."""

import pytest

from sase.plan_chain import (
    PLAN_CHAIN_CODER_SUFFIX,
    PLAN_CHAIN_GATE_SUFFIX,
    PLAN_CHAIN_MONITOR_SUFFIX,
    PLAN_CHAIN_PLAN_SUFFIX,
    agent_family_base,
    agent_family_phase_name,
    agent_family_role_for_suffix,
    agent_family_suffix_token,
    canonical_plan_chain_suffix,
    is_agent_family_member,
    is_plan_feedback_suffix,
    is_plan_chain_artifact_meta,
    plan_chain_agent_name,
    plan_chain_feedback_round,
    _parse_plan_chain_suffix,
    _plan_chain_feedback_suffix,
    _plan_chain_suffix_from_meta,
)


def test_plan_chain_agent_names_use_canonical_suffixes() -> None:
    assert plan_chain_agent_name("agent", PLAN_CHAIN_PLAN_SUFFIX) == "agent--plan"
    assert plan_chain_agent_name("agent", _plan_chain_feedback_suffix(1)) == "agent--2"
    assert plan_chain_agent_name("agent", PLAN_CHAIN_CODER_SUFFIX) == "agent--code"


def test_agent_family_role_for_suffix_accepts_new_and_legacy_suffixes() -> None:
    assert agent_family_role_for_suffix("--plan") == "plan"
    assert agent_family_role_for_suffix("-plan") == "plan"
    assert agent_family_role_for_suffix(".q") is None
    assert agent_family_role_for_suffix("-q") is None
    assert agent_family_role_for_suffix("--q") is None
    assert agent_family_role_for_suffix("--2") == "feedback"
    assert agent_family_role_for_suffix("--2", agent_family_role="review") == "review"
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


def test_numeric_suffixes_are_feedback_or_custom_members() -> None:
    assert agent_family_role_for_suffix("--0") is None
    assert agent_family_role_for_suffix("--1") is None
    assert agent_family_role_for_suffix("--2") == "feedback"
    assert agent_family_role_for_suffix("--2", agent_family_role="review") == "review"
    assert not is_plan_feedback_suffix("--2", agent_family_role="review")


def test_retired_nested_question_suffixes_are_not_plan_chain_suffixes() -> None:
    assert canonical_plan_chain_suffix("--code-0") is None
    assert canonical_plan_chain_suffix("--plan-0-0") is None
    assert _parse_plan_chain_suffix("--code-0") is None
    assert _parse_plan_chain_suffix("--plan-0-0") is None


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
    assert canonical_plan_chain_suffix(".q") is None
    assert canonical_plan_chain_suffix("-q") is None
    assert canonical_plan_chain_suffix(".code") == "--code"
    assert canonical_plan_chain_suffix("-code") == "--code"
    assert canonical_plan_chain_suffix(".2") == "--2"
    assert canonical_plan_chain_suffix("-2") == "--2"
    assert plan_chain_feedback_round("--10") == 10
    assert plan_chain_feedback_round("-10") == 10


def test_historical_canonical_q_suffix_remains_readable_as_custom_token() -> None:
    assert canonical_plan_chain_suffix("--q") == "--q"
    assert agent_family_suffix_token("--q") == "q"
    assert plan_chain_agent_name("agent", "--q") == "agent--q"
    assert agent_family_base("agent--q") == "agent"
    assert is_agent_family_member("agent--q")
    assert is_plan_chain_artifact_meta(
        {
            "name": "agent--q",
            "workflow_name": "agent",
            "role_suffix": "--q",
        }
    )


def test_monitor_suffix_classifies_as_monitor_phase() -> None:
    assert canonical_plan_chain_suffix(PLAN_CHAIN_MONITOR_SUFFIX) == "--mon"
    assert agent_family_role_for_suffix("--mon") == "monitor"
    info = _parse_plan_chain_suffix("--mon")
    assert info is not None
    assert info.role == "monitor"
    assert info.kind == "phase"
    assert plan_chain_agent_name("agent", "--mon") == "agent--mon"


def test_monitor_sequence_suffixes_classify_as_monitor_phase() -> None:
    assert canonical_plan_chain_suffix("--mon-0") == "--mon-0"
    assert canonical_plan_chain_suffix("--mon-3") == "--mon-3"
    assert agent_family_role_for_suffix("--mon-0") == "monitor"

    info = _parse_plan_chain_suffix("--mon-0")
    assert info is not None
    assert info.role == "monitor"
    assert info.kind == "phase"
    assert info.token == "0"
    assert not info.is_feedback

    assert plan_chain_agent_name("agent", "--mon-0") == "agent--mon-0"


def test_gate_suffixes_classify_as_gate_phase_members() -> None:
    assert canonical_plan_chain_suffix(PLAN_CHAIN_GATE_SUFFIX) == "--gate"
    assert canonical_plan_chain_suffix("--gate-0") == "--gate-0"
    assert canonical_plan_chain_suffix("--gate-alpha") == "--gate-alpha"
    assert agent_family_role_for_suffix("--gate") == "gate"
    assert agent_family_role_for_suffix("--gate-0") == "gate"

    info = _parse_plan_chain_suffix("--gate-0")
    assert info is not None
    assert info.role == "gate"
    assert info.kind == "phase"
    assert info.token == "0"
    assert not info.is_feedback

    assert plan_chain_agent_name("agent", "--gate") == "agent--gate"
    assert plan_chain_agent_name("agent", "--gate-0") == "agent--gate-0"


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
