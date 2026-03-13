"""Prompt step execution mixin."""

import os
from typing import TYPE_CHECKING, Any

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
    from sase.xprompt.workflow_executor_steps_embedded import EmbeddedWorkflowInfo
    from sase.xprompt.workflow_output import WorkflowOutputHandler


def capture_vcs_diff() -> str | None:
    """Capture uncommitted changes as a VCS diff, including untracked files.

    Returns:
        The VCS diff output, or None if no changes or an error occurred.
    """
    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(os.getcwd())
        _, diff_text = provider.diff_with_untracked(os.getcwd())
        return diff_text
    except Exception:
        return None


def _collect_embedded_step_outputs(
    embedded_workflows: list["EmbeddedWorkflowInfo"],
) -> tuple[str | None, dict[str, str]]:
    """Collect diff_path and meta_* fields from embedded step outputs.

    Scans both pre-steps and post-steps for meta_* fields.
    diff_path extraction remains post-step only.
    """
    diff_path: str | None = None
    meta_fields: dict[str, str] = {}
    for info in embedded_workflows:
        # Collect meta_* from ALL pre-steps
        for step in info.pre_steps:
            step_output = info.context.get(step.name)
            if isinstance(step_output, dict):
                for k, v in step_output.items():
                    if k.startswith("meta_") and v:
                        meta_fields[k] = str(v)
        # Collect meta_* from ALL post-steps
        for step in info.post_steps:
            step_output = info.context.get(step.name)
            if isinstance(step_output, dict):
                for k, v in step_output.items():
                    if k.startswith("meta_") and v:
                        meta_fields[k] = str(v)
        # Extract path-type output from LAST post-step only
        # (first embedded workflow with post-steps wins)
        if info.post_steps and diff_path is None:
            last_step = info.post_steps[-1]
            step_output = info.context.get(last_step.name)
            if isinstance(step_output, dict) and last_step.output is not None:
                properties = last_step.output.schema.get("properties")
                if properties and isinstance(properties, dict):
                    for field_name, prop in properties.items():
                        if isinstance(prop, dict) and prop.get("type") == "path":
                            path_value = step_output.get(field_name)
                            if path_value:
                                diff_path = str(path_value)
                                break
    return diff_path, meta_fields


def _resolve_embedded_path_fields(
    output: dict[str, Any],
    step: WorkflowStep,
    embedded_workflows: list["EmbeddedWorkflowInfo"],
) -> None:
    """Populate missing path-type output fields from embedded workflow contexts.

    When a parent step declares path-type output fields (e.g., {desc_file: path}),
    the actual file paths may come from embedded workflow pre-steps. This resolves
    those paths before HITL review so file contents can be displayed.
    """
    from sase.xprompt.workflow_executor_steps_embedded import map_output_by_type

    parent_output_types = output_types_from_step(step)
    if not parent_output_types:
        return

    path_fields = {k for k, v in parent_output_types.items() if v == "path"}
    if not path_fields:
        return

    for info in embedded_workflows:
        for pre_step in info.pre_steps:
            if not pre_step.output:
                continue
            pre_step_output = info.context.get(pre_step.name)
            if not isinstance(pre_step_output, dict):
                continue
            # step.output is guaranteed non-None here because
            # output_types_from_step() returned a non-None dict above.
            assert step.output is not None
            mapped = map_output_by_type(step.output, pre_step.output, pre_step_output)
            if mapped is None:
                continue
            for field_name in path_fields:
                if field_name in mapped and field_name not in output:
                    output[field_name] = mapped[field_name]


