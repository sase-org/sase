"""Tests for jinja, models, standalone execution, and utilities."""

import os
from pathlib import Path

import pytest
from sase.main.query_handler._standalone_steps import _evaluate_standalone_condition
from sase.content import dump_yaml
from sase.xprompt._exceptions import XPromptArgumentError
from sase.xprompt._jinja import (
    _substitute_legacy_placeholders,
    render_toplevel_jinja2,
    substitute_placeholders,
    validate_and_convert_args,
)
from sase.xprompt.models import (
    InputArg,
    InputType,
    XPrompt,
)
from sase.xprompt.workflow_executor_utils import parse_bash_output, render_template


def test_evaluate_standalone_condition_missing_variable() -> None:
    """Test condition evaluates to False when variable is missing."""
    result = _evaluate_standalone_condition("{{ nonexistent }}", {})
    assert result is False


# Tests for is_jinja2_template


# Tests for _substitute_legacy_placeholders


def test_substitute_legacy_missing_arg_error() -> None:
    """Test _substitute_legacy_placeholders raises on missing required arg."""
    with pytest.raises(XPromptArgumentError, match="requires argument"):
        _substitute_legacy_placeholders("{1}", [], "test")


# Tests for render_toplevel_jinja2


def test_render_toplevel_jinja2_simple() -> None:
    """Test render_toplevel_jinja2 with plain text (no Jinja2)."""
    result = render_toplevel_jinja2("Hello world")
    assert result == "Hello world"


def test_render_toplevel_jinja2_ignores_fenced_block() -> None:
    """{{ var }} inside triple backticks is not rendered."""
    content = "```\n{{ undefined_var }}\n```"
    result = render_toplevel_jinja2(content)
    assert result == content


def test_render_toplevel_jinja2_ignores_quadruple_backtick_block() -> None:
    """{{ var }} inside quadruple backticks is not rendered."""
    content = "````\n{{ undefined_var }}\n````"
    result = render_toplevel_jinja2(content)
    assert result == content


def test_render_toplevel_jinja2_renders_outside_fenced_block() -> None:
    """Jinja2 outside code blocks still works when code blocks are present."""
    content = "```\ncode\n```\nValue is: {{ 1 + 1 }}"
    result = render_toplevel_jinja2(content)
    assert "```\ncode\n```" in result
    assert "Value is: 2" in result


def test_substitute_placeholders_ignores_jinja_in_fenced_block() -> None:
    """{{ _1 }} inside fenced blocks in xprompt content is preserved."""
    content = "Hello {{ _1 }}\n```\n{{ _1 }} should not expand\n```"
    result = substitute_placeholders(content, ["world"], {}, "test")
    assert "Hello world" in result
    assert "{{ _1 }} should not expand" in result


# Tests for substitute_placeholders


# Tests for parse_bash_output


def test_parse_bash_output_invalid_json() -> None:
    """Test parse_bash_output with invalid JSON falls through."""
    result = parse_bash_output("{not valid json")
    assert result == {"_output": "{not valid json"}


def test_parse_bash_output_empty() -> None:
    """Test parse_bash_output with empty input."""
    result = parse_bash_output("")
    assert result == {}


# Tests for dump_yaml


def test_dump_yaml_multiline() -> None:
    """Test dump_yaml with multiline string uses literal block style."""
    result = dump_yaml({"msg": "line1\nline2\n"})
    assert "msg:" in result
    # Should use literal block style (|)
    assert "|" in result


# Tests for InputArg.validate_and_convert


def test_input_arg_word_valid() -> None:
    """Test InputArg validates word type correctly."""
    arg = InputArg(name="x", type=InputType.WORD)
    assert arg.validate_and_convert("hello") == "hello"


def test_input_arg_int_valid() -> None:
    """Test InputArg validates int type correctly."""
    arg = InputArg(name="x", type=InputType.INT)
    assert arg.validate_and_convert("42") == 42


def test_input_arg_float_valid() -> None:
    """Test InputArg validates float type correctly."""
    arg = InputArg(name="x", type=InputType.FLOAT)
    assert arg.validate_and_convert("3.14") == pytest.approx(3.14)


def test_input_arg_bool_true() -> None:
    """Test InputArg validates bool true values."""
    arg = InputArg(name="x", type=InputType.BOOL)
    assert arg.validate_and_convert("true") is True
    assert arg.validate_and_convert("yes") is True
    assert arg.validate_and_convert("1") is True
    assert arg.validate_and_convert("on") is True


def test_input_arg_bool_false() -> None:
    """Test InputArg validates bool false values."""
    arg = InputArg(name="x", type=InputType.BOOL)
    assert arg.validate_and_convert("false") is False
    assert arg.validate_and_convert("no") is False
    assert arg.validate_and_convert("0") is False
    assert arg.validate_and_convert("off") is False


# Tests for XPrompt


# Tests for xprompt_to_workflow


# Tests for validate_and_convert_args


