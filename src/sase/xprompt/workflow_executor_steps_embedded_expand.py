"""Embedded workflow expansion mixin.

Provides the prompt expansion logic that detects workflow references
(e.g. ``#commit``, ``#gh:sase``) and replaces them with rendered
prompt_part content.
"""

import json
import logging
import os
import re
from typing import Any

from sase.content import (
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
)
from sase.xprompt._fenced_blocks import protect_fenced_blocks, unprotect_fenced_blocks
from sase.xprompt.models import UNSET
from sase.xprompt.workflow_executor_steps_embedded_types import (
    EmbeddedWorkflowInfo,
    _DISABLED_REGION_START_RE,
    PendingEmbeddedWorkflow,
    _WORKFLOW_REF_PATTERN,
)
from sase.xprompt.workflow_executor_utils import render_template
from sase.xprompt.workflow_models import (
    Workflow,
    WorkflowExecutionError,
    WorkflowState,
)


logger = logging.getLogger(__name__)


class EmbeddedWorkflowExpandMixin:
    """Mixin providing embedded workflow expansion in prompts.

    This mixin requires the following attributes on self:
        - workflow: Workflow
        - artifacts_dir: str
        - state: WorkflowState

    This mixin requires the following methods on self (provided by
    EmbeddedWorkflowMixin or another mixin in the MRO):
        - _execute_embedded_workflow_steps(...)
        - _resolve_tagged_workflow_content(...)
    """

    # Type hints for attributes from WorkflowExecutor
    workflow: Workflow
    artifacts_dir: str
    state: WorkflowState

    # Method type declarations for methods provided by other mixins
    _execute_embedded_workflow_steps: Any
    _resolve_tagged_workflow_content: Any

    def _expand_embedded_workflows_in_prompt(
        self,
        prompt: str,
        pre_step_offset: int = 0,
    ) -> tuple[str, list[EmbeddedWorkflowInfo], int]:
        """Detect and expand embedded workflows in a prompt.

        Finds workflow references in the prompt, executes their pre-steps,
        and replaces the references with prompt_part content.

        The expansion proceeds in five phases:
        1. Collection — iterate matches left-to-right, parse args, build pending list
        2. Validation — ensure at most one wraps_all workflow
        3. Pre-step execution — wraps_all first, then remaining in right-to-left order
        4. Text replacement — replace references right-to-left (position-safe)
        5. Post-step list — build embedded_workflows with wraps_all at end

        Args:
            prompt: The prompt text that may contain workflow references.
            pre_step_offset: Starting offset for sub-step numbering of pre-steps.

        Returns:
            Tuple of (expanded_prompt, list of EmbeddedWorkflowInfo,
            total_pre_steps_executed). The post_steps should be executed
            after the main prompt completes.
        """
        from sase.xprompt._parsing import (
            find_matching_paren_for_args,
            normalize_vcs_underscore_refs,
            parse_args,
        )
        from sase.xprompt.loader import get_all_workflows

        workflows = get_all_workflows()
        running_offset = pre_step_offset

        # Protect fenced code blocks so that workflow references like #gh
        # inside triple-backtick blocks are not treated as real references.
        fenced_blocks: list[str] = []
        prompt = protect_fenced_blocks(prompt, fenced_blocks)

        # Normalize #gh_sase → #gh:sase so the workflow ref pattern can
        # correctly split VCS prefix from ref name.
        prompt = normalize_vcs_underscore_refs(prompt)

        # ── Phase 1: Collection ──────────────────────────────────────────
        # Iterate matches left-to-right, parse args, build pending list.
        matches = list(re.finditer(_WORKFLOW_REF_PATTERN, prompt, re.MULTILINE))
        pending: list[PendingEmbeddedWorkflow] = []

        for match in matches:
            name = match.group(1)

            if name not in workflows:
                continue

            workflow = workflows[name]

            if not workflow.has_prompt_part():
                logger.warning(
                    "_expand_embedded_workflows_in_prompt: skipping #%s — "
                    "workflow found but has no prompt_part (standalone workflow "
                    "cannot be embedded). It will pass through as literal text.",
                    name,
                )
                continue

            # Extract arguments
            has_open_paren = match.group(2) is not None
            colon_arg = match.group(3)
            plus_suffix = match.group(4)
            match_end = match.end()

            positional_args: list[str] = []
            named_args: dict[str, str] = {}

            if has_open_paren:
                paren_start = match.end() - 1
                paren_end = find_matching_paren_for_args(prompt, paren_start)
                if paren_end is not None:
                    paren_content = prompt[paren_start + 1 : paren_end]
                    positional_args, named_args = parse_args(paren_content)
                    match_end = paren_end + 1
            elif colon_arg is not None:
                if colon_arg.startswith("`") and colon_arg.endswith("`"):
                    colon_arg = colon_arg[1:-1]
                positional_args = [colon_arg]
            elif plus_suffix is not None:
                positional_args = ["true"]

            # Build args dict
            args: dict[str, Any] = dict(named_args)
            for i, value in enumerate(positional_args):
                if i < len(workflow.inputs):
                    input_arg = workflow.inputs[i]
                    if input_arg.name not in args:
                        args[input_arg.name] = value

            explicit_args = dict(args)

            # Apply defaults
            for input_arg in workflow.inputs:
                if input_arg.name not in args and input_arg.default is not UNSET:
                    args[input_arg.name] = input_arg.default

            pending.append(
                PendingEmbeddedWorkflow(
                    name=name,
                    workflow=workflow,
                    match_start=match.start(),
                    match_end=match_end,
                    args=args,
                    explicit_args=explicit_args,
                )
            )

        if not pending:
            prompt = unprotect_fenced_blocks(prompt, fenced_blocks)
            return prompt, [], 0

        # ── Phase 2: Validation ──────────────────────────────────────────
        from sase.xprompt.tags import XPromptTag

        vcs_entries = [p for p in pending if p.workflow.has_tag(XPromptTag.vcs)]
        if len(vcs_entries) > 1:
            names = ", ".join(f"#{p.name}" for p in vcs_entries)
            raise WorkflowExecutionError(
                f"Multiple VCS-tagged workflows in one prompt: {names}. "
                "At most one VCS workflow is allowed per prompt."
            )

        # ── Phase 3: Pre-step execution ──────────────────────────────────
        # Execute in priority order: VCS workflow first, then remaining in
        # reversed (right-to-left) order to preserve current behavior.
        wraps_all_pending = [p for p in pending if p.workflow.has_tag(XPromptTag.vcs)]
        non_wraps_all_pending = [
            p for p in pending if not p.workflow.has_tag(XPromptTag.vcs)
        ]
        execution_order = wraps_all_pending + list(reversed(non_wraps_all_pending))

        for p in execution_order:
            pre_steps = p.workflow.get_pre_prompt_steps()
            p.embedded_context = dict(p.args)

            if pre_steps:
                from sase.xprompt.workflow_output import ParentStepContext

                parent_ctx = ParentStepContext(
                    step_index=self.state.current_step_index,
                    total_steps=len(self.workflow.steps),
                )
                success = self._execute_embedded_workflow_steps(
                    pre_steps,
                    p.embedded_context,
                    f"embedded:{p.name}",
                    parent_step_context=parent_ctx,
                    is_pre_prompt_step=True,
                    step_index_offset=running_offset,
                    embedded_workflow_name=p.name,
                )
                if not success:
                    raise WorkflowExecutionError(
                        f"Pre-steps for embedded workflow '{p.name}' failed"
                    )
                running_offset += len(pre_steps)

            # Inject embedded workflow environment variables into os.environ
            # so they are visible to the agent, stop hooks, and post-steps.
            if p.workflow.environment:
                for key, value_template in p.workflow.environment.items():
                    rendered = render_template(value_template, p.embedded_context)
                    os.environ[key] = rendered

            # Render prompt_part (respecting if: condition)
            prompt_part_idx = p.workflow.get_prompt_part_index()
            prompt_part_step = (
                p.workflow.steps[prompt_part_idx]
                if prompt_part_idx is not None
                else None
            )
            prompt_part_content = ""
            if prompt_part_step and prompt_part_step.condition:
                rendered_cond = render_template(
                    prompt_part_step.condition, p.embedded_context
                )
                cond_str = rendered_cond.strip().lower()
                if cond_str not in ("", "false", "none", "0", "[]", "{}"):
                    prompt_part_content = prompt_part_step.prompt_part or ""
            else:
                prompt_part_content = p.workflow.get_prompt_part_content()
            if prompt_part_content:
                prompt_part_content = render_template(
                    prompt_part_content, p.embedded_context
                )
                is_at_line_start = (
                    p.match_start == 0 or prompt[p.match_start - 1] == "\n"
                )
                prompt_part_content = apply_section_marker_handling(
                    prompt_part_content, is_at_line_start
                )
                # When the expanded content ends with a markdown heading and
                # there's more content on the same line after the reference,
                # append a blank line so the following text appears below the
                # heading.  We use two newlines (\n\n) rather than one because
                # a single \n gets collapsed by the prettier formatting pass.
                if (
                    content_ends_with_markdown_heading(prompt_part_content)
                    and p.match_end < len(prompt)
                    and prompt[p.match_end] != "\n"
                ):
                    prompt_part_content += "\n\n"
            # Append VCS-specific tagged content based on SASE_COMMIT_METHOD
            commit_method = p.workflow.environment.get("SASE_COMMIT_METHOD")
            if commit_method:
                from sase.xprompt.tags import get_by_tag

                append_tag = None
                if commit_method in ("create_commit", "create_proposal"):
                    append_tag = XPromptTag.append_to_commit_and_propose
                elif commit_method == "create_pull_request":
                    append_tag = XPromptTag.append_to_pr

                if append_tag:
                    vcs_hint = wraps_all_pending[0].name if wraps_all_pending else None
                    tagged_wf = get_by_tag(append_tag, vcs_hint=vcs_hint)
                    if tagged_wf:
                        tagged_content, extra_steps = (
                            self._resolve_tagged_workflow_content(
                                tagged_wf, running_offset
                            )
                        )
                        running_offset += extra_steps
                        if tagged_content:
                            prompt_part_content = (
                                (prompt_part_content or "") + "\n" + tagged_content
                            )

            p.rendered_prompt_part = prompt_part_content

        # ── Phase 4: Text replacement ────────────────────────────────────
        # Sort by match_start descending so right-to-left replacement is position-safe.
        for p in sorted(pending, key=lambda x: x.match_start, reverse=True):
            replacement = p.rendered_prompt_part
            # When the rendered content starts with a disabled-region marker
            # but the insertion point is mid-line (e.g. after an unexpanded
            # VCS ref like #hg:sase), prepend a newline so the marker starts
            # at a line boundary — required for downstream protect/strip.
            if (
                replacement
                and p.match_start > 0
                and prompt[p.match_start - 1] != "\n"
                and _DISABLED_REGION_START_RE.match(replacement)
            ):
                replacement = "\n" + replacement
            prompt = prompt[: p.match_start] + replacement + prompt[p.match_end :]

        # Restore fenced code blocks now that matching and replacement are done.
        prompt = unprotect_fenced_blocks(prompt, fenced_blocks)

        # ── Phase 5: Post-step list ──────────────────────────────────────
        # Build embedded_workflows: non-VCS in right-to-left order, then
        # VCS at END so its post-steps run last (teardown after everything).
        embedded_workflows: list[EmbeddedWorkflowInfo] = []

        for p in reversed(non_wraps_all_pending):
            post_steps = p.workflow.get_post_prompt_steps()
            if post_steps:
                embedded_workflows.append(
                    EmbeddedWorkflowInfo(
                        pre_steps=p.workflow.get_pre_prompt_steps(),
                        post_steps=post_steps,
                        context=p.embedded_context,
                        workflow_name=p.name,
                    )
                )

        for p in wraps_all_pending:
            post_steps = p.workflow.get_post_prompt_steps()
            if post_steps:
                embedded_workflows.append(
                    EmbeddedWorkflowInfo(
                        pre_steps=p.workflow.get_pre_prompt_steps(),
                        post_steps=post_steps,
                        context=p.embedded_context,
                        workflow_name=p.name,
                    )
                )

        # Save embedded workflow metadata (pending is already left-to-right)
        if pending and os.path.isdir(self.artifacts_dir):
            ordered_metadata = [
                {
                    "name": p.name,
                    "args": p.explicit_args,
                    "tags": sorted(t.value for t in p.workflow.tags),
                }
                for p in pending
            ]
            # Write shared file (backward compat for sase run agents)
            metadata_path = os.path.join(self.artifacts_dir, "embedded_workflows.json")
            with open(metadata_path, "w", encoding="utf-8") as f:
                json.dump(ordered_metadata, f, indent=2)
            # Write step-specific file for multi-step workflows
            current_step_name = self.workflow.steps[self.state.current_step_index].name
            step_metadata_path = os.path.join(
                self.artifacts_dir,
                f"embedded_workflows_{current_step_name}.json",
            )
            with open(step_metadata_path, "w", encoding="utf-8") as f:
                json.dump(ordered_metadata, f, indent=2)

        return prompt, embedded_workflows, running_offset - pre_step_offset
