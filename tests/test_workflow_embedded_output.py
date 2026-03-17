"""Tests for embedded workflow output propagation."""

from typing import Any

from sase.xprompt.models import OutputSpec
from sase.xprompt.workflow_executor_steps_embedded import (
    EmbeddedWorkflowInfo,
    EmbeddedWorkflowMixin,
    map_output_by_type,
)
from sase.xprompt.workflow_models import StepState, StepStatus, WorkflowStep


def _make_output_spec(fields: dict[str, str]) -> OutputSpec:
    """Helper to create an OutputSpec from {name: type} pairs."""
    return OutputSpec(
        type="json_schema",
        schema={"properties": {k: {"type": v} for k, v in fields.items()}},
    )


def _make_step_state(name: str, output: dict[str, Any] | None = None) -> StepState:
    """Helper to create a StepState."""
    return StepState(name=name, status=StepStatus.COMPLETED, output=output)


class _FakeMixin(EmbeddedWorkflowMixin):
    """Minimal fake that provides the context dict and delegates to the real method."""

    def __init__(self, context: dict[str, Any]) -> None:
        self.context = context  # type: ignore[assignment]


def _call_propagate(
    context: dict[str, Any],
    embedded_workflows: list[EmbeddedWorkflowInfo],
    step: WorkflowStep,
    step_state: StepState,
) -> None:
    """Call _propagate_last_embedded_output via the fake mixin."""
    fake = _FakeMixin(context)
    fake._propagate_last_embedded_output(embedded_workflows, step, step_state)


# ============================================================================
# EmbeddedWorkflowInfo dataclass basics
# ============================================================================


def test_embedded_workflow_info_defaults() -> None:
    """Test EmbeddedWorkflowInfo default values."""
    info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[],
        context={},
        workflow_name="test",
    )
    assert info.nested_step_name is None
    assert info.workflow_name == "test"
    assert info.pre_steps == []
    assert info.post_steps == []
    assert info.context == {}


def test_embedded_workflow_info_with_nested_step_name() -> None:
    """Test EmbeddedWorkflowInfo with nested_step_name set."""
    info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[],
        context={"key": "val"},
        workflow_name="file",
        nested_step_name="prior_art",
    )
    assert info.nested_step_name == "prior_art"


# ============================================================================
# map_output_by_type tests
# ============================================================================


def testmap_output_by_type_empty_parent() -> None:
    """Test that mapping returns None for empty parent spec."""
    parent_spec = OutputSpec(type="json_schema", schema={"properties": {}})
    embedded_spec = _make_output_spec({"file_path": "path"})
    embedded_output = {"file_path": "/tmp/test.md"}

    result = map_output_by_type(parent_spec, embedded_spec, embedded_output)
    assert result is None


# ============================================================================
# _propagate_last_embedded_output tests
# ============================================================================


def test_propagate_remaps_different_key_names() -> None:
    """Test propagation remaps values when key names differ but types match."""
    post_step = WorkflowStep(
        name="verify_file",
        bash='echo "file_path=test.md"',
        output=_make_output_spec({"file_path": "path"}),
    )
    info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[post_step],
        context={"verify_file": {"file_path": "/tmp/plan-240101.md"}},
        workflow_name="file",
    )

    # Parent uses a different key name but same type
    parent_step = WorkflowStep(
        name="plan",
        agent="write a plan",
        output=_make_output_spec({"plan_path": "path"}),
    )
    step_state = _make_step_state("plan", output={"_raw": "response"})
    context: dict[str, Any] = {"plan": {"_raw": "response"}}

    _call_propagate(context, [info], parent_step, step_state)

    assert step_state.output == {"plan_path": "/tmp/plan-240101.md"}
    assert context["plan"] == {"plan_path": "/tmp/plan-240101.md"}


def test_propagate_noop_when_parent_has_no_output() -> None:
    """Test no propagation when parent step has no output spec."""
    post_step = WorkflowStep(
        name="verify",
        bash='echo "file_path=test.md"',
        output=_make_output_spec({"file_path": "path"}),
    )
    info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[post_step],
        context={"verify": {"file_path": "test.md"}},
        workflow_name="file",
    )

    parent_step = WorkflowStep(name="plan", agent="write a plan")  # no output
    step_state = _make_step_state("plan", output={"_raw": "response"})
    context: dict[str, Any] = {"plan": {"_raw": "response"}}

    _call_propagate(context, [info], parent_step, step_state)

    assert step_state.output == {"_raw": "response"}
    assert context["plan"] == {"_raw": "response"}


