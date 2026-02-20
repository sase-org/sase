"""Tests for xprompt argument validation, rendering, and command substitution."""

from unittest.mock import MagicMock, patch

from sase.xprompt._jinja import validate_and_convert_args
from sase.xprompt.models import UNSET, InputArg, InputType, XPrompt
from sase.xprompt.processor import (
    _resolve_command_substitution_in_args,
    process_xprompt_references,
)
from sase.xprompt.workflow_executor_utils import render_template
from sase.xprompt.workflow_models import Workflow, WorkflowStep


# --- validate_and_convert_args tests ---


def testvalidate_and_convert_args_positional_to_named() -> None:
    """Test that positional args are mapped to named args using input definitions.

    When an xprompt has YAML frontmatter with input definitions like:
        input:
          - name: prompt
            type: text

    And a positional argument is passed like #xprompt([[text]]), the text
    should be accessible both as _1 (positional) and as the named variable
    'prompt' defined in the input specification.
    """
    xprompt = XPrompt(
        name="mentor",
        content="{{ prompt }}",
        inputs=[InputArg(name="prompt", type=InputType.TEXT)],
    )
    positional_args = ["This is my prompt text"]
    named_args: dict[str, str] = {}

    conv_positional, conv_named = validate_and_convert_args(
        xprompt, positional_args, named_args
    )

    # The positional arg should be in both lists
    assert conv_positional == ["This is my prompt text"]
    # The positional arg should also be mapped to the named arg 'prompt'
    assert conv_named == {"prompt": "This is my prompt text"}


def testvalidate_and_convert_args_multiple_positional_to_named() -> None:
    """Test that multiple positional args are mapped to their respective names."""
    xprompt = XPrompt(
        name="test",
        content="{{ first }} and {{ second }}",
        inputs=[
            InputArg(name="first", type=InputType.LINE),
            InputArg(name="second", type=InputType.LINE),
        ],
    )
    positional_args = ["value1", "value2"]
    named_args: dict[str, str] = {}

    conv_positional, conv_named = validate_and_convert_args(
        xprompt, positional_args, named_args
    )

    assert conv_positional == ["value1", "value2"]
    assert conv_named == {"first": "value1", "second": "value2"}


def testvalidate_and_convert_args_explicit_named_arg_not_overwritten() -> None:
    """Test that explicit named args take precedence over positional mapping."""
    xprompt = XPrompt(
        name="test",
        content="{{ prompt }}",
        inputs=[InputArg(name="prompt", type=InputType.TEXT)],
    )
    # Both a positional and a named arg provided for the same input
    positional_args = ["positional value"]
    named_args = {"prompt": "explicit named value"}

    conv_positional, conv_named = validate_and_convert_args(
        xprompt, positional_args, named_args
    )

    # Positional still maps to named, but then named_args processing overwrites
    assert conv_positional == ["positional value"]
    assert conv_named == {"prompt": "explicit named value"}


# --- Simple xprompt positional arg rendering tests ---


def _build_simple_xprompt_render_ctx(
    workflow: Workflow,
    positional_args: list[str],
    named_args: dict[str, str],
) -> dict[str, object]:
    """Replicate the render context logic from execute_workflow for testing."""
    render_ctx: dict[str, object] = dict(named_args)
    for i, value in enumerate(positional_args):
        if i < len(workflow.inputs):
            input_arg = workflow.inputs[i]
            if input_arg.name not in render_ctx:
                render_ctx[input_arg.name] = value
    for input_arg in workflow.inputs:
        if input_arg.name not in render_ctx and input_arg.default is not UNSET:
            render_ctx[input_arg.name] = (
                "null" if input_arg.default is None else str(input_arg.default)
            )
    return render_ctx


def test_simple_xprompt_positional_arg_renders_template() -> None:
    """Test that positional args are mapped to input names for simple xprompts.

    This exercises the fix for the #presubmit xprompt bug where positional args
    were not mapped before render_template was called.
    """
    workflow = Workflow(
        name="presubmit",
        inputs=[InputArg(name="presubmit_output_path", type=InputType.PATH)],
        steps=[
            WorkflowStep(
                name="main",
                prompt_part=("Fix the errors in @{{ presubmit_output_path }} file."),
            )
        ],
    )
    positional_args = ["~/.sase/hooks/presubmit.out"]
    named_args: dict[str, str] = {}

    render_ctx = _build_simple_xprompt_render_ctx(workflow, positional_args, named_args)
    content = workflow.get_prompt_part_content()
    rendered = render_template(content, render_ctx)

    assert rendered == "Fix the errors in @~/.sase/hooks/presubmit.out file."


