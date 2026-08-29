"""Prompt expansion and preprocessing for workflow prompt steps."""

from dataclasses import dataclass, replace
import os
from typing import Any

from sase.xprompt.directives import PromptDirectives
from sase.xprompt.workflow_executor_steps_embedded_types import EmbeddedWorkflowInfo
from sase.xprompt.workflow_models import Workflow, WorkflowExecutionError, WorkflowStep


def _collect_pre_step_meta(
    embedded_workflows: list[EmbeddedWorkflowInfo],
) -> dict[str, str]:
    """Collect meta_* fields from embedded pre-step outputs."""
    pre_step_meta: dict[str, str] = {}
    for info in embedded_workflows:
        for pre_step in info.pre_steps:
            pre_step_output = info.context.get(pre_step.name)
            if isinstance(pre_step_output, dict):
                for k, v in pre_step_output.items():
                    if k.startswith("meta_") and v:
                        pre_step_meta[k] = str(v)
    return pre_step_meta


@dataclass
class _PreparedPromptStep:
    """Preprocessed prompt, routing directives, and embedded workflow state."""

    expanded_prompt: str
    effective_directives: PromptDirectives
    embedded_workflows: list[EmbeddedWorkflowInfo]
    pre_step_count: int
    pre_step_meta: dict[str, str]


class PromptStepPrepareMixin:
    """Mixin that expands and preprocesses a prompt step before invocation.

    Required attributes (from WorkflowExecutor):
        - workflow: Workflow
        - context: dict[str, Any]
        - artifacts_dir: str
        - inherited_model_override: str | None
        - inherited_vcs_tag: str | None

    Required methods (from EmbeddedWorkflowMixin):
        - _expand_embedded_workflows_in_prompt(prompt) -> tuple
    """

    workflow: Workflow
    context: dict[str, Any]
    artifacts_dir: str
    inherited_model_override: str | None
    inherited_vcs_tag: str | None

    _expand_embedded_workflows_in_prompt: Any  # (prompt) -> tuple

    def _prepare_prompt_step(self, step: WorkflowStep) -> _PreparedPromptStep:
        """Expand xprompts, embedded workflows, and format instructions."""
        from sase.llm_provider.preprocessing import (
            preprocess_prompt_early,
            preprocess_prompt_late,
        )

        if not step.agent:
            raise WorkflowExecutionError(
                f"Agent step '{step.name}' has no agent prompt"
            )

        from sase.xprompt._parsing import inherit_vcs_workflow_tag

        step_prompt = inherit_vcs_workflow_tag(step.agent, self.inherited_vcs_tag)
        from sase.xprompt.used_xprompts import write_used_xprompts

        # Step-only write: per-step usage lands in xprompts_<step>.json for
        # child rows, while the shared xprompts.json (launch/root metadata
        # written at the launch boundary) is preserved rather than clobbered
        # with step-level data. When no launch boundary captured usage, the
        # first step still seeds the shared file.
        write_used_xprompts(
            self.artifacts_dir,
            step_prompt,
            step.name,
            extra_xprompts=self.workflow.xprompts,
            step_only=True,
        )

        # Early phase: directives, Jinja2 context rendering, xprompt expansion
        early = preprocess_prompt_early(
            step_prompt,
            extra_xprompts=self.workflow.xprompts,
            scope=self.context,
            context=self.context,
        )
        effective_directives = early.directives
        if self.inherited_model_override:
            effective_directives = replace(
                effective_directives,
                model=self.inherited_model_override,
            )
        retry_model_override = os.environ.get("SASE_MODEL_OVERRIDE")
        if retry_model_override:
            effective_directives = replace(
                effective_directives,
                model=retry_model_override,
            )

        # Then expand embedded workflows
        # This executes pre-steps and replaces workflow refs with prompt_part content
        expanded_prompt, embedded_workflows, pre_step_count = (
            self._expand_embedded_workflows_in_prompt(early.prompt)
        )

        # Re-expand xprompts after embedded workflow pre-steps.  The pre-steps
        # may have updated the workspace (e.g. git pull), making CWD-relative
        # xprompts (like local sase.yml entries) available that weren't
        # present during the early phase.
        if embedded_workflows:
            from sase.xprompt import process_xprompt_references

            expanded_prompt = process_xprompt_references(
                expanded_prompt,
                extra_xprompts=self.workflow.xprompts,
                scope=self.context,
            )

        # Late phase: command sub, file refs, Jinja2, prettier, HTML stripping
        from sase.artifact_ref_prompt_context import (
            prompt_ref_contexts_for_segment_vcs_refs,
        )

        ref_contexts = prompt_ref_contexts_for_segment_vcs_refs(
            early.segment_vcs_refs, is_home_mode=False
        )
        expanded_prompt = preprocess_prompt_late(
            expanded_prompt,
            ref_contexts=ref_contexts,
            materialize_missing_roots=True,
        )

        # Append output format instructions if step has output spec
        if step.output:
            from sase.xprompt import generate_format_instructions

            format_instr = generate_format_instructions(step.output)
            if format_instr:
                expanded_prompt = expanded_prompt + format_instr

        # Collect meta_* from embedded pre-steps so the TUI can display
        # Workspace/Project/Patch immediately when the agent starts.
        pre_step_meta = _collect_pre_step_meta(embedded_workflows)

        return _PreparedPromptStep(
            expanded_prompt=expanded_prompt,
            effective_directives=effective_directives,
            embedded_workflows=embedded_workflows,
            pre_step_count=pre_step_count,
            pre_step_meta=pre_step_meta,
        )
