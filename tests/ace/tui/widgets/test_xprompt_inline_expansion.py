"""Tests for the pure ``Ctrl+I`` inline-expansion helper."""

from __future__ import annotations

from unittest.mock import patch

from sase.ace.tui.widgets.xprompt_inline_expansion import (
    _InlineExpansionReason,
    expand_inline_xprompt,
)
from sase.agent.prompt_inputs import render_prompt_with_inputs
from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.prompt_frontmatter import PromptFrontmatter
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
        assert result.reason is _InlineExpansionReason.EXPANDED
        assert result.expanded_text == "Just a plain note."
        assert result.error is None
        assert result.inputs == []

    def test_required_input_preserves_placeholder_and_returns_declaration(
        self,
    ) -> None:
        arg = InputArg(name="who", type=InputType.LINE)
        wf = _simple_workflow("greet", "Hi {{ who }}", inputs=[arg])
        result = expand_inline_xprompt("greet", wf)
        assert result.ok
        assert result.expanded_text == "Hi {{ who }}"
        assert result.inputs == [arg]

    def test_optional_input_preserves_placeholder_instead_of_baking_default(
        self,
    ) -> None:
        arg = InputArg(name="name", type=InputType.LINE, default="world")
        wf = _simple_workflow(
            "greet",
            "Hello {{ name }}!",
            inputs=[arg],
        )
        result = expand_inline_xprompt("greet", wf)
        assert result.ok
        assert result.expanded_text == "Hello {{ name }}!"
        assert result.inputs == [arg]

    def test_typed_inputs_round_trip_without_type_validation(self) -> None:
        retries = InputArg(name="retries", type=InputType.INT)
        dry_run = InputArg(name="dry_run", type=InputType.BOOL, default=False)
        wf = _simple_workflow(
            "deploy",
            "retries={{ retries }} dry_run={{ dry_run }}",
            inputs=[retries, dry_run],
        )
        result = expand_inline_xprompt("deploy", wf)
        assert result.ok
        assert result.expanded_text == "retries={{ retries }} dry_run={{ dry_run }}"
        assert result.inputs == [retries, dry_run]

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

    def test_declared_input_used_inside_local_helper_surfaces_in_body(self) -> None:
        topic = InputArg(name="topic", type=InputType.LINE)
        helper = XPrompt(
            name="_article_search_agent",
            content="Search for recent writing about {{ topic }}.",
        )
        wf = _simple_workflow(
            "reads",
            "#_article_search_agent",
            inputs=[topic],
            xprompts={"_article_search_agent": helper},
        )
        result = expand_inline_xprompt("reads", wf)
        assert result.ok
        assert result.expanded_text == "Search for recent writing about {{ topic }}."
        assert result.inputs == [topic]

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

    def test_declared_input_used_inside_nested_global_reference_round_trips(
        self,
    ) -> None:
        topic = InputArg(name="topic", type=InputType.LINE)
        team = XPrompt(name="team", content="Team topic: {{ topic }}")
        wf = _simple_workflow("entry", "#team", inputs=[topic])
        with patch(f"{_MODULE}.get_all_xprompts", return_value={"team": team}):
            result = expand_inline_xprompt("entry", wf)
        assert result.ok
        assert result.expanded_text == "Team topic: {{ topic }}"
        assert result.inputs == [topic]

    def test_multi_agent_body_with_inputs_preserves_segment_separators(self) -> None:
        item = InputArg(name="item", type=InputType.LINE)
        wf = _simple_workflow(
            "multi",
            "Part A {{ item }}\n---\nPart B {{ item }}",
            inputs=[item],
        )
        result = expand_inline_xprompt("multi", wf)
        assert result.ok
        assert result.expanded_text == "Part A {{ item }}\n---\nPart B {{ item }}"
        assert result.inputs == [item]

    def test_input_filters_degrade_as_rendered_identity_strings(self) -> None:
        name = InputArg(name="name", type=InputType.LINE)
        wf = _simple_workflow("shout", "{{ name | upper }}", inputs=[name])
        result = expand_inline_xprompt("shout", wf)
        assert result.ok
        assert result.expanded_text == "{{ NAME }}"

    def test_expanded_direct_input_resolves_through_launch_substitution(self) -> None:
        topic = InputArg(name="topic", type=InputType.LINE)
        wf = _simple_workflow("reads", "Read about {{ topic }}.", inputs=[topic])
        result = expand_inline_xprompt("reads", wf)

        frontmatter = PromptFrontmatter()
        for arg in result.inputs:
            frontmatter.set_input(arg)
        prompt = f"{frontmatter.serialize()}\n{result.expanded_text}"

        assert (
            render_prompt_with_inputs(prompt, {"topic": "SASE"}) == "Read about SASE."
        )

    def test_expanded_helper_input_resolves_through_launch_substitution(self) -> None:
        topic = InputArg(name="topic", type=InputType.LINE)
        helper = XPrompt(name="_helper", content="Read about {{ topic }}.")
        wf = _simple_workflow(
            "reads",
            "#_helper",
            inputs=[topic],
            xprompts={"_helper": helper},
        )
        result = expand_inline_xprompt("reads", wf)

        frontmatter = PromptFrontmatter()
        for arg in result.inputs:
            frontmatter.set_input(arg)
        prompt = f"{frontmatter.serialize()}\n{result.expanded_text}"

        assert (
            render_prompt_with_inputs(prompt, {"topic": "SASE"}) == "Read about SASE."
        )


class TestRejectedExpansion:
    def test_standalone_workflow_returns_error(self) -> None:
        wf = Workflow(
            name="deploy",
            steps=[WorkflowStep(name="main", agent="deploy the app")],
        )
        result = expand_inline_xprompt("deploy", wf)
        assert not result.ok
        assert result.reason is _InlineExpansionReason.STANDALONE_WORKFLOW
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
        assert result.reason is _InlineExpansionReason.WORKFLOW_STEPS
        assert result.error is not None
        assert "workflow steps" in result.error

    def test_environment_side_effect_returns_error(self) -> None:
        wf = _simple_workflow("envy", "body", environment={"FOO": "bar"})
        result = expand_inline_xprompt("envy", wf)
        assert not result.ok
        assert result.reason is _InlineExpansionReason.WORKFLOW_STEPS

    def test_circular_reference_returns_error_without_exiting(self) -> None:
        a = XPrompt(name="a", content="#b")
        b = XPrompt(name="b", content="#a")
        wf = _simple_workflow("start", "#a")
        with patch(f"{_MODULE}.get_all_xprompts", return_value={}):
            result = expand_inline_xprompt("start", wf, local_xprompts={"a": a, "b": b})
        assert not result.ok
        assert result.reason is _InlineExpansionReason.EXPANSION_ERROR
        assert result.expanded_text is None

    def test_invalid_template_returns_error(self) -> None:
        # ``definitely_undefined_xyz`` is not a global template var; StrictUndefined
        # makes rendering raise, which the helper must surface as an error rather
        # than letting it propagate.
        wf = _simple_workflow("bad", "Hello {{ definitely_undefined_xyz }}")
        result = expand_inline_xprompt("bad", wf)
        assert not result.ok
        assert result.reason is _InlineExpansionReason.EXPANSION_ERROR
