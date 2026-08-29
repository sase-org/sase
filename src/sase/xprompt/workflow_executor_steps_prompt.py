"""Prompt step execution mixin.

Launch selection helpers live in ``workflow_executor_steps_prompt_launch``.
Embedded output helpers live in ``workflow_executor_steps_prompt_outputs``.
Prompt preprocessing lives in ``workflow_executor_steps_prompt_prepare``.
"""

import os
from typing import TYPE_CHECKING, Any

from sase.xprompt.workflow_executor_steps_prompt_launch import (
    resolve_prompt_step_launch_selection,
    update_root_agent_meta_from_launch,
)
from sase.xprompt.workflow_executor_steps_prompt_outputs import (
    absolutize_path_outputs,
    apply_embedded_outputs_to_parent,
    capture_vcs_diff,
    has_finally_post_steps,
    resolve_embedded_path_fields,
)
from sase.xprompt.workflow_executor_steps_prompt_prepare import PromptStepPrepareMixin
from sase.xprompt.workflow_executor_types import HITLHandler, output_types_from_step
from sase.xprompt.workflow_models import (
    StepState,
    StepStatus,
    Workflow,
    WorkflowExecutionError,
    WorkflowState,
    WorkflowStep,
)

if TYPE_CHECKING:
    from sase.xprompt.workflow_output import WorkflowOutputHandler

# Re-export for backward compatibility
__all__ = [
    "PromptStepMixin",
    "capture_vcs_diff",
]


