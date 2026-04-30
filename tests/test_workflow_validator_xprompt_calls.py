"""Tests for xprompt call extraction and validation in workflow_validator."""

from sase.xprompt.models import InputArg, InputType, XPrompt
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowStep,
)
from sase.xprompt.workflow_validator_checks import (
    detect_unused_xprompt_inputs,
    detect_unused_xprompts,
    validate_xprompt_names,
)
from sase.xprompt.workflow_validator_extract import (
    _XPromptCall,
    extract_xprompt_calls,
    validate_xprompt_call,
)


def testextract_xprompt_calls_with_args() -> None:
    """Test extracting xprompt with parenthesis args."""
    calls = extract_xprompt_calls('#bar(arg1, name="value")')
    assert len(calls) == 1
    assert calls[0].name == "bar"
    assert calls[0].positional_args == ["arg1"]
    assert calls[0].named_args == {"name": "value"}


def testextract_xprompt_calls_colon_syntax() -> None:
    """Test extracting xprompt with colon syntax."""
    calls = extract_xprompt_calls("#foo:myvalue")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].positional_args == ["myvalue"]
    assert calls[0].named_args == {}


def testextract_xprompt_calls_plus_syntax() -> None:
    """Test extracting xprompt with plus syntax."""
    calls = extract_xprompt_calls("#foo+")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].positional_args == ["true"]
    assert calls[0].named_args == {}


def testextract_xprompt_calls_fstring_placeholder() -> None:
    """Single-brace `{path}` placeholder counts as one positional arg."""
    calls = extract_xprompt_calls("#foo:{path}")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].positional_args == ["{path}"]
    assert calls[0].named_args == {}


def testextract_xprompt_calls_jinja_still_preferred_over_single_brace() -> None:
    """`{{ var }}` Jinja form keeps matching ahead of the new single-brace form."""
    calls = extract_xprompt_calls("#foo:{{ var }}")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].positional_args == ["{{ var }}"]
    assert calls[0].named_args == {}


def testextract_xprompt_calls_preserves_bang_marker() -> None:
    """Validator diagnostics keep the original #! marker."""
    calls = extract_xprompt_calls("#!foo:{path}")
    assert len(calls) == 1
    assert calls[0].name == "foo"
    assert calls[0].marker == "#!"
    assert calls[0].raw_match == "#!foo:{path}"


def testvalidate_xprompt_call_fstring_placeholder_satisfies_required_arg() -> None:
    """An f-string-style colon arg satisfies a required positional input."""
    xprompt = XPrompt(
        name="pysplit",
        content="{{ path }}",
        inputs=[InputArg(name="path", type=InputType.LINE)],
    )
    source = 'f"#pysplit:{path}"'
    calls = extract_xprompt_calls(source)
    assert len(calls) == 1
    errors = validate_xprompt_call(calls[0], xprompt, "step1")
    assert errors == []


def testvalidate_xprompt_call_missing_required_arg() -> None:
    """Test validation detects missing required argument."""
    xprompt = XPrompt(
        name="test",
        content="{{ required_arg }}",
        inputs=[InputArg(name="required_arg", type=InputType.LINE)],
    )
    call = _XPromptCall(
        name="test",
        positional_args=[],
        named_args={},
        raw_match="#test",
    )
    errors = validate_xprompt_call(call, xprompt, "step1")
    assert len(errors) == 1
    assert "missing required args" in errors[0]
    assert "required_arg" in errors[0]


def testvalidate_xprompt_call_unknown_named_arg() -> None:
    """Test validation detects unknown named argument."""
    xprompt = XPrompt(
        name="test",
        content="{{ known }}",
        inputs=[InputArg(name="known", type=InputType.LINE, default="default")],
    )
    call = _XPromptCall(
        name="test",
        positional_args=[],
        named_args={"unknown_arg": "value"},
        raw_match='#test(unknown_arg="value")',
    )
    errors = validate_xprompt_call(call, xprompt, "step1")
    assert len(errors) == 1
    assert "has no input named 'unknown_arg'" in errors[0]
    assert "Available:" in errors[0]


