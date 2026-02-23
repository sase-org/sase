"""Tests for xprompt argument validation, rendering, and command substitution."""

from unittest.mock import MagicMock, patch

from sase.xprompt._jinja import validate_and_convert_args
from sase.xprompt.models import UNSET, InputArg, InputType, XPrompt
from sase.xprompt.processor import (
    _resolve_command_substitution_in_args,
)
from sase.xprompt.workflow_models import Workflow


# --- validate_and_convert_args tests ---


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


# --- Command substitution resolution tests ---


_CMD_SUB_PATCH = "sase.gemini_wrapper.file_references.process_command_substitution"


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
