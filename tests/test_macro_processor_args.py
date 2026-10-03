"""Tests for macro argument validation, rendering, and command substitution."""

from unittest.mock import MagicMock, patch

from sase.macro._jinja import validate_and_convert_args
from sase.macro.models import UNSET, InputArg, InputType, Macro
from sase.macro.processor import (
    _resolve_command_substitution_in_args,
    process_macro_references,
)
from sase.macro.workflow_models import Workflow


# --- validate_and_convert_args tests ---


def testvalidate_and_convert_args_explicit_named_arg_not_overwritten() -> None:
    """Test that explicit named args take precedence over positional mapping."""
    macro_def = Macro(
        name="test",
        content="{{ prompt }}",
        inputs=[InputArg(name="prompt", type=InputType.TEXT)],
    )
    # Both a positional and a named arg provided for the same input
    positional_args = ["positional value"]
    named_args = {"prompt": "explicit named value"}

    conv_positional, conv_named = validate_and_convert_args(
        macro_def, positional_args, named_args
    )

    # Positional still maps to named, but then named_args processing overwrites
    assert conv_positional == ["positional value"]
    assert conv_named == {"prompt": "explicit named value"}


# --- Simple macro positional arg rendering tests ---


def _build_simple_macro_render_ctx(
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


def test_process_macro_colon_arg_decodes_plus_space_substitution() -> None:
    """Normal macro expansion decodes plus substitution before validation."""
    macro_def = Macro(
        name="path_info",
        content="Path: {{ root }}",
        inputs=[InputArg(name="root", type=InputType.PATH)],
    )

    with patch(
        "sase.macro.processor.get_all_macros", return_value={"path_info": macro_def}
    ):
        result = process_macro_references(
            "#path_info:/Users/me/Library/Application+Support/sase"
        )

    assert result == "Path: /Users/me/Library/Application Support/sase"


# --- Command substitution resolution tests ---


_CMD_SUB_PATCH = "sase.file_references.process_command_substitution"


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


# --- Shorthand free-text payload binding (structural, not [[...]] round-trip) ---


def test_process_macro_double_colon_shorthand_payload_is_not_reparsed() -> None:
    """A ':: text' payload is bound as one positional, never re-lexed as source."""
    macro_def = Macro(
        name="research_swarm",
        content="{{ prompt }}",
        inputs=[InputArg(name="prompt", type=InputType.TEXT, default=None)],
    )
    payload = (
        "sase memory read <web>:<keyword> [<web>:<keyword> [...]], and more, "
        "with a trailing apostrophe's worth of text"
    )

    with patch(
        "sase.macro.processor.get_all_macros",
        return_value={"research_swarm": macro_def},
    ):
        result = process_macro_references(f"#research_swarm:: {payload}")

    assert result == payload


def test_process_macro_shorthand_payload_plus_is_not_decoded() -> None:
    """A ':: text' payload keeps literal `+` (`C++`), it is not space-decoded."""
    macro_def = Macro(
        name="research_swarm",
        content="{{ prompt }}",
        inputs=[InputArg(name="prompt", type=InputType.TEXT, default=None)],
    )
    payload = "Compare C++ and Rust for A+B work."

    with patch(
        "sase.macro.processor.get_all_macros",
        return_value={"research_swarm": macro_def},
    ):
        result = process_macro_references(f"#research_swarm:: {payload}")

    assert result == payload


def test_process_macro_paren_arg_plus_is_not_decoded() -> None:
    """Paren-form macro arguments keep literal `+`, it is not space-decoded."""
    macro_def = Macro(
        name="describe",
        content="{{ prompt }}",
        inputs=[InputArg(name="prompt", type=InputType.TEXT)],
    )

    with patch(
        "sase.macro.processor.get_all_macros", return_value={"describe": macro_def}
    ):
        result = process_macro_references("#describe(Compare C++ and Rust)")

    assert result == "Compare C++ and Rust"


def test_process_macro_double_colon_eol_binds_next_lines() -> None:
    """`#name::` at EOL binds following lines like `:: text`."""
    macro_def = Macro(
        name="rs",
        content="{{ prompt }}",
        inputs=[InputArg(name="prompt", type=InputType.TEXT)],
    )

    with patch("sase.macro.processor.get_all_macros", return_value={"rs": macro_def}):
        assert process_macro_references("#rs::\nhello\nworld") == "hello\nworld"
        assert process_macro_references("#rs(g=yes)::\nhello") == "hello"
        assert "::" not in process_macro_references("#rs::\nhello\nworld")
