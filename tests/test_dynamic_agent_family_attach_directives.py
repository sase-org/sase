from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.agent.family_attach import (
    _FamilyAttachDirective,
    _FamilyAttachError,
    _extract_family_attach_directive,
    default_with_feedback_parent_from_family_attach,
)
from sase.agent.launch_validation import validate_launch_name_requests
from sase.agent.multi_prompt_reference_directives import extract_static_name_directive
from sase.agent_family import (
    STANDARD_PLAN_CHAIN_ID,
    build_handoff_event,
    evaluate_handoff_event,
    evaluate_questions_transition,
    family_state_snapshot,
)
from sase.plan_chain import agent_family_role_for_suffix, is_plan_chain_artifact_meta
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_name_directive_family_attach_form_parses_and_strips() -> None:
    cleaned, directives = extract_prompt_directives("%n(foo, reviewer)\nDo work")

    assert cleaned == "Do work"
    assert directives.name is None
    assert directives.family_attach_parent == "foo"
    assert directives.family_attach_suffix == "reviewer"


def test_name_directive_single_positional_keeps_plain_name_behavior() -> None:
    cleaned, directives = extract_prompt_directives("%n(foo)\nDo work")

    assert cleaned == "Do work"
    assert directives.name == "foo"
    assert directives.family_attach_parent is None


def test_name_directive_rejects_extra_positionals_and_keywords() -> None:
    with pytest.raises(DirectiveError, match="at most two positional"):
        extract_prompt_directives("%n(foo, reviewer, extra)\nDo work")

    with pytest.raises(DirectiveError, match="Unsupported keyword"):
        extract_prompt_directives("%n(foo, run_status=DONE)\nDo work")


def test_name_directive_rejects_legacy_family_suffix_spellings() -> None:
    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%n(foo, .reviewer)\nDo work")

    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%n(foo, -reviewer)\nDo work")


def test_prelaunch_name_helpers_ignore_family_attach_form() -> None:
    prompt = "%n(foo, reviewer)\nDo work"

    assert extract_static_name_directive(prompt) is None
    validate_launch_name_requests([prompt])


def test_extract_family_attach_directive() -> None:
    directive = _extract_family_attach_directive("%model:codex/gpt-5\n%n(foo, @)")

    assert directive == _FamilyAttachDirective(parent="foo", suffix="@")


def test_with_feedback_parent_default_uses_family_attach_directive() -> None:
    args: dict[str, str] = {"feedback": "tighten tests"}

    default_with_feedback_parent_from_family_attach(
        "with_feedback",
        args,
        prompt="%n(foo, @) #with_feedback:: tighten tests",
    )

    assert args["parent"] == "foo"


def test_custom_family_role_classifies_plan_chain_metadata() -> None:
    meta = {
        "name": "foo--reviewer",
        "workflow_name": "foo",
        "role_suffix": "--reviewer",
        "agent_family_role": "reviewer",
    }

    assert agent_family_role_for_suffix("--reviewer", agent_family_role="reviewer") == (
        "reviewer"
    )
    assert is_plan_chain_artifact_meta(meta)


def test_custom_family_role_is_standard_chain_evaluator_compatible() -> None:
    event = build_handoff_event(
        kind="questions_submitted",
        artifacts_dir="/tmp/foo-reviewer",
        payload={"questions": [{"question": "Clarify scope?"}]},
        current_role_suffix="--reviewer",
        agent_family_role="reviewer",
    )
    snapshot = family_state_snapshot(
        current_role_suffix="--reviewer",
        agent_family_role="reviewer",
    )

    evaluation = evaluate_handoff_event(event, snapshot)
    transition = evaluate_questions_transition(
        interrupted_suffix="--reviewer",
        interrupted_role="reviewer",
        feedback_count=0,
        qa_round_count=1,
    )

    assert event.interrupted_role == "reviewer"
    assert evaluation.gate_id == "user_questions"
    assert evaluation.runtime_metadata.as_meta_fields()["agent_family_config_id"] == (
        STANDARD_PLAN_CHAIN_ID
    )
    assert transition.followup_role == "reviewer"
    assert transition.suffix_template == "--reviewer-@"


def test_family_attach_collision_message_suggests_auto_suffix() -> None:
    from sase.agent.family_attach import _ensure_family_name_available

    with patch("sase.agent.names.get_reserved_agent_names", return_value={"foo--bar"}):
        with pytest.raises(_FamilyAttachError, match=r"%n\(foo, @\)"):
            _ensure_family_name_available(
                "foo--bar",
                _FamilyAttachDirective(parent="foo", suffix="bar"),
            )
