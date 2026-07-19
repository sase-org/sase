from __future__ import annotations

from unittest.mock import patch

import pytest

from sase.agent.family_attach import (
    FamilyAttachDirective,
    FamilyAttachError,
    default_with_feedback_parent_from_family_attach,
    extract_family_attach_directive,
)
from sase.agent.launch_validation import validate_launch_name_requests
from sase.agent.multi_prompt_reference_directives import extract_static_name_directive
from sase.plan_chain import (
    agent_family_role_for_suffix,
    is_plan_chain_artifact_meta,
    question_followup_suffix_template,
)
from sase.xprompt._exceptions import DirectiveError
from sase.xprompt.directives import extract_prompt_directives


def test_name_directive_family_attach_form_parses_and_strips() -> None:
    cleaned, directives = extract_prompt_directives("%i(foo, reviewer)\nDo work")

    assert cleaned == "Do work"
    assert directives.name is None
    assert directives.family_attach_parent == "foo"
    assert directives.family_attach_suffix == "reviewer"


def test_name_directive_single_positional_keeps_plain_name_behavior() -> None:
    cleaned, directives = extract_prompt_directives("%i(foo)\nDo work")

    assert cleaned == "Do work"
    assert directives.name == "foo"
    assert directives.family_attach_parent is None


def test_name_directive_rejects_extra_positionals_and_keywords() -> None:
    with pytest.raises(DirectiveError, match="at most two positional"):
        extract_prompt_directives("%i(foo, reviewer, extra)\nDo work")

    with pytest.raises(DirectiveError, match="Unsupported keyword"):
        extract_prompt_directives("%i(foo, run_status=DONE)\nDo work")


def test_name_directive_rejects_legacy_family_suffix_spellings() -> None:
    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%i(foo, .reviewer)\nDo work")

    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%i(foo, -reviewer)\nDo work")


def test_prelaunch_name_helpers_ignore_family_attach_form() -> None:
    prompt = "%i(foo, reviewer)\nDo work"

    assert extract_static_name_directive(prompt) is None
    validate_launch_name_requests([prompt])


def test_extract_family_attach_directive() -> None:
    directive = extract_family_attach_directive("%model:codex/gpt-5\n%i(foo, @)")

    assert directive == FamilyAttachDirective(parent="foo", suffix="@")


def test_with_feedback_parent_default_uses_family_attach_directive() -> None:
    args: dict[str, str] = {"feedback": "tighten tests"}

    default_with_feedback_parent_from_family_attach(
        "with_feedback",
        args,
        prompt="%i(foo, @) #with_feedback:: tighten tests",
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


def test_arbitrary_family_role_keeps_role_for_question_followup() -> None:
    assert (
        question_followup_suffix_template(
            "--reviewer",
            agent_family_role="reviewer",
        )
        == "--reviewer-@"
    )


def test_family_attach_collision_message_suggests_auto_suffix() -> None:
    from sase.agent._family_attach_resolution import _ensure_family_name_available

    with patch("sase.agent.names.get_reserved_agent_names", return_value={"foo--bar"}):
        with pytest.raises(FamilyAttachError, match=r"%i\(foo, @\)"):
            _ensure_family_name_available(
                "foo--bar",
                FamilyAttachDirective(parent="foo", suffix="bar"),
            )
