"""Embedded workflow step execution mixin."""

from typing import TYPE_CHECKING, Any

from sase.xprompt.workflow_executor_steps_embedded_expand import (
    EmbeddedWorkflowExpandMixin,
)
from sase.xprompt.workflow_executor_steps_embedded_types import (
    EmbeddedWorkflowInfo,
    map_output_by_type,
)
from sase.xprompt.workflow_executor_types import HITLHandler, output_types_from_step
from sase.xprompt.workflow_executor_utils import render_template
from sase.xprompt.workflow_models import (
    StepState,
    StepStatus,
    Workflow,
    WorkflowExecutionError,
    WorkflowState,
    WorkflowStep,
)

# Re-export types for backward compatibility
from sase.xprompt.workflow_executor_steps_embedded_types import (  # noqa: F401
    PendingEmbeddedWorkflow,
    _WORKFLOW_REF_PATTERN,
)

if TYPE_CHECKING:
    from sase.xprompt.workflow_output import ParentStepContext, WorkflowOutputHandler

__all__ = [
    "EmbeddedWorkflowInfo",
    "EmbeddedWorkflowMixin",
    "PendingEmbeddedWorkflow",
    "_WORKFLOW_REF_PATTERN",
    "map_output_by_type",
]


class EmbeddedWorkflowMixin(EmbeddedWorkflowExpandMixin):
    """Mixin class providing embedded workflow execution.

    Inherits from EmbeddedWorkflowExpandMixin which provides prompt
    expansion logic (_expand_embedded_workflows_in_prompt).

    This mixin requires the following attributes on self:
        - workflow: Workflow
        - context: dict[str, Any]
        - artifacts_dir: str
        - hitl_handler: HITLHandler | None
        - output_handler: WorkflowOutputHandler | None
        - state: WorkflowState

    This mixin requires the following methods on self:
        - _get_step_type(step) -> str
        - _evaluate_condition(condition) -> bool
        - _save_prompt_step_marker(step_name, step_state, ...) -> None
        - _execute_prompt_step(step, step_state) -> bool
        - _execute_python_step(step, step_state) -> bool
        - _execute_bash_step(step, step_state) -> bool
    """

    # Type hints for attributes from WorkflowExecutor
    workflow: Workflow
    context: dict[str, Any]
    artifacts_dir: str
    hitl_handler: HITLHandler | None
    output_handler: "WorkflowOutputHandler | None"
    state: WorkflowState

    # Method type declarations for methods provided by other mixins/main class
    _get_step_type: Any  # (step: WorkflowStep) -> str
    _evaluate_condition: Any  # (condition: str) -> bool
    _save_prompt_step_marker: Any  # (step_name, step_state, ...) -> None
    _execute_prompt_step: Any  # (step, step_state) -> bool
    _execute_python_step: Any  # (step, step_state) -> bool
    _execute_bash_step: Any  # (step, step_state) -> bool

    def _execute_embedded_workflow_steps(
        self,
        steps: list[WorkflowStep],
        embedded_context: dict[str, Any],
        parent_step_name: str,
        parent_step_context: "ParentStepContext | None" = None,
        is_pre_prompt_step: bool = False,
        step_index_offset: int = 0,
        embedded_workflow_name: str | None = None,
    ) -> bool:
        """Execute steps from an embedded workflow.

        Runs steps inline as part of the containing workflow execution,
        accumulating outputs into the embedded workflow's context.

        Steps marked with ``finally_=True`` run even when a prior step has
        failed, mirroring the behavior of :meth:`WorkflowExecutor.execute`.

        Args:
            steps: List of workflow steps to execute.
            embedded_context: Context for the embedded workflow (args + outputs).
            parent_step_name: Name of the parent step for error messages.
            parent_step_context: Context for parent step numbering in output.
            is_pre_prompt_step: True if these are pre-prompt steps (before the main
                prompt), which should be hidden in the Agents tab.

        Returns:
            True if all steps succeeded, False if any failed.
        """
        del parent_step_name  # Unused but kept for API consistency
        total_steps = len(steps)
        has_finally_steps = any(s.finally_ for s in steps)
        hit_failure = False

        for i, step in enumerate(steps):
            # After a failure, skip non-finally steps
            if hit_failure and not step.finally_:
                embedded_context[step.name] = {}
                continue

            # Create a temporary step state for execution
            temp_state = StepState(name=step.name, status=StepStatus.PENDING)

            # Save original context and temporarily use embedded context
            original_context = self.context
            self.context = embedded_context

            try:
                # Determine step type for display
                step_type = self._get_step_type(step)

                # Evaluate if: condition
                if step.condition:
                    condition_result = self._evaluate_condition(step.condition)
                    if not condition_result:
                        temp_state.status = StepStatus.SKIPPED
                        # Notify output handler about skipped step
                        if self.output_handler:
                            self.output_handler.on_step_start(
                                step.name,
                                step_type,
                                step_index_offset + i,
                                total_steps,
                                condition=step.condition,
                                condition_result=False,
                                parent_step_context=parent_step_context,
                            )
                            self.output_handler.on_step_skip(
                                step.name, reason="condition false"
                            )
                        embedded_context[step.name] = {}
                        continue

                # Notify step start
                if self.output_handler:
                    self.output_handler.on_step_start(
                        step.name,
                        step_type,
                        step_index_offset + i,
                        total_steps,
                        parent_step_context=parent_step_context,
                    )

                temp_state.status = StepStatus.IN_PROGRESS

                self._current_embedded_workflow_name = embedded_workflow_name

                if step.is_agent_step():
                    success = self._execute_prompt_step(step, temp_state)
                elif step.is_python_step():
                    success = self._execute_python_step(step, temp_state)
                elif step.is_bash_step():
                    success = self._execute_bash_step(step, temp_state)
                else:
                    raise WorkflowExecutionError(
                        f"Unsupported step type in embedded workflow: {step.name}"
                    )

                if not success:
                    if not has_finally_steps:
                        return False
                    hit_failure = True
                    continue

                # Save marker for embedded step with parent context
                step_source = (
                    step.bash
                    if step_type == "bash"
                    else (step.python if step_type == "python" else None)
                )

                # Compute output_types from embedded step's OutputSpec
                output_types = output_types_from_step(step)

                self._save_prompt_step_marker(
                    step.name,
                    temp_state,
                    step_type,
                    step_source,
                    step_index_offset + i,
                    parent_step_index=(
                        parent_step_context.step_index if parent_step_context else None
                    ),
                    parent_total_steps=(
                        parent_step_context.total_steps if parent_step_context else None
                    ),
                    is_pre_prompt_step=is_pre_prompt_step,
                    hidden=step.hidden,
                    output_types=output_types,
                    embedded_workflow_name=embedded_workflow_name,
                )

                # Notify step complete
                if self.output_handler:
                    self.output_handler.on_step_complete(step.name, temp_state.output)

            finally:
                # Restore original context
                self.context = original_context
                # Sync state.context back to the parent context so that
                # workflow_state.json always reflects the parent's context
                # (including cl_name).  Without this, the state.context
                # retains the embedded workflow's context because step
                # execution methods call ``self.state.context = dict(self.context)``
                # while self.context points at the embedded context.
                self.state.context = dict(self.context)
                self._current_embedded_workflow_name = None

        return not hit_failure

    def _resolve_tagged_workflow_content(
        self,
        tagged_wf: Workflow,
        step_index_offset: int,
    ) -> tuple[str, int]:
        """Execute a tagged workflow's pre-steps and return its prompt_part.

        Tagged workflows (e.g. ``append_to_commit_and_propose``) may have
        pre-steps and conditional prompt_part steps.  This method executes the
        pre-steps, evaluates the ``if:`` condition, and returns the rendered
        prompt_part content.

        Returns:
            Tuple of (prompt_part_content, number_of_pre_steps_executed).
        """
        prompt_part_idx = tagged_wf.get_prompt_part_index()
        if prompt_part_idx is None:
            return "", 0

        prompt_part_step = tagged_wf.steps[prompt_part_idx]
        pre_steps = tagged_wf.get_pre_prompt_steps()

        # Simple case: no pre-steps and no condition — return content directly.
        if not pre_steps and not prompt_part_step.condition:
            return tagged_wf.get_prompt_part_content(), 0

        # Execute pre-steps to build context for the condition / template.
        tagged_ctx: dict[str, Any] = {}
        if pre_steps:
            from sase.xprompt.workflow_output import ParentStepContext

            parent_ctx = ParentStepContext(
                step_index=self.state.current_step_index,
                total_steps=len(self.workflow.steps),
            )
            success = self._execute_embedded_workflow_steps(
                pre_steps,
                tagged_ctx,
                f"tagged:{tagged_wf.name}",
                parent_step_context=parent_ctx,
                is_pre_prompt_step=True,
                step_index_offset=step_index_offset,
                embedded_workflow_name=tagged_wf.name,
            )
            if not success:
                return "", len(pre_steps)

        # Evaluate if: condition on the prompt_part step.
        if prompt_part_step.condition:
            rendered_cond = render_template(prompt_part_step.condition, tagged_ctx)
            cond_str = rendered_cond.strip().lower()
            if cond_str in ("", "false", "none", "0", "[]", "{}"):
                return "", len(pre_steps)

        # Return content, rendered with the tagged context if available.
        content = prompt_part_step.prompt_part or ""
        if content and tagged_ctx:
            content = render_template(content, tagged_ctx)
        return content, len(pre_steps)

    def _propagate_last_embedded_output(
        self,
        embedded_workflows: list[EmbeddedWorkflowInfo],
        step: WorkflowStep,
        step_state: StepState,
    ) -> None:
        """Propagate an embedded workflow's output to the parent step.

        Searches through embedded workflows for the first one whose last
        post-step output can be type-matched to the parent step's declared
        ``output``.  The list is ordered rightmost-non-wraps_all first, so
        forward iteration naturally prefers the rightmost content-producing
        workflow over wraps_all teardown workflows appended at the end.

        Matching is by property **type** (not name), so a parent declaring
        ``{my_path: path}`` will match an embedded step declaring
        ``{file_path: path}``.

        Args:
            embedded_workflows: List of embedded workflow info from expansion.
            step: The parent prompt step.
            step_state: The parent step's runtime state.
        """
        if not step.output:
            return
        if not embedded_workflows:
            return

        for info in embedded_workflows:
            if not info.post_steps:
                continue

            last_post_step = info.post_steps[-1]
            if not last_post_step.output:
                continue

            embedded_output = info.context.get(last_post_step.name)
            if not isinstance(embedded_output, dict):
                continue

            mapped = map_output_by_type(
                step.output, last_post_step.output, embedded_output
            )
            if mapped is not None:
                step_state.output = mapped
                self.context[step.name] = mapped
                return
