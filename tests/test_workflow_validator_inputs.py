"""Tests for input/variable collection in workflow_validator."""

import pytest

from sase.xprompt.models import InputArg, InputType
from sase.xprompt.workflow_models import Workflow, WorkflowStep
from sase.xprompt.workflow_validator import validate_workflow
from sase.xprompt.workflow_validator_checks import detect_unused_inputs
from sase.xprompt.workflow_validator_extract import (
    collect_used_variables,
    extract_template_refs,
)


def test_extract_template_refs_empty_jinja_block_is_empty() -> None:
    """Empty Jinja blocks should not crash variable extraction."""
    assert extract_template_refs("{{}}") == []


def test_extract_template_refs_ignores_disabled_regions() -> None:
    """Jinja-looking content in disabled regions is not a variable reference."""
    content = (
        "live {{ keep }}\n"
        "%xprompts_enabled:false\n"
        "{{ disabled }}\n"
        "{{}}\n"
        "{% bad %}\n"
        "%xprompts_enabled:true\n"
    )

    assert extract_template_refs(content) == ["keep"]


def testcollect_used_variables_multiple_sources() -> None:
    """Test collecting variables from multiple step types."""
    workflow = Workflow(
        name="test",
        inputs=[
            InputArg(name="bash_var", type=InputType.LINE),
            InputArg(name="prompt_var", type=InputType.LINE),
            InputArg(name="python_var", type=InputType.LINE),
        ],
        steps=[
            WorkflowStep(name="s1", bash="echo {{ bash_var }}"),
            WorkflowStep(name="s2", agent="{{ prompt_var }}"),
            WorkflowStep(name="s3", python="print({{ python_var }})"),
        ],
    )
    used = collect_used_variables(workflow)
    assert "bash_var" in used
    assert "prompt_var" in used
    assert "python_var" in used


def testcollect_used_variables_ignores_disabled_regions() -> None:
    """Disabled-region template refs are inert during workflow validation."""
    workflow = Workflow(
        name="test",
        inputs=[InputArg(name="live_var", type=InputType.LINE)],
        steps=[
            WorkflowStep(
                name="s1",
                agent=(
                    "{{ live_var }}\n"
                    "%xprompts_enabled:false\n"
                    "{{ disabled_var }}\n"
                    "{{}}\n"
                    "#fake_xprompt\n"
                    "%directive\n"
                    "%xprompts_enabled:true\n"
                ),
            )
        ],
    )

    assert collect_used_variables(workflow) == {"live_var"}


def test_validate_workflow_allows_disabled_qa_block_with_empty_jinja(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression for agent resumes containing disabled Q&A text with ``{{}}``."""
    monkeypatch.setattr("sase.xprompt.workflow_validator.get_all_xprompts", lambda: {})
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="question_response",
                agent=(
                    "%xprompts_enabled:false\n"
                    "# Previous answer\n"
                    "{{  }} -> {{}}\n"
                    "{{ undefined_var }}\n"
                    "#fake_xprompt\n"
                    "%directive\n"
                    "%xprompts_enabled:true\n"
                ),
            )
        ],
    )

    validate_workflow(workflow)


def testcollect_used_variables_from_condition() -> None:
    """Test that variables in if: conditions are collected."""
    workflow = Workflow(
        name="test",
        inputs=[InputArg(name="flag", type=InputType.BOOL)],
        steps=[
            WorkflowStep(
                name="step1",
                bash="echo hello",
                condition="{{ flag }}",
            )
        ],
    )
    used = collect_used_variables(workflow)
    assert "flag" in used


def testcollect_used_variables_from_for_loop() -> None:
    """Test that variables in for: expressions are collected."""
    workflow = Workflow(
        name="test",
        inputs=[InputArg(name="items_list", type=InputType.LINE)],
        steps=[
            WorkflowStep(
                name="step1",
                bash="echo {{ item }}",
                for_loop={"item": "{{ items_list }}"},
            )
        ],
    )
    used = collect_used_variables(workflow)
    assert "items_list" in used


def testdetect_unused_inputs_finds_unused() -> None:
    """Test detection of unused inputs."""
    workflow = Workflow(
        name="test",
        inputs=[
            InputArg(name="used_input", type=InputType.LINE),
            InputArg(name="unused_input", type=InputType.LINE),
        ],
        steps=[WorkflowStep(name="step1", bash="echo {{ used_input }}")],
    )
    used_vars = collect_used_variables(workflow)
    unused = detect_unused_inputs(workflow, used_vars)
    assert "unused_input" in unused
    assert "used_input" not in unused


def testdetect_unused_inputs_ignores_step_inputs() -> None:
    """Test that step inputs (auto-generated) are not flagged as unused."""
    workflow = Workflow(
        name="test",
        inputs=[
            InputArg(name="regular_input", type=InputType.LINE),
            InputArg(name="step_input", type=InputType.LINE, is_step_input=True),
        ],
        steps=[WorkflowStep(name="step1", bash="echo hi")],
    )
    used_vars = collect_used_variables(workflow)
    unused = detect_unused_inputs(workflow, used_vars)
    # step_input should not be in unused even though not referenced
    assert "step_input" not in unused
    # regular_input is unused and should be detected
    assert "regular_input" in unused
