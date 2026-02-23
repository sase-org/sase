"""Tests for output detection and template refs in workflow_validator."""

import pytest
from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_models import (
    ParallelConfig,
    Workflow,
    WorkflowStep,
    WorkflowValidationError,
)
from sase.xprompt.workflow_validator import (
    _detect_unused_outputs,
)


def _make_output() -> OutputSpec:
    """Create a minimal OutputSpec for testing."""
    return OutputSpec(
        type="json_schema",
        schema={"properties": {"result": {"type": "string"}}},
    )


def test_detect_unused_outputs_used_no_error() -> None:
    """Step output referenced by next step → no error."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="producer", bash="echo hi", output=_make_output()),
            WorkflowStep(name="consumer", bash="echo {{ producer.result }}"),
        ],
    )
    errors = _detect_unused_outputs(workflow)
    assert errors == []


def test_detect_unused_outputs_prompt_part_last_post_step_exempt() -> None:
    """prompt_part workflow, last post-step exempt."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="pre", bash="echo pre"),
            WorkflowStep(name="main", prompt_part="Do something"),
            WorkflowStep(name="post_last", bash="echo post", output=_make_output()),
        ],
    )
    errors = _detect_unused_outputs(workflow)
    assert errors == []


def test_detect_unused_outputs_parallel_nested_unused() -> None:
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
    errors = _detect_unused_outputs(workflow)
    assert len(errors) == 1
    assert "research.task_b" in errors[0]


def test_detect_unused_outputs_parallel_join_array_skips_nested() -> None:
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
    errors = _detect_unused_outputs(workflow)
    assert errors == []


def test_detect_unused_outputs_whole_step_ref() -> None:
    """{{ step | tojson }} (no dot) → marks step used."""
    workflow = Workflow(
        name="test",
        steps=[
            WorkflowStep(name="data", bash="echo hi", output=_make_output()),
            WorkflowStep(name="use_it", bash="echo {{ data | tojson }}"),
        ],
    )
    errors = _detect_unused_outputs(workflow)
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
