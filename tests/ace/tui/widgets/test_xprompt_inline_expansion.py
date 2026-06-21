"""Tests for the pure ``Ctrl+I`` inline-expansion helper."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.xprompt_inline_expansion import (
    InlineExpansionReason,
    expand_inline_xprompt,
)
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.workflow_models import Workflow, WorkflowStep

_MODULE = "sase.ace.tui.widgets.xprompt_inline_expansion"


def _simple_workflow(
    name: str,
    content: str,
    *,
    inputs: list[InputArg] | None = None,
    xprompts: dict[str, XPrompt] | None = None,
    environment: dict[str, str] | None = None,
) -> Workflow:
    """Build a single prompt-part workflow (a simple xprompt projection)."""
    return Workflow(
        name=name,
        inputs=inputs or [],
        steps=[WorkflowStep(name="main", prompt_part=content)],
        xprompts=xprompts or {},
        environment=environment or {},
    )


class TestSupportedExpansion:
    def test_simple_no_arg_xprompt_expands_to_content(self) -> None:
        wf = _simple_workflow("note", "Just a plain note.")
        result = expand_inline_xprompt("note", wf)
        assert result.ok
        assert result.reason is InlineExpansionReason.EXPANDED
        assert result.expanded_text == "Just a plain note."
        assert result.error is None

    def test_simple_xprompt_with_defaults_expands_using_defaults(self) -> None:
        wf = _simple_workflow(
            "greet",
            "Hello {{ name }}!",
            inputs=[InputArg(name="name", type=InputType.LINE, default="world")],
        )
        result = expand_inline_xprompt("greet", wf)
        assert result.ok
        assert result.expanded_text == "Hello world!"

    def test_segment_separators_preserved_as_text(self) -> None:
        wf = _simple_workflow("multi", "Part A\n---\nPart B")
        result = expand_inline_xprompt("multi", wf)
        assert result.ok
        assert result.expanded_text == "Part A\n---\nPart B"

    def test_nested_local_reference_expands_from_frontmatter(self) -> None:
        rules = XPrompt(name="_rules", content="Be concise.")
        wf = _simple_workflow("guide", "Rules:\n#_rules")
        with patch(f"{_MODULE}.get_all_xprompts", return_value={}):
            result = expand_inline_xprompt(
                "guide", wf, local_xprompts={"_rules": rules}
            )
        assert result.ok
        assert result.expanded_text == "Rules:\nBe concise."

    def test_global_reference_to_local_helper_expands_recursively(self) -> None:
        team = XPrompt(name="team", content="Team note: #_rules")
        rules = XPrompt(name="_rules", content="local rule")
        wf = _simple_workflow("entry", "#team")
        with patch(f"{_MODULE}.get_all_xprompts", return_value={"team": team}):
            result = expand_inline_xprompt(
                "entry", wf, local_xprompts={"_rules": rules}
            )
        assert result.ok
        assert result.expanded_text == "Team note: local rule"


class TestRejectedExpansion:
    def test_required_input_returns_error(self) -> None:
        wf = _simple_workflow(
            "greet",
            "Hi {{ who }}",
            inputs=[InputArg(name="who", type=InputType.LINE)],
        )
        result = expand_inline_xprompt("greet", wf)
        assert not result.ok
        assert result.reason is InlineExpansionReason.REQUIRED_INPUT
        assert result.expanded_text is None
        assert result.error is not None
        assert "who" in result.error

    def test_standalone_workflow_returns_error(self) -> None:
        wf = Workflow(
            name="deploy",
            steps=[WorkflowStep(name="main", agent="deploy the app")],
        )
        result = expand_inline_xprompt("deploy", wf)
        assert not result.ok
        assert result.reason is InlineExpansionReason.STANDALONE_WORKFLOW
        assert result.error is not None
        assert "#!deploy" in result.error

    def test_embeddable_workflow_with_steps_returns_error(self) -> None:
        wf = Workflow(
            name="build",
            steps=[
                WorkflowStep(name="pre", bash="make"),
                WorkflowStep(name="main", prompt_part="body text"),
            ],
        )
        result = expand_inline_xprompt("build", wf)
        assert not result.ok
        assert result.reason is InlineExpansionReason.WORKFLOW_STEPS
        assert result.error is not None
        assert "workflow steps" in result.error

    def test_environment_side_effect_returns_error(self) -> None:
        wf = _simple_workflow("envy", "body", environment={"FOO": "bar"})
        result = expand_inline_xprompt("envy", wf)
        assert not result.ok
        assert result.reason is InlineExpansionReason.WORKFLOW_STEPS

    def test_circular_reference_returns_error_without_exiting(self) -> None:
        a = XPrompt(name="a", content="#b")
        b = XPrompt(name="b", content="#a")
        wf = _simple_workflow("start", "#a")
        with patch(f"{_MODULE}.get_all_xprompts", return_value={}):
            result = expand_inline_xprompt("start", wf, local_xprompts={"a": a, "b": b})
        assert not result.ok
        assert result.reason is InlineExpansionReason.EXPANSION_ERROR
        assert result.expanded_text is None

    def test_invalid_template_returns_error(self) -> None:
        # ``definitely_undefined_xyz`` is not a global template var; StrictUndefined
        # makes rendering raise, which the helper must surface as an error rather
        # than letting it propagate.
        wf = _simple_workflow("bad", "Hello {{ definitely_undefined_xyz }}")
        result = expand_inline_xprompt("bad", wf)
        assert not result.ok
        assert result.reason is InlineExpansionReason.EXPANSION_ERROR