def test_simple_xprompt_named_arg_takes_precedence() -> None:
    """Test that named args take precedence over positional for simple xprompts."""
    workflow = Workflow(
        name="test",
        inputs=[InputArg(name="path", type=InputType.PATH)],
        steps=[WorkflowStep(name="main", prompt_part="Check @{{ path }}.")],
    )
    positional_args = ["positional_path"]
    named_args = {"path": "named_path"}

    render_ctx = _build_simple_xprompt_render_ctx(workflow, positional_args, named_args)
    content = workflow.get_prompt_part_content()
    rendered = render_template(content, render_ctx)

    assert rendered == "Check @named_path."


def test_simple_xprompt_default_applied_when_no_arg() -> None:
    """Test that defaults are applied for missing inputs in simple xprompts."""
    workflow = Workflow(
        name="test",
        inputs=[
            InputArg(name="path", type=InputType.PATH),
            InputArg(name="mode", type=InputType.LINE, default="strict"),
        ],
        steps=[
            WorkflowStep(
                name="main",
                prompt_part="Check @{{ path }} in {{ mode }} mode.",
            )
        ],
    )
    positional_args = ["/some/file"]
    named_args: dict[str, str] = {}

    render_ctx = _build_simple_xprompt_render_ctx(workflow, positional_args, named_args)
    content = workflow.get_prompt_part_content()
    rendered = render_template(content, render_ctx)

    assert rendered == "Check @/some/file in strict mode."


def test_simple_xprompt_null_default_renders_as_null() -> None:
    """Test that None defaults render as 'null' string."""
    workflow = Workflow(
        name="test",
        inputs=[
            InputArg(name="val", type=InputType.LINE, default=None),
        ],
        steps=[WorkflowStep(name="main", prompt_part="Value is {{ val }}.")],
    )
    render_ctx = _build_simple_xprompt_render_ctx(workflow, [], {})
    content = workflow.get_prompt_part_content()
    rendered = render_template(content, render_ctx)

    assert rendered == "Value is null."


# --- Command substitution resolution tests ---


_CMD_SUB_PATCH = "sase.gemini_wrapper.file_references.process_command_substitution"


def test_resolve_cmd_sub_plain_args_unchanged() -> None:
    """Test that plain args (no $() ) pass through unchanged."""
    pos, named = _resolve_command_substitution_in_args(
        ["plain", "args"], {"key": "value"}
    )
    assert pos == ["plain", "args"]
    assert named == {"key": "value"}


@patch(_CMD_SUB_PATCH)
def test_resolve_cmd_sub_resolves_dollar_paren(
    mock_cmd_sub: MagicMock,
) -> None:
    """Test that args containing $( are resolved via process_command_substitution."""
    mock_cmd_sub.side_effect = lambda s: s.replace("$(branch_bug)", "PROJ-123")
    pos, named = _resolve_command_substitution_in_args(
        ["$(branch_bug)"], {"id": "$(branch_bug)"}
    )
    assert pos == ["PROJ-123"]
    assert named == {"id": "PROJ-123"}


@patch(_CMD_SUB_PATCH)
@patch("sase.xprompt.processor.get_all_xprompts")
def test_process_xprompt_references_colon_cmd_sub(
    mock_get_all: MagicMock,
    mock_cmd_sub: MagicMock,
) -> None:
    """Test process_xprompt_references resolves $(cmd) in colon arg."""
    mock_cmd_sub.side_effect = lambda s: s.replace("$(branch_bug)", "PROJ-42")
    mock_get_all.return_value = {
        "bug": XPrompt(name="bug", content="Bug ID: {1}"),
    }
    result = process_xprompt_references("#bug:$(branch_bug)")
    assert result == "Bug ID: PROJ-42"


@patch(_CMD_SUB_PATCH)
@patch("sase.xprompt.processor.get_all_xprompts")
def test_process_xprompt_references_paren_cmd_sub(
    mock_get_all: MagicMock,
    mock_cmd_sub: MagicMock,
) -> None:
    """Test process_xprompt_references resolves $(cmd) in paren arg."""
    mock_cmd_sub.side_effect = lambda s: s.replace("$(branch_bug)", "PROJ-42")
    mock_get_all.return_value = {
        "bug": XPrompt(name="bug", content="Bug ID: {1}"),
    }
    result = process_xprompt_references("#bug($(branch_bug))")
    assert result == "Bug ID: PROJ-42"


@patch(_CMD_SUB_PATCH)
@patch("sase.xprompt.processor.get_all_xprompts")
def test_process_xprompt_references_named_cmd_sub(
    mock_get_all: MagicMock,
    mock_cmd_sub: MagicMock,
) -> None:
    """Test process_xprompt_references resolves $(cmd) in named arg."""
    mock_cmd_sub.side_effect = lambda s: s.replace("$(branch_bug)", "PROJ-42")
    mock_get_all.return_value = {
        "bug": XPrompt(
            name="bug",
            content="{{ bug_id }}",
            inputs=[InputArg(name="bug_id", type=InputType.LINE)],
        ),
    }
    result = process_xprompt_references("#bug(bug_id=$(branch_bug))")
    assert result == "PROJ-42"