class PromptStepMixin:
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
        from sase.llm_provider import invoke_agent
        from sase.llm_provider.preprocessing import (
            preprocess_prompt_early,
            preprocess_prompt_late,
        )
        from sase.shared_utils import ensure_str_content

        from sase.xprompt import extract_structured_content

        if not step.agent:
            raise WorkflowExecutionError(
                f"Agent step '{step.name}' has no agent prompt"
            )

        # Early phase: directives, Jinja2 context rendering, xprompt expansion
        early = preprocess_prompt_early(
            step.agent,
            extra_xprompts=self.workflow.xprompts,
            scope=self.context,
            context=self.context,
        )

        # Then expand embedded workflows
        # This executes pre-steps and replaces workflow refs with prompt_part content
        expanded_prompt, embedded_workflows, pre_step_count = (
            self._expand_embedded_workflows_in_prompt(early.prompt)
        )

        # Re-expand xprompts after embedded workflow pre-steps.  The pre-steps
        # may have updated the workspace (e.g. git pull), making CWD-relative
        # xprompts (like .xprompts/xprompts.yml entries) available that weren't
        # present during the early phase.
        if embedded_workflows:
            from sase.xprompt import process_xprompt_references

            expanded_prompt = process_xprompt_references(
                expanded_prompt,
                extra_xprompts=self.workflow.xprompts,
                scope=self.context,
            )

        # Late phase: command sub, file refs, Jinja2, prettier, HTML stripping
        expanded_prompt = preprocess_prompt_late(expanded_prompt)

        # Collect meta_* from embedded pre-steps so the TUI can display
        # Workspace/Project/ChangeSpec immediately when the agent starts.
        pre_step_meta: dict[str, str] = {}
        for info in embedded_workflows:
            for pre_step in info.pre_steps:
                pre_step_output = info.context.get(pre_step.name)
                if isinstance(pre_step_output, dict):
                    for k, v in pre_step_output.items():
                        if k.startswith("meta_") and v:
                            pre_step_meta[k] = str(v)
        if pre_step_meta:
            step_state.output = dict(pre_step_meta)

        # Resolve model and LLM provider for TUI display in the step marker
        from sase.llm_provider.registry import (
            get_default_provider_name,
            get_provider,
            resolve_model_provider,
        )

        step_model = early.directives.model
        if step_model:
            resolved_provider, step_model = resolve_model_provider(step_model)
            step_llm_provider = resolved_provider or get_default_provider_name()
        else:
            step_llm_provider = get_default_provider_name()
            step_model = get_provider().resolve_model_name()

        # Save initial marker to show step is running in TUI
        step_state.status = StepStatus.IN_PROGRESS
        self._save_prompt_step_marker(
            step.name,
            step_state,
            hidden=step.hidden,
            model=step_model,
            llm_provider=step_llm_provider,
        )

        # Invoke agent (skip preprocessing — we already did early+late)
        # Extract base workflow name (without project prefix) to avoid slashes in filenames
        base_name = (
            self.workflow.name.split("/")[-1]
            if "/" in self.workflow.name
            else self.workflow.name
        )
        response = invoke_agent(
            expanded_prompt,
            agent_type=f"workflow-{base_name}-{step.name}",
            artifacts_dir=self.artifacts_dir,
            workflow=self.workflow.name,
            skip_preprocessing=True,
            directives=early.directives,
        )
        response_text = ensure_str_content(response.content)

        # Save chat history for TUI display
        response_path: str | None = None
        try:
            from sase.chat_history import save_chat_history

            response_path = save_chat_history(
                prompt=expanded_prompt,
                response=response_text,
                workflow=self.workflow.name,
                agent=step.name,
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
            _resolve_embedded_path_fields(output, step, embedded_workflows)

        # Make path fields absolute for cross-process HITL communication
        step_output_types = output_types_from_step(step)
        if step_output_types:
            for field_name, field_type in step_output_types.items():
                if field_type == "path" and field_name in output:
                    path_val = os.path.expanduser(str(output[field_name]))
                    if not os.path.isabs(path_val):
                        path_val = os.path.abspath(path_val)
                    output[field_name] = path_val

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
                return False
            elif result.action == "accept":
                pass  # Continue with output as-is
            elif result.action == "edit":
                if result.edited_output is not None:
                    output = result.edited_output
                # Continue with edited output
            # Future: handle feedback for regeneration

            # Resume running status after HITL acceptance
            self.state.status = "running"
            self._save_state()

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
        diff_path: str | None = None
        if diff_content:
            diff_path = os.path.join(self.artifacts_dir, f"{step.name}_diff.txt")
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
                        f"Post-steps for embedded workflow in step '{step.name}' failed"
                    )
                cumulative_post_offset += len(info.post_steps)

        # Propagate output from last embedded workflow's last post-step
        self._propagate_last_embedded_output(embedded_workflows, step, step_state)

        # Collect diff_path and meta_* from embedded post-step outputs and
        # re-save the parent marker so the TUI can display them.
        if embedded_workflows:
            embedded_diff_path, embedded_meta = _collect_embedded_step_outputs(
                embedded_workflows
            )
            resave_needed = False
            if embedded_meta:
                if step_state.output is None:
                    step_state.output = {}
                step_state.output.update(embedded_meta)
                self.context[step.name] = step_state.output
                self.state.context = dict(self.context)
                resave_needed = True
            # When embedded workflows appended post-steps, their path output
            # exclusively determines the file panel content for DONE entries
            has_appended_steps = any(info.post_steps for info in embedded_workflows)
            if has_appended_steps:
                diff_path = embedded_diff_path  # May be None → hides file panel
                if embedded_diff_path:
                    if step_state.output is None:
                        step_state.output = {}
                    step_state.output["diff_path"] = embedded_diff_path
                resave_needed = True
            elif embedded_diff_path and not diff_path:
                # Embedded workflows without post-steps but with path (defensive)
                diff_path = embedded_diff_path
                if step_state.output is None:
                    step_state.output = {}
                step_state.output["diff_path"] = embedded_diff_path
                resave_needed = True
            if resave_needed:
                self._save_prompt_step_marker(
                    step.name,
                    step_state,
                    diff_path=diff_path,
                    hidden=step.hidden,
                    response_path=response_path,
                )

        return True