class PromptStepMixin(PromptStepPrepareMixin):
    """Mixin class providing prompt step execution.

    This mixin requires the following attributes on self:
        - workflow: Workflow
        - context: dict[str, Any]
        - artifacts_dir: str
        - hitl_handler: HITLHandler | None
        - state: WorkflowState

    This mixin requires the following methods on self:
        - _save_state() -> None
        - _save_prompt_step_marker(step_name, step_state, ...) -> None
        - _expand_embedded_workflows_in_prompt(prompt) -> tuple
        - _execute_embedded_workflow_steps(steps, context, name, ...) -> bool
    """

    # Type hints for attributes from WorkflowExecutor
    workflow: Workflow
    context: dict[str, Any]
    artifacts_dir: str
    hitl_handler: HITLHandler | None
    output_handler: "WorkflowOutputHandler | None"
    state: WorkflowState
    inherited_model_override: str | None
    inherited_vcs_tag: str | None
    _agents_launched: int

    # Method type declarations for methods provided by other mixins/main class
    _save_state: Any  # () -> None
    _save_prompt_step_marker: Any  # (step_name, step_state, ...) -> None
    _expand_embedded_workflows_in_prompt: Any  # (prompt) -> tuple
    _execute_embedded_workflow_steps: Any  # (steps, context, name, ...) -> bool
    _propagate_last_embedded_output: (
        Any  # (embedded_workflows, step, step_state) -> None
    )
    _should_hitl: Any  # (step: WorkflowStep) -> bool

    def _execute_prompt_step(
        self,
        step: WorkflowStep,
        step_state: StepState,
    ) -> bool:
        """Execute a prompt step.

        Args:
            step: The workflow step definition.
            step_state: The runtime state for this step.

        Returns:
            True if step succeeded, False if rejected by user.
        """
        from sase.content import ensure_str_content
        from sase.llm_provider import invoke_agent
        from sase.xprompt import extract_structured_content

        prepared = self._prepare_prompt_step(step)
        expanded_prompt = prepared.expanded_prompt
        effective_directives = prepared.effective_directives
        embedded_workflows = prepared.embedded_workflows
        pre_step_count = prepared.pre_step_count
        pre_step_meta = prepared.pre_step_meta

        if pre_step_meta:
            step_state.output = dict(pre_step_meta)

        # Resolve the concrete provider/model/effort for this step's real
        # invocation. The first prompt step redeems the bootstrap reservation
        # when it still matches the effective routing directives; stale or
        # unavailable reservations fall back to inherited agent_meta, then a
        # fresh consuming resolution of default_model.
        from sase.llm_provider.provider_disable import get_active_provider_disables

        provider_disables = get_active_provider_disables() or None
        launch_selection = resolve_prompt_step_launch_selection(
            self.artifacts_dir,
            directives=effective_directives,
            provider_disables=provider_disables,
        )
        step_model = launch_selection.model
        step_llm_provider = launch_selection.provider
        step_reasoning_effort = launch_selection.reasoning_effort
        step_model_alias_trail = list(launch_selection.alias_trail)
        step_model_alias_origin = launch_selection.alias_origin
        step_model_alias = (
            effective_directives.model_alias if effective_directives.model else None
        )

        # Save initial marker to show step is running in TUI
        step_state.status = StepStatus.IN_PROGRESS
        self._save_prompt_step_marker(
            step.name,
            step_state,
            hidden=step.hidden,
            model=step_model,
            llm_provider=step_llm_provider,
            reasoning_effort=step_reasoning_effort,
            model_alias=step_model_alias,
            model_alias_trail=step_model_alias_trail,
            model_alias_origin=step_model_alias_origin,
        )

        if self.workflow.is_anonymous_workflow:
            # The anonymous workflow's single step is the top-level agent
            # invocation: reconcile agent_meta.json with the authoritative
            # selection so `sase agent list`, the ACE row, and any launch
            # reservation metadata written before this real invocation agree
            # with what actually ran.
            update_root_agent_meta_from_launch(
                self.artifacts_dir,
                directives=effective_directives,
                launch_selection=launch_selection,
            )

        # Check if any embedded workflow has finally-marked post-steps.
        # When present, those steps must run even if the agent invocation or
        # a non-finally post-step fails.
        _has_finally_post = has_finally_post_steps(embedded_workflows)

        # Invoke agent (skip preprocessing — we already did early+late)
        # Extract base workflow name (without project prefix) to avoid slashes in filenames
        base_name = (
            self.workflow.name.split("/")[-1]
            if "/" in self.workflow.name
            else self.workflow.name
        )
        context_cl_name = self.context.get("cl_name")
        branch_or_workspace = (
            context_cl_name
            if isinstance(context_cl_name, str) and context_cl_name
            else None
        )

        # -- Agent invocation + post-step section -------------------------
        # Wrapped so that finally-marked post-steps run on failure.
        _deferred_error: Exception | None = None
        _deferred_reject: bool = False
        response_path: str | None = None
        diff_path: str | None = None

        try:
            self._agents_launched += 1
            response = invoke_agent(
                expanded_prompt,
                agent_type=f"workflow-{base_name}-{step.name}",
                artifacts_dir=self.artifacts_dir,
                workflow=self.workflow.name,
                branch_or_workspace=branch_or_workspace,
                skip_preprocessing=True,
                directives=effective_directives,
                launch_selection=launch_selection,
            )
            response_text = ensure_str_content(response.content)

            # Save chat history for TUI display
            try:
                from sase.history.chat import save_chat_history

                response_path = save_chat_history(
                    prompt=expanded_prompt,
                    response=response_text,
                    workflow=self.workflow.name,
                    agent=step.name,
                    metadata_agent=step.name,
                    metadata_model=step_model,
                    metadata_llm_provider=step_llm_provider,
                    branch_or_workspace=branch_or_workspace,
                )
            except Exception:
                pass

            # Parse and validate output
            output: dict[str, Any] = {}

            if step.output:
                try:
                    data, _ = extract_structured_content(response_text)
                    if isinstance(data, dict):
                        output = data
                    else:
                        output = {"_data": data}
                except Exception:
                    output = {"_raw": response_text}
            else:
                output = {"_raw": response_text}

            # Resolve path fields from embedded contexts before HITL
            if self._should_hitl(step) and embedded_workflows:
                resolve_embedded_path_fields(output, step, embedded_workflows)

            absolutize_path_outputs(output, step)

            # HITL review if required
            if self._should_hitl(step) and self.hitl_handler:
                step_state.status = StepStatus.WAITING_HITL
                self.state.status = "waiting_hitl"
                self._save_state()
                self._save_prompt_step_marker(
                    step.name,
                    step_state,
                    hidden=step.hidden,
                    response_path=response_path,
                )

                result = self.hitl_handler.prompt(
                    step.name,
                    "agent",
                    output,
                    has_output=step.output is not None,
                    output_types=output_types_from_step(step),
                )

                if result.action == "reject":
                    _deferred_reject = True
                elif result.action == "edit":
                    if result.edited_output is not None:
                        output = result.edited_output

                if not _deferred_reject:
                    # Resume running status after HITL acceptance
                    self.state.status = "running"
                    self._save_state()

            if not _deferred_reject:
                # Mark step completed after HITL (prompt work is done)
                step_state.status = StepStatus.COMPLETED

                # Merge pre-step meta back into output (preserving prompt output priority)
                if pre_step_meta:
                    for k, v in pre_step_meta.items():
                        if k not in output:
                            output[k] = v

                # Store output in context under step name
                step_state.output = output
                self.context[step.name] = output
                self.state.context = dict(self.context)

                # Capture git diff if changes were made
                diff_content = capture_vcs_diff()
                diff_path = None
                if diff_content:
                    diff_path = os.path.join(
                        self.artifacts_dir, f"{step.name}_diff.txt"
                    )
                    try:
                        with open(diff_path, "w", encoding="utf-8") as f:
                            f.write(diff_content)
                    except Exception:
                        diff_path = None

                # Save prompt step marker for TUI visibility
                self._save_prompt_step_marker(
                    step.name,
                    step_state,
                    diff_path=diff_path,
                    hidden=step.hidden,
                    response_path=response_path,
                )

                # Execute post-steps from embedded workflows
                # Start offset after pre-steps so step indices don't collide
                cumulative_post_offset = pre_step_count
                for info in embedded_workflows:
                    if info.post_steps:
                        from sase.xprompt.workflow_output import ParentStepContext

                        # Make agent prompt and response available to post-steps
                        info.context["_prompt"] = expanded_prompt
                        info.context["_response"] = response_text
                        parent_ctx = ParentStepContext(
                            step_index=self.state.current_step_index,
                            total_steps=len(self.workflow.steps),
                        )
                        success = self._execute_embedded_workflow_steps(
                            info.post_steps,
                            info.context,
                            f"embedded:post:{step.name}",
                            parent_step_context=parent_ctx,
                            step_index_offset=cumulative_post_offset,
                            embedded_workflow_name=info.workflow_name,
                        )
                        if not success:
                            raise WorkflowExecutionError(
                                f"Post-steps for embedded workflow in step "
                                f"'{step.name}' failed"
                            )
                        cumulative_post_offset += len(info.post_steps)

        except Exception as exc:
            if not _has_finally_post:
                raise
            _deferred_error = exc

        # -- Finally post-steps: run even after agent/post-step failure ----
        if (_deferred_error is not None or _deferred_reject) and _has_finally_post:
            cumulative_post_offset = pre_step_count
            for info in embedded_workflows:
                finally_steps = [s for s in info.post_steps if s.finally_]
                if finally_steps:
                    from sase.xprompt.workflow_output import ParentStepContext

                    parent_ctx = ParentStepContext(
                        step_index=self.state.current_step_index,
                        total_steps=len(self.workflow.steps),
                    )
                    # Best-effort cleanup; ignore failures in finally steps
                    try:
                        self._execute_embedded_workflow_steps(
                            finally_steps,
                            info.context,
                            f"embedded:finally:{step.name}",
                            parent_step_context=parent_ctx,
                            step_index_offset=cumulative_post_offset,
                            embedded_workflow_name=info.workflow_name,
                        )
                    except Exception:
                        pass  # Don't mask the original error
                cumulative_post_offset += len(info.post_steps)

        # Propagate deferred failures now that cleanup has run
        if _deferred_error is not None:
            raise _deferred_error
        if _deferred_reject:
            return False

        # Propagate output from last embedded workflow's last post-step
        self._propagate_last_embedded_output(embedded_workflows, step, step_state)

        # Collect diff_path and meta_* from embedded post-step outputs and
        # re-save the parent marker so the TUI can display them.
        if embedded_workflows:
            diff_path, resave_needed = apply_embedded_outputs_to_parent(
                embedded_workflows,
                step_name=step.name,
                step_state=step_state,
                context=self.context,
                state=self.state,
                diff_path=diff_path,
            )
            if resave_needed:
                self._save_prompt_step_marker(
                    step.name,
                    step_state,
                    diff_path=diff_path,
                    hidden=step.hidden,
                    response_path=response_path,
                )

        return True
