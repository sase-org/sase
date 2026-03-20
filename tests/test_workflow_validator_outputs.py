"""Tests for output detection, template refs, and cross-step field validation."""

import pytest
from sase.xprompt.models import OutputSpec, XPrompt
from sase.xprompt.workflow_models import (
    LoopConfig,
    ParallelConfig,
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)
from sase.xprompt.workflow_validator_checks import (
    detect_unused_outputs,
    validate_cross_step_field_refs,
)


def _make_output() -> OutputSpec:
    """Create a minimal OutputSpec for testing."""
    return OutputSpec(
        type="json_schema",
        schema={"properties": {"result": {"type": "string"}}},
    )


def testdetect_unused_outputs_used_no_error() -> None:
    """Step output referenced by next step → no error."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="producer", bash="echo hi", output=_make_output()),
            WorkflowStep(name="consumer", bash="echo {{ producer.result }}"),
        ],
    )
    errors = detect_unused_outputs(workflow)
    assert errors == []


def testdetect_unused_outputs_prompt_part_last_post_step_exempt() -> None:
    """prompt_part workflow, last post-step exempt."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="pre", bash="echo pre"),
            WorkflowStep(name="main", prompt_part="Do something"),
            WorkflowStep(name="post_last", bash="echo post", output=_make_output()),
        ],
    )
    errors = detect_unused_outputs(workflow)
    assert errors == []


def testdetect_unused_outputs_parallel_nested_unused() -> None:
    """Nested step output never referenced → error."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="research",
                parallel_config=ParallelConfig(
                    steps=[
                        WorkflowStep(
                            name="task_a",
                            bash="echo a",
                            output=_make_output(),
                        ),
                        WorkflowStep(
                            name="task_b",
                            bash="echo b",
                            output=_make_output(),
                        ),
                    ]
                ),
            ),
            WorkflowStep(
                name="verify",
                bash="echo {{ research.task_a.result }}",
            ),
        ],
    )
    errors = detect_unused_outputs(workflow)
    assert len(errors) == 1
    assert "research.task_b" in errors[0]


def testdetect_unused_outputs_parallel_join_array_skips_nested() -> None:
    """join: array → nested outputs not tracked individually."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="parallel_step",
                join="array",
                parallel_config=ParallelConfig(
                    steps=[
                        WorkflowStep(
                            name="first",
                            bash="echo 1",
                            output=_make_output(),
                        ),
                        WorkflowStep(
                            name="second",
                            bash="echo 2",
                            output=_make_output(),
                        ),
                    ]
                ),
            ),
            WorkflowStep(
                name="verify",
                bash="echo {{ parallel_step | length }}",
            ),
        ],
    )
    errors = detect_unused_outputs(workflow)
    assert errors == []


def testdetect_unused_outputs_whole_step_ref() -> None:
    """{{ step | tojson }} (no dot) → marks step used."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="data", bash="echo hi", output=_make_output()),
            WorkflowStep(name="use_it", bash="echo {{ data | tojson }}"),
        ],
    )
    errors = detect_unused_outputs(workflow)
    assert errors == []


def test_validate_workflow_raises_on_unused_output() -> None:
    """Integration: validate_workflow() raises error for unused output."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="unused_out", bash="echo hi", output=_make_output()),
            WorkflowStep(name="final", bash="echo done"),
        ],
    )
    with pytest.raises(WorkflowValidationError, match="unused_out"):
        from sase.xprompt.workflow_validator import validate_workflow

        validate_workflow(workflow)


# ── Cross-step field validation ──────────────────────────────────────────


def _make_output_with_fields(*fields: str) -> OutputSpec:
    """Create an OutputSpec with the given field names."""
    props = {f: {"type": "string"} for f in fields}
    return OutputSpec(type="json_schema", schema={"properties": props})


def test_cross_step_valid_field_ref() -> None:
    """Valid field reference → no error."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="build",
                bash="echo artifact_path=/tmp/a",
                output=_make_output_with_fields("artifact_path"),
            ),
            WorkflowStep(name="deploy", bash="deploy {{ build.artifact_path }}"),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert errors == []


def test_cross_step_typo_field_ref() -> None:
    """Typo in field name → error listing available fields."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="build",
                bash="echo artifact_path=/tmp/a",
                output=_make_output_with_fields("artifact_path"),
            ),
            WorkflowStep(name="deploy", bash="deploy {{ build.atrifact_path }}"),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert len(errors) == 1
    assert "atrifact_path" in errors[0]
    assert "artifact_path" in errors[0]