def test_validate_and_convert_args_extra_positional() -> None:
    """Test validate_and_convert_args passes through extra positional args."""
    xp = XPrompt(
        name="test",
        content="hello",
        inputs=[InputArg(name="x", type=InputType.LINE)],
    )
    pos, _ = validate_and_convert_args(xp, ["a", "extra"], {})
    assert pos == ["a", "extra"]


def test_validate_and_convert_args_unknown_named() -> None:
    """Test validate_and_convert_args passes through unknown named args."""
    xp = XPrompt(
        name="test",
        content="hello",
        inputs=[InputArg(name="x", type=InputType.LINE)],
    )
    _, named = validate_and_convert_args(xp, [], {"unknown": "val"})
    assert named == {"unknown": "val"}


def test_validate_and_convert_args_positional_error() -> None:
    """Test validate_and_convert_args raises on positional conversion error."""
    xp = XPrompt(
        name="test",
        content="hello",
        inputs=[InputArg(name="n", type=InputType.INT)],
    )
    with pytest.raises(XPromptArgumentError, match="argument error"):
        validate_and_convert_args(xp, ["not_a_number"], {})


def test_validate_and_convert_args_named_error() -> None:
    """Test validate_and_convert_args raises on named conversion error."""
    xp = XPrompt(
        name="test",
        content="hello",
        inputs=[InputArg(name="n", type=InputType.INT)],
    )
    with pytest.raises(XPromptArgumentError, match="argument error"):
        validate_and_convert_args(xp, [], {"n": "not_a_number"})


def test_validate_and_convert_args_null_positional_arg_uses_default() -> None:
    """Test that positional arg 'null' is skipped so callee's default applies."""
    xp = XPrompt(
        name="test",
        content="hello",
        inputs=[InputArg(name="x", type=InputType.LINE, default="fallback")],
    )
    pos, named = validate_and_convert_args(xp, ["null"], {})
    assert pos == ["null"]
    assert named == {"x": "fallback"}


def test_validate_and_convert_args_null_value_no_default_skipped() -> None:
    """Test that 'null' with no callee default leaves arg out of result."""
    xp = XPrompt(
        name="test",
        content="hello",
        inputs=[InputArg(name="x", type=InputType.LINE)],
    )
    _, named = validate_and_convert_args(xp, [], {"x": "null"})
    assert "x" not in named


# Tests for skipped step context in execute_standalone_steps


def test_skipped_step_accessible_via_jinja2_default_filter() -> None:
    """Test that a subsequent step can reference a skipped step via default filter."""
    from sase.main.query_handler._standalone_steps import execute_standalone_steps
    from sase.xprompt.workflow_models import WorkflowStep

    steps = [
        WorkflowStep(
            name="maybe_run",
            bash="echo 'success=true'",
            condition="{{ flag }}",
        ),
        WorkflowStep(
            name="report",
            bash="echo 'result={{ maybe_run.success | default(false) | string | lower }}'",
        ),
    ]
    context: dict[str, object] = {"flag": False}
    result = execute_standalone_steps(steps, context, "test_workflow")
    assert result["maybe_run"] == {}
    assert result["report"]["result"] == "false"


# Tests for render_template with boolean values


def test_render_template_bool_tojson_produces_python() -> None:
    """Test that tojson filter produces Python-compatible booleans/None."""
    result = render_template("{{ flag | tojson }}", {"flag": True})
    assert result == "True"
    result = render_template("{{ flag | tojson }}", {"flag": False})
    assert result == "False"
    result = render_template("{{ flag | tojson }}", {"flag": None})
    assert result == "None"


def test_chdir_handling_in_standalone_steps(tmp_path: Path) -> None:
    """Test that _chdir special output changes the working directory."""
    from sase.main.query_handler._standalone_steps import execute_standalone_steps
    from sase.xprompt.workflow_models import WorkflowStep

    target_dir = str(tmp_path)
    original_dir = os.getcwd()
    try:
        steps = [
            WorkflowStep(
                name="change_dir",
                bash=f"echo '_chdir={target_dir}'",
            ),
        ]
        context: dict[str, object] = {}
        result = execute_standalone_steps(steps, context, "test_workflow")
        assert os.getcwd() == target_dir
        # _chdir should be popped from output
        assert "_chdir" not in result["change_dir"]
    finally:
        os.chdir(original_dir)


def test_bool_roundtrip_bash_to_template() -> None:
    """End-to-end: bash output → parse → schema converts to bool → render with | string | lower."""
    from sase.xprompt.output_validation import (
        _convert_data_types,
        _convert_semantic_schema_to_json_schema,
    )

    # Simulate bash outputting success=true
    data = parse_bash_output("success=true")
    assert data == {"success": "true"}

    # Schema as produced by _parse_shortform_output from {success: bool}
    schema: dict[str, object] = {"properties": {"success": {"type": "bool"}}}
    _, type_map = _convert_semantic_schema_to_json_schema(schema)
    converted = _convert_data_types(data, schema, type_map, "")
    assert converted["success"] is True

    # Render with | string | lower — should produce lowercase "true"
    result = render_template("{{ s.success | string | lower }}", {"s": converted})
    assert result == "true"
