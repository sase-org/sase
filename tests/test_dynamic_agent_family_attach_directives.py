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
    cleaned, directives = extract_prompt_directives("%i(reviewer, family=foo)\nDo work")

    assert cleaned == "Do work"
    assert directives.name is None
    assert directives.family_attach_parent == "foo"
    assert directives.family_attach_suffix == "reviewer"


def test_name_directive_single_positional_keeps_plain_name_behavior() -> None:
    cleaned, directives = extract_prompt_directives("%i(foo)\nDo work")

    assert cleaned == "Do work"
    assert directives.name == "foo"
    assert directives.family_attach_parent is None


def test_name_directive_rejects_positional_family_form_and_unknown_keywords() -> None:
    with pytest.raises(
        DirectiveError,
        match=r"positional family form.*%id\(<suffix>, family=<parent>\)",
    ):
        extract_prompt_directives("%i(foo, reviewer)\nDo work")

    with pytest.raises(DirectiveError, match="positional family form"):
        extract_prompt_directives("%i(foo, reviewer, extra)\nDo work")

    with pytest.raises(
        DirectiveError,
        match=r"Only bead=, clan=, family=, and tribe= are supported",
    ):
        extract_prompt_directives("%i(foo, run_status=DONE)\nDo work")


def test_name_directive_family_keyword_requires_suffix_and_parent() -> None:
    with pytest.raises(
        DirectiveError,
        match=r"family=.*requires exactly one positional suffix.*%id\(@, family=",
    ):
        extract_prompt_directives("%id(family=foo)\nDo work")

    with pytest.raises(DirectiveError, match="requires a non-empty family name"):
        extract_prompt_directives("%id(reviewer, family=)\nDo work")


@pytest.mark.parametrize(
    "source",
    [
        "%id(worker, clan=research, family=foo)",
        "%id(worker, clan=research, tribe=review)",
        "%id(worker, family=foo, tribe=review)",
    ],
)
def test_name_directive_identity_keywords_are_mutually_exclusive(source: str) -> None:
    with pytest.raises(
        DirectiveError,
        match=r"clan=, family=, and tribe=.*mutually exclusive",
    ):
        extract_prompt_directives(f"{source}\nDo work")


def test_name_directive_tribe_keyword_parses() -> None:
    cleaned, directives = extract_prompt_directives(
        "%id(worker, tribe=research)\nDo work"
    )

    assert cleaned == "Do work"
    assert directives.name == "worker"
    assert directives.tribe == "research"


def test_name_directive_rejects_legacy_family_suffix_spellings() -> None:
    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%i(.reviewer, family=foo)\nDo work")

    with pytest.raises(DirectiveError, match="without a family separator"):
        extract_prompt_directives("%i(-reviewer, family=foo)\nDo work")


def test_prelaunch_name_helpers_ignore_family_attach_form() -> None:
    prompt = "%i(reviewer, family=foo)\nDo work"

    assert extract_static_name_directive(prompt) is None
    validate_launch_name_requests([prompt])


def test_extract_family_attach_directive() -> None:
    directive = extract_family_attach_directive("%model:codex/gpt-5\n%i(@, family=foo)")

    assert directive == FamilyAttachDirective(parent="foo", suffix="@")


def test_extract_forced_family_attach_directive() -> None:
    prompt = "%id(!code, family=foo, bead=sase-1)\nDo work"

    cleaned, directives = extract_prompt_directives(prompt)
    directive = extract_family_attach_directive(prompt)

    assert cleaned == "Do work"
    assert directives.name_force_reuse is True
    assert directives.family_attach_parent == "foo"
    assert directives.family_attach_suffix == "code"
    assert directives.bead_id == "sase-1"
    assert directive == FamilyAttachDirective(
        parent="foo",
        suffix="code",
        force_reuse=True,
    )


def test_with_feedback_parent_default_uses_family_attach_directive() -> None:
    args: dict[str, str] = {"feedback": "tighten tests"}

    default_with_feedback_parent_from_family_attach(
        "with_feedback",
        args,
        prompt="%i(@, family=foo) #with_feedback:: tighten tests",
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
        with pytest.raises(FamilyAttachError, match=r"%i\(@, family=foo\)"):
            _ensure_family_name_available(
                "foo--bar",
                FamilyAttachDirective(parent="foo", suffix="bar"),
            )
