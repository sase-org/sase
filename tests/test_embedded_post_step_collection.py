"""Tests for _collect_embedded_step_outputs() in workflow_executor_steps_prompt."""

from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_executor_steps_embedded import EmbeddedWorkflowInfo
from sase.xprompt.workflow_executor_steps_prompt import (
    _collect_embedded_step_outputs,
)
from sase.xprompt.workflow_models import WorkflowStep


def _make_info(
    ctx: dict[str, object],
    post_steps: list[WorkflowStep] | None = None,
) -> EmbeddedWorkflowInfo:
    """Create an EmbeddedWorkflowInfo with the given context for testing."""
    return EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=post_steps or [],
        context=ctx,
        workflow_name="test",
    )


def _make_step(
    name: str,
    output_properties: dict[str, dict[str, str]] | None = None,
) -> WorkflowStep:
    """Create a WorkflowStep with an optional OutputSpec."""
    output = None
    if output_properties is not None:
        output = OutputSpec(
            type="json_schema",
            schema={"properties": output_properties},
        )
    return WorkflowStep(name=name, output=output)


def test_first_diff_path_wins_across_workflows() -> None:
    """First non-empty path-typed field wins across multiple workflows."""
    step1 = _make_step("step", {"diff_path": {"type": "path"}})
    step2 = _make_step("step", {"diff_path": {"type": "path"}})
    ctx1: dict[str, object] = {"step": {"diff_path": "/tmp/first.diff"}}
    ctx2: dict[str, object] = {"step": {"diff_path": "/tmp/second.diff"}}
    diff_path, meta = _collect_embedded_step_outputs(
        [_make_info(ctx1, post_steps=[step1]), _make_info(ctx2, post_steps=[step2])]
    )
    assert diff_path == "/tmp/first.diff"


def test_empty_diff_path_ignored() -> None:
    """Empty string path value is treated as absent."""
    step = _make_step("step", {"diff_path": {"type": "path"}})
    ctx: dict[str, object] = {"step": {"diff_path": ""}}
    diff_path, meta = _collect_embedded_step_outputs(
        [_make_info(ctx, post_steps=[step])]
    )
    assert diff_path is None


def test_no_output_spec_skips_path_extraction() -> None:
    """Steps without OutputSpec skip path extraction but still collect meta."""
    step = _make_step("step")  # No output spec
    ctx: dict[str, object] = {"step": {"diff_path": "/tmp/test.diff", "meta_id": "abc"}}
    diff_path, meta = _collect_embedded_step_outputs(
        [_make_info(ctx, post_steps=[step])]
    )
    assert diff_path is None
    assert meta == {"meta_id": "abc"}


def test_step_not_in_context_skipped() -> None:
    """Steps whose name isn't in context are silently skipped."""
    step = _make_step("missing_step", {"path_field": {"type": "path"}})
    ctx: dict[str, object] = {}
    diff_path, meta = _collect_embedded_step_outputs(
        [_make_info(ctx, post_steps=[step])]
    )
    assert diff_path is None
    assert meta == {}
