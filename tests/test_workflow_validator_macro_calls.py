"""Tests for macro call extraction and validation in workflow_validator."""

from sase.macro.models import InputArg, InputType, Macro
from sase.macro.workflow_models import (
    Workflow,
    WorkflowStep,
)
from sase.macro.workflow_validator_checks import (
    detect_unused_macro_inputs,
    detect_unused_macros,
    validate_macro_names,
)
from sase.macro.workflow_validator_extract import (
    _MacroCall,
    extract_macro_calls,
    validate_macro_call,
)


def testextract_macro_calls_with_args() -> None:
    """Test extracting macro with parenthesis args."""
    calls = extract_macro_calls('#bar(arg1, name="value")')
    assert len(calls) == 1
    assert calls[0].name == "bar"
    assert calls[0].positional_args == ["arg1"]
    assert calls[0].named_args == {"name": "value"}


def testextract_macro_calls_colon_syntax() -> None:
    """Test extracting macro with colon syntax."""
    calls = extract_macro_calls("#foo:myvalue")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].positional_args == ["myvalue"]
    assert calls[0].named_args == {}


def testextract_macro_calls_plus_syntax() -> None:
    """Test extracting macro with plus syntax."""
    calls = extract_macro_calls("#foo+")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].positional_args == ["true"]
    assert calls[0].named_args == {}


def testextract_macro_calls_fstring_placeholder() -> None:
    """Single-brace `{path}` placeholder counts as one positional arg."""
    calls = extract_macro_calls("#foo:{path}")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].positional_args == ["{path}"]
    assert calls[0].named_args == {}


def testextract_macro_calls_jinja_still_preferred_over_single_brace() -> None:
    """`{{ var }}` Jinja form keeps matching ahead of the new single-brace form."""
    calls = extract_macro_calls("#foo:{{ var }}")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].positional_args == ["{{ var }}"]
    assert calls[0].named_args == {}


def testextract_macro_calls_ignores_disabled_regions() -> None:
    """Macro-looking examples in disabled regions are not validation calls."""
    calls = extract_macro_calls(
        "live #real\n"
        "%xprompts_enabled:false\n"
        "#fake_xprompt\n"
        "#fake_arg:{{ missing }}\n"
        "%directive\n"
        "%xprompts_enabled:true\n"
    )

    assert [call.name for call in calls] == ["real"]


def testextract_macro_calls_preserves_bang_marker() -> None:
    """Validator diagnostics keep the original #! marker."""
    calls = extract_macro_calls("#!foo:{path}")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].marker == "#!"
    assert calls[0].raw_match == "#!foo:{path}"


def testvalidate_macro_call_fstring_placeholder_satisfies_required_arg() -> None:
    """An f-string-style colon arg satisfies a required positional input."""
    macro_def = Macro(
        name="split_file",
        content="{{ file_path }}",
        inputs=[InputArg(name="file_path", type=InputType.LINE)],
    )
    source = 'f"#split_file:{path}"'
    calls = extract_macro_calls(source)
    assert len(calls) == 1
    errors = validate_macro_call(calls[0], macro_def, "step1")
    assert errors == []


def testvalidate_macro_call_missing_required_arg() -> None:
    """Test validation detects missing required argument."""
    macro_def = Macro(
        name="test",
        content="{{ required_arg }}",
        inputs=[InputArg(name="required_arg", type=InputType.LINE)],
    )
    call = _MacroCall(
        name="test",
        positional_args=[],
        named_args={},
        raw_match="#test",
    )
    errors = validate_macro_call(call, macro_def, "step1")
    assert len(errors) == 1
    assert "missing required args" in errors[0]
    assert "required_arg" in errors[0]


def testvalidate_macro_call_unknown_named_arg() -> None:
    """Test validation detects unknown named argument."""
    macro_def = Macro(
        name="test",
        content="{{ known }}",
        inputs=[InputArg(name="known", type=InputType.LINE, default="default")],
    )
    call = _MacroCall(
        name="test",
        positional_args=[],
        named_args={"unknown_arg": "value"},
        raw_match='#test(unknown_arg="value")',
    )
    errors = validate_macro_call(call, macro_def, "step1")
    assert len(errors) == 1
    assert "has no input named 'unknown_arg'" in errors[0]
    assert "Available:" in errors[0]