def test_propagate_noop_when_embedded_post_step_has_no_output() -> None:
    """Test no propagation when embedded post-step has no output spec."""
    post_step = WorkflowStep(
        name="verify",
        bash='echo "done"',
        # no output spec
    )
    info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[post_step],
        context={"verify": {"file_path": "test.md"}},
        workflow_name="file",
    )

    parent_step = WorkflowStep(
        name="plan",
        agent="write a plan",
        output=_make_output_spec({"file_path": "path"}),
    )
    step_state = _make_step_state("plan", output={"_raw": "response"})
    context: dict[str, Any] = {"plan": {"_raw": "response"}}

    _call_propagate(context, [info], parent_step, step_state)

    assert step_state.output == {"_raw": "response"}


def test_propagate_noop_when_output_types_dont_match() -> None:
    """Test no propagation when output types don't match."""
    post_step = WorkflowStep(
        name="verify",
        bash='echo "url=http://example.com"',
        output=_make_output_spec({"url": "text"}),
    )
    info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[post_step],
        context={"verify": {"url": "http://example.com"}},
        workflow_name="file",
    )

    parent_step = WorkflowStep(
        name="plan",
        agent="write a plan",
        output=_make_output_spec({"file_path": "path"}),  # wants path, not text
    )
    step_state = _make_step_state("plan", output={"_raw": "response"})
    context: dict[str, Any] = {"plan": {"_raw": "response"}}

    _call_propagate(context, [info], parent_step, step_state)

    assert step_state.output == {"_raw": "response"}


def test_propagate_noop_when_no_embedded_workflows() -> None:
    """Test no propagation when embedded_workflows is empty."""
    parent_step = WorkflowStep(
        name="plan",
        agent="write a plan",
        output=_make_output_spec({"file_path": "path"}),
    )
    step_state = _make_step_state("plan", output={"_raw": "response"})
    context: dict[str, Any] = {"plan": {"_raw": "response"}}

    _call_propagate(context, [], parent_step, step_state)

    assert step_state.output == {"_raw": "response"}


def test_propagate_skips_non_matching_wraps_all_workflow() -> None:
    """Test propagation finds the right embedded workflow when wraps_all is last.

    When the embedded_workflows list has a content-producing workflow (#file)
    followed by a wraps_all teardown workflow (#hg) whose output doesn't
    type-match, propagation should use the earlier matching workflow.
    """
    # #file workflow — has matching path output
    file_post_step = WorkflowStep(
        name="verify_file",
        bash='echo "file_path=test.md"',
        output=_make_output_spec({"file_path": "path"}),
    )
    file_info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[file_post_step],
        context={"verify_file": {"file_path": "/tmp/new_cl_desc-240101.md"}},
        workflow_name="file",
    )

    # #hg workflow (wraps_all, appended at end) — no matching output
    release_post_step = WorkflowStep(
        name="release",
        python='print("released")',
        output=_make_output_spec({"released": "bool"}),
    )
    hg_info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[release_post_step],
        context={"release": {"released": True}},
        workflow_name="hg",
    )

    parent_step = WorkflowStep(
        name="gen_desc",
        agent="generate description",
        output=_make_output_spec({"desc_file": "path"}),
    )
    step_state = _make_step_state("gen_desc", output={"_raw": "response"})
    context: dict[str, Any] = {"gen_desc": {"_raw": "response"}}

    # List order: [#file, #hg] — #hg is last (wraps_all goes at end)
    _call_propagate(context, [file_info, hg_info], parent_step, step_state)

    assert step_state.output == {"desc_file": "/tmp/new_cl_desc-240101.md"}
    assert context["gen_desc"] == {"desc_file": "/tmp/new_cl_desc-240101.md"}


def test_propagate_noop_when_no_post_steps() -> None:
    """Test no propagation when embedded workflow has no post-steps."""
    info = EmbeddedWorkflowInfo(
        pre_steps=[],
        post_steps=[],
        context={},
        workflow_name="file",
    )

    parent_step = WorkflowStep(
        name="plan",
        agent="write a plan",
        output=_make_output_spec({"file_path": "path"}),
    )
    step_state = _make_step_state("plan", output={"_raw": "response"})
    context: dict[str, Any] = {"plan": {"_raw": "response"}}

    _call_propagate(context, [info], parent_step, step_state)

    assert step_state.output == {"_raw": "response"}