def test_cross_step_no_dot_ref_skipped() -> None:
    """{{ step | tojson }} (no field) → no field validation."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="data",
                bash="echo result=ok",
                output=_make_output_with_fields("result"),
            ),
            WorkflowStep(name="use", bash="echo {{ data | tojson }}"),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert errors == []


def test_cross_step_self_ref_in_repeat() -> None:
    """Self-reference in repeat loop validated against own output."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="retry",
                bash="echo success=true",
                output=_make_output_with_fields("success"),
                repeat_config=LoopConfig(
                    condition="{{ retry.success }}", max_iterations=5
                ),
            ),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert errors == []


def test_cross_step_self_ref_typo_in_repeat() -> None:
    """Typo in self-reference repeat condition → error."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="retry",
                bash="echo success=true",
                output=_make_output_with_fields("success"),
                repeat_config=LoopConfig(
                    condition="{{ retry.sucess }}", max_iterations=5
                ),
            ),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert len(errors) == 1
    assert "sucess" in errors[0]


def test_cross_step_for_loop_var_not_checked() -> None:
    """For-loop variable access not confused with step field."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="build",
                bash="echo result={{ item.name }}",
                output=_make_output_with_fields("result"),
                for_loop={"item": "{{ items }}"},
                join="lastOf",
            ),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert errors == []


def test_cross_step_for_loop_array_join_skips_field_check() -> None:
    """Step with for + join=array → no field-level check."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="process",
                bash="echo result=ok",
                output=_make_output_with_fields("result"),
                for_loop={"item": "{{ items }}"},
                join="array",
            ),
            WorkflowStep(name="use", bash="echo {{ process | length }}"),
        ],
    )
    # "process" has for+array join, so it's not in step_fields.
    # Referencing process.bogus should NOT trigger an error.
    errors = validate_cross_step_field_refs(workflow)
    assert errors == []


def test_cross_step_parallel_nested_valid() -> None:
    """{{ parallel.nested.field }} with correct field → no error."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="research",
                parallel_config=ParallelConfig(
                    steps=[
                        WorkflowStep(
                            name="task_a",
                            bash="echo val=1",
                            output=_make_output_with_fields("val"),
                        ),
                    ]
                ),
            ),
            WorkflowStep(name="verify", bash="echo {{ research.task_a.val }}"),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert errors == []


def test_cross_step_parallel_nested_typo() -> None:
    """{{ parallel.nested.typo }} → error."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="research",
                parallel_config=ParallelConfig(
                    steps=[
                        WorkflowStep(
                            name="task_a",
                            bash="echo val=1",
                            output=_make_output_with_fields("val"),
                        ),
                    ]
                ),
            ),
            WorkflowStep(name="verify", bash="echo {{ research.task_a.value }}"),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert len(errors) == 1
    assert "value" in errors[0]
    assert "val" in errors[0]


def test_cross_step_compound_expression() -> None:
    """Multiple refs in one expression both validated."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="a",
                bash="echo ok=true",
                output=_make_output_with_fields("ok"),
            ),
            WorkflowStep(
                name="b",
                bash="echo ok=true",
                output=_make_output_with_fields("ok"),
            ),
            WorkflowStep(
                name="c",
                bash="echo {{ a.ok and b.nope }}",
            ),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert len(errors) == 1
    assert "b" in errors[0] and "nope" in errors[0]


def test_cross_step_condition_field_ref() -> None:
    """Field ref inside if: condition is validated."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="check",
                bash="echo ready=true",
                output=_make_output_with_fields("ready"),
            ),
            WorkflowStep(
                name="act",
                condition="{{ check.redy }}",
                bash="echo go",
            ),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert len(errors) == 1
    assert "redy" in errors[0]


def test_cross_step_xprompt_content_validated() -> None:
    """Field ref in workflow-local xprompt content is validated."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(
                name="setup",
                bash="echo path=/tmp",
                output=_make_output_with_fields("path"),
            ),
            WorkflowStep(name="run", agent="do stuff #_helper"),
        ],
        xprompts={
            "_helper": XPrompt(
                name="_helper",
                content="Use file at {{ setup.pth }}",
            ),
        },
    )
    errors = validate_cross_step_field_refs(workflow)
    assert len(errors) == 1
    assert "pth" in errors[0]
    assert "Xprompt '_helper'" in errors[0]


def test_cross_step_step_without_output_skipped() -> None:
    """Refs to steps without output schemas are not validated."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="setup", bash="echo hi"),  # no output
            WorkflowStep(name="use", bash="echo {{ setup.anything }}"),
        ],
    )
    errors = validate_cross_step_field_refs(workflow)
    assert errors == []
