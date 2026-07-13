"""Tests for shared xprompt reference parsing and workflow kind classification."""

from sase.xprompt._fenced_blocks import protect_fenced_blocks
from sase.xprompt._parsing import (
    XPromptReferenceArgKind,
    XPromptReferenceMarker,
    iter_xprompt_references,
)
from sase.xprompt.workflow_models import Workflow, WorkflowKind, WorkflowStep


def _single_ref(prompt: str):
    refs = iter_xprompt_references(prompt)
    assert len(refs) == 1
    return refs[0]


def test_parse_inline_reference() -> None:
    ref = _single_ref("#commit")

    assert ref.marker is XPromptReferenceMarker.INLINE
    assert ref.name == "commit"
    assert ref.raw == "#commit"
    assert ref.start == 0
    assert ref.end == len("#commit")
    assert ref.arg_kind is XPromptReferenceArgKind.NONE
    assert ref.hitl_override is None
    assert ref.parse_arguments() == ([], {})


def test_parse_standalone_reference() -> None:
    ref = _single_ref("#!sync")

    assert ref.marker is XPromptReferenceMarker.STANDALONE
    assert ref.is_standalone_marker
    assert ref.name == "sync"
    assert ref.raw == "#!sync"
    assert ref.reference_body == "sync"


def test_parse_standalone_reference_with_hitl_suffix() -> None:
    ref = _single_ref("#!sync!!")

    assert ref.name == "sync"
    assert ref.raw == "#!sync!!"
    assert ref.hitl_override is True
    assert ref.reference_body == "sync"


def test_parse_plus_reference_is_boolean_shorthand() -> None:
    ref = _single_ref("#feature+")

    assert ref.name == "feature"
    assert ref.arg_kind is XPromptReferenceArgKind.PLUS
    assert ref.parse_arguments() == (["true"], {})


def test_parse_namespaced_standalone_reference_with_colon_arg() -> None:
    ref = _single_ref("#!sase/toobig_split:prod")

    assert ref.name == "sase/toobig_split"
    assert ref.arg_kind is XPromptReferenceArgKind.COLON
    assert ref.raw == "#!sase/toobig_split:prod"
    assert ref.argument_source == ":prod"
    assert ref.parse_arguments() == (["prod"], {})


def test_parse_colon_reference_decodes_plus_space_substitution() -> None:
    ref = _single_ref("#setup:/Users/me/Library/Application+Support/sase")

    assert ref.name == "setup"
    assert ref.raw == "#setup:/Users/me/Library/Application+Support/sase"
    assert ref.argument_source == ":/Users/me/Library/Application+Support/sase"
    assert ref.parse_arguments() == (
        ["/Users/me/Library/Application Support/sase"],
        {},
    )


def test_parse_colon_shorthand_reference_with_parentheses_in_text() -> None:
    ref = _single_ref("#research: find foo (bar)")

    assert ref.name == "research"
    assert ref.arg_kind is XPromptReferenceArgKind.COLON_SHORTHAND
    assert ref.argument_source == ": find foo (bar)"
    assert ref.parse_arguments() == (["find foo (bar)"], {})


def test_parse_double_colon_shorthand_reference_with_parentheses_in_text() -> None:
    ref = _single_ref("#research_swarm:: find foo (bar)")

    assert ref.name == "research_swarm"
    assert ref.arg_kind is XPromptReferenceArgKind.DOUBLE_COLON_SHORTHAND
    assert ref.argument_source == ":: find foo (bar)"
    assert ref.parse_arguments() == (["find foo (bar)"], {})


def test_parse_standalone_reference_with_paren_args() -> None:
    ref = _single_ref("#!deploy(arg=value)")

    assert ref.name == "deploy"
    assert ref.arg_kind is XPromptReferenceArgKind.PAREN
    assert ref.raw == "#!deploy(arg=value)"
    assert ref.argument_source == "(arg=value)"
    assert ref.parse_arguments() == ([], {"arg": "value"})


def test_references_inside_fenced_blocks_are_lexically_matchable() -> None:
    prompt = "```\n#!sync\n```"

    ref = _single_ref(prompt)

    assert ref.raw == "#!sync"


def test_callers_can_filter_fenced_block_references() -> None:
    prompt = "```\n#!sync\n```"
    fenced_blocks: list[str] = []
    protected = protect_fenced_blocks(prompt, fenced_blocks)

    assert iter_xprompt_references(protected) == []


def test_markdown_heading_with_space_is_not_a_reference() -> None:
    assert iter_xprompt_references("# Heading") == []


def test_workflow_kind_simple_xprompt() -> None:
    workflow = Workflow(
        name="commit",
        steps=[WorkflowStep(name="main", prompt_part="commit this")],
    )

    assert workflow.prompt_kind() is WorkflowKind.SIMPLE_XPROMPT


def test_workflow_kind_embeddable_workflow() -> None:
    workflow = Workflow(
        name="gh",
        steps=[
            WorkflowStep(name="setup", bash="true"),
            WorkflowStep(name="main", prompt_part="wrapped prompt"),
            WorkflowStep(name="teardown", bash="true"),
        ],
    )

    assert workflow.prompt_kind() is WorkflowKind.EMBEDDABLE_WORKFLOW


def test_workflow_kind_standalone_workflow() -> None:
    workflow = Workflow(
        name="sync",
        steps=[WorkflowStep(name="run", bash="sase sync")],
    )

    assert workflow.prompt_kind() is WorkflowKind.STANDALONE_WORKFLOW