def testvalidate_xprompt_call_too_many_positional_args() -> None:
    """Test validation detects too many positional arguments."""
    xprompt = XPrompt(
        name="test",
        content="{{ one }}",
        inputs=[InputArg(name="one", type=InputType.LINE)],
    )
    call = _XPromptCall(
        name="test",
        positional_args=["first", "second", "third"],
        named_args={},
        raw_match="#test(first, second, third)",
    )
    errors = validate_xprompt_call(call, xprompt, "step1")
    assert len(errors) >= 1
    assert "3 positional args but only 1 inputs defined" in errors[0]


def testvalidate_xprompt_call_error_uses_original_marker() -> None:
    """Argument validation points at #! when that marker was used."""
    xprompt = XPrompt(
        name="test",
        content="{{ required_arg }}",
        inputs=[InputArg(name="required_arg", type=InputType.LINE)],
    )
    call = _XPromptCall(
        name="test",
        positional_args=[],
        named_args={},
        raw_match="#!test",
        marker="#!",
    )
    errors = validate_xprompt_call(call, xprompt, "step1")
    assert len(errors) == 1
    assert "Step 'step1': #!test missing required args" in errors[0]


def testdetect_unused_xprompts_finds_unused() -> None:
    """Workflow-local xprompt never referenced → error."""
    workflow = Workflow(
        name="test",
        steps=[WorkflowStep(name="step1", bash="echo hi")],
        xprompts={
            "_unused": XPrompt(name="_unused", content="some content"),
        },
    )
    xprompts = dict(workflow.xprompts)
    errors = detect_unused_xprompts(workflow, xprompts)
    assert len(errors) == 1
    assert "_unused" in errors[0]


def testdetect_unused_xprompts_used_by_other_xprompt() -> None:
    """Xprompt referenced by another xprompt → no error."""
    workflow = Workflow(
        name="test",
        steps=[WorkflowStep(name="step1", agent="Use #_outer here")],
        xprompts={
            "_base": XPrompt(name="_base", content="base content"),
            "_outer": XPrompt(name="_outer", content="wraps #_base"),
        },
    )
    xprompts = dict(workflow.xprompts)
    errors = detect_unused_xprompts(workflow, xprompts)
    assert errors == []


def testdetect_unused_xprompt_inputs_finds_unused() -> None:
    """Xprompt input not in content → error."""
    workflow = Workflow(
        name="test",
        steps=[],
        xprompts={
            "_helper": XPrompt(
                name="_helper",
                content="no vars here",
                inputs=[InputArg(name="unused_arg", type=InputType.LINE)],
            ),
        },
    )
    errors = detect_unused_xprompt_inputs(workflow)
    assert len(errors) == 1
    assert "unused_arg" in errors[0]
    assert "_helper" in errors[0]


def testdetect_unused_xprompt_inputs_used() -> None:
    """Xprompt input referenced in content → no error."""
    workflow = Workflow(
        name="test",
        steps=[],
        xprompts={
            "_helper": XPrompt(
                name="_helper",
                content="Use {{ my_arg }} here",
                inputs=[InputArg(name="my_arg", type=InputType.LINE)],
            ),
        },
    )
    errors = detect_unused_xprompt_inputs(workflow)
    assert errors == []


def testvalidate_xprompt_names_missing_underscore() -> None:
    """Xprompt name without '_' prefix → error."""
    workflow = Workflow(
        name="test",
        steps=[WorkflowStep(name="step1", bash="echo hi")],
        xprompts={
            "foo": XPrompt(name="foo", content="some content"),
        },
    )
    errors = validate_xprompt_names(workflow)
    assert len(errors) == 1
    assert "foo" in errors[0]
    assert "must start with '_'" in errors[0]
    assert "'_foo'" in errors[0]


def test_workflow_local_xprompt_with_scope_resolves_step_outputs() -> None:
    """Workflow-local xprompts with Jinja2 refs resolve via scope."""
    from sase.xprompt.processor import process_xprompt_references

    xprompts = {
        "_research_files": XPrompt(
            name="_research_files",
            content="Files: {{ research.api_research.file_path }}",
        ),
    }
    scope = {
        "research": {
            "api_research": {"file_path": "/tmp/test.py"},
        },
    }
    result = process_xprompt_references(
        "Analyze #_research_files",
        extra_xprompts=xprompts,
        scope=scope,
    )
    assert "Files: /tmp/test.py" in result
    assert "#_research_files" not in result