def testvalidate_macro_call_too_many_positional_args() -> None:
    """Test validation detects too many positional arguments."""
    macro_def = Macro(
        name="test",
        content="{{ one }}",
        inputs=[InputArg(name="one", type=InputType.LINE)],
    )
    call = _MacroCall(
        name="test",
        positional_args=["first", "second", "third"],
        named_args={},
        raw_match="#test(first, second, third)",
    )
    errors = validate_macro_call(call, macro_def, "step1")
    assert len(errors) >= 1
    assert "3 positional args but only 1 inputs defined" in errors[0]


def testvalidate_macro_call_error_uses_original_marker() -> None:
    """Argument validation points at #! when that marker was used."""
    macro_def = Macro(
        name="test",
        content="{{ required_arg }}",
        inputs=[InputArg(name="required_arg", type=InputType.LINE)],
    )
    call = _MacroCall(
        name="test",
        positional_args=[],
        named_args={},
        raw_match="#!test",
        marker="#!",
    )
    errors = validate_macro_call(call, macro_def, "step1")
    assert len(errors) == 1
    assert "Step 'step1': #!test missing required args" in errors[0]


def testdetect_unused_macros_finds_unused() -> None:
    """Workflow-local macro never referenced → error."""
    workflow = Workflow(
        name="test",
        steps=[WorkflowStep(name="step1", bash="echo hi")],
        macros={
            "_unused": Macro(name="_unused", content="some content"),
        },
    )
    macros = dict(workflow.macros)
    errors = detect_unused_macros(workflow, macros)
    assert len(errors) == 1
    assert "_unused" in errors[0]


def testdetect_unused_macros_used_by_other_macro() -> None:
    """Macro referenced by another macro → no error."""
    workflow = Workflow(
        name="test",
        steps=[WorkflowStep(name="step1", agent="Use #_outer here")],
        macros={
            "_base": Macro(name="_base", content="base content"),
            "_outer": Macro(name="_outer", content="wraps #_base"),
        },
    )
    macros = dict(workflow.macros)
    errors = detect_unused_macros(workflow, macros)
    assert errors == []


def testdetect_unused_macro_inputs_finds_unused() -> None:
    """Macro input not in content → error."""
    workflow = Workflow(
        name="test",
        steps=[],
        macros={
            "_helper": Macro(
                name="_helper",
                content="no vars here",
                inputs=[InputArg(name="unused_arg", type=InputType.LINE)],
            ),
        },
    )
    errors = detect_unused_macro_inputs(workflow)
    assert len(errors) == 1
    assert "unused_arg" in errors[0]
    assert "_helper" in errors[0]


def testdetect_unused_macro_inputs_used() -> None:
    """Macro input referenced in content → no error."""
    workflow = Workflow(
        name="test",
        steps=[],
        macros={
            "_helper": Macro(
                name="_helper",
                content="Use {{ my_arg }} here",
                inputs=[InputArg(name="my_arg", type=InputType.LINE)],
            ),
        },
    )
    errors = detect_unused_macro_inputs(workflow)
    assert errors == []


def testvalidate_macro_names_missing_underscore() -> None:
    """Macro name without '_' prefix → error."""
    workflow = Workflow(
        name="test",
        steps=[WorkflowStep(name="step1", bash="echo hi")],
        macros={
            "foo": Macro(name="foo", content="some content"),
        },
    )
    errors = validate_macro_names(workflow)
    assert len(errors) == 1
    assert "foo" in errors[0]
    assert "must start with '_'" in errors[0]
    assert "'_foo'" in errors[0]


def test_workflow_local_macro_with_scope_resolves_step_outputs() -> None:
    """Workflow-local macros with Jinja2 refs resolve via scope."""
    from sase.macro.processor import process_macro_references

    macros = {
        "_research_files": Macro(
            name="_research_files",
            content="Files: {{ research.api_research.file_path }}",
        ),
    }
    scope = {
        "research": {
            "api_research": {"file_path": "/tmp/test.py"},
        },
    }
    result = process_macro_references(
        "Analyze #_research_files",
        extra_macros=macros,
        scope=scope,
    )
    assert "Files: /tmp/test.py" in result
    assert "#_research_files" not in result
