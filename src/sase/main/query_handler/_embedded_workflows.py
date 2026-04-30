"""Embedded workflow expansion in queries."""

import json
import os
from dataclasses import dataclass, field
from typing import Any

from sase.content import (
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
)
from sase.xprompt.models import UNSET
from sase.xprompt.workflow_models import WorkflowStep


@dataclass
class EmbeddedWorkflowResult:
    """Result from expanding an embedded workflow in a query.

    Captures the pre/post steps, context, and positional metadata needed
    to write step marker files for TUI visibility.
    """

    workflow_name: str
    pre_steps: list[WorkflowStep]
    post_steps: list[WorkflowStep]
    context: dict[str, Any] = field(default_factory=dict)
    prompt_part_index: int = 0
    total_workflow_steps: int = 0


def expand_embedded_workflows_in_query(
    query: str,
    artifacts_dir: str | None = None,
) -> tuple[str, list[EmbeddedWorkflowResult]]:
    """Detect and expand embedded workflows in a query.

    For simple `sase run` queries, this handles workflows with `prompt_part`:
    - Executes pre-steps from embedded workflows
    - Replaces workflow references with prompt_part content
    - Returns post-steps to be executed after the main prompt

    Args:
        query: The query text that may contain workflow references.
        artifacts_dir: Optional directory for workflow artifacts.

    Returns:
        Tuple of (expanded_query, list of EmbeddedWorkflowResult objects).
    """
    from sase.xprompt._fenced_blocks import fenced_block_ranges
    from sase.xprompt._parsing import (
        iter_xprompt_references,
        normalize_vcs_underscore_refs,
    )
    from sase.xprompt.loader import get_all_workflows
    from sase.xprompt.processor import process_xprompt_references
    from sase.xprompt.workflow_executor_steps_embedded_types import (
        format_inline_workflow_reference_error,
        parse_workflow_reference_args,
    )
    from sase.xprompt.workflow_executor_utils import render_template
    from sase.xprompt.workflow_models import WorkflowExecutionError

    from ._standalone_steps import execute_standalone_steps

    workflows = get_all_workflows()
    post_workflows: list[EmbeddedWorkflowResult] = []
    expanded_metadata: list[dict[str, Any]] = []

    # Normalize #gh_sase → #gh:sase so the workflow ref pattern can
    # correctly split VCS prefix from ref name.
    query = normalize_vcs_underscore_refs(query)

    # Compute fenced code block ranges so we can skip references inside them.
    fenced_ranges = fenced_block_ranges(query)

    # Find all potential workflow references
    refs = iter_xprompt_references(query)

    # Process from last to first to preserve positions
    for ref in reversed(refs):
        # Skip references inside fenced code blocks
        if any(start <= ref.start < end for start, end in fenced_ranges):
            continue

        # Skip if not a workflow
        name = ref.name
        if name not in workflows:
            continue

        workflow = workflows[name]

        if ref.is_standalone_marker or not workflow.has_prompt_part():
            raise WorkflowExecutionError(
                format_inline_workflow_reference_error(
                    name=name,
                    raw=ref.raw,
                    has_prompt_part=workflow.has_prompt_part(),
                )
            )

        positional_args, named_args = parse_workflow_reference_args(ref)
        match_end = ref.end

        # Build args dict
        args: dict[str, Any] = dict(named_args)
        for i, value in enumerate(positional_args):
            if i < len(workflow.inputs):
                input_arg = workflow.inputs[i]
                if input_arg.name not in args:
                    args[input_arg.name] = value

        # Capture explicit args before applying defaults
        explicit_args = dict(args)
        expanded_metadata.append(
            {
                "name": name,
                "args": explicit_args,
                "tags": sorted(t.value for t in workflow.tags),
            }
        )

        # Apply defaults
        for input_arg in workflow.inputs:
            if input_arg.name not in args and input_arg.default is not UNSET:
                args[input_arg.name] = input_arg.default

        # Get pre and post steps
        pre_steps = workflow.get_pre_prompt_steps()
        post_steps = workflow.get_post_prompt_steps()

        # Create isolated context for the embedded workflow
        embedded_context: dict[str, Any] = dict(args)

        # Execute pre-steps using a minimal workflow executor
        if pre_steps:
            embedded_context = execute_standalone_steps(
                pre_steps, embedded_context, workflow.name, artifacts_dir
            )

        # Inject embedded workflow environment variables into os.environ
        # so they are visible to the agent, stop hooks, and post-steps.
        if workflow.environment:
            for key, value_template in workflow.environment.items():
                rendered = render_template(value_template, embedded_context)
                os.environ[key] = rendered

        # Render prompt_part with the embedded context (args + pre-step outputs)
        prompt_part_content = workflow.get_prompt_part_content()
        if prompt_part_content:
            prompt_part_content = render_template(prompt_part_content, embedded_context)
            prompt_part_content = process_xprompt_references(prompt_part_content)

            # Handle section markers (### or ---) with proper line positioning
            is_at_line_start = ref.start == 0 or query[ref.start - 1] == "\n"
            prompt_part_content = apply_section_marker_handling(
                prompt_part_content, is_at_line_start
            )

        # When the expanded content ends with a markdown heading and there's
        # more content on the same line after the reference, append a blank
        # line so the following text appears below the heading.  We use two
        # newlines (\n\n) rather than one because a single \n gets collapsed
        # by the prettier formatting pass in preprocess_prompt_late.
        if (
            prompt_part_content
            and content_ends_with_markdown_heading(prompt_part_content)
            and match_end < len(query)
            and query[match_end] != "\n"
        ):
            prompt_part_content += "\n\n"

        # Replace the workflow reference with the prompt_part content
        query = query[: ref.start] + prompt_part_content + query[match_end:]

        # Store workflow result for post-step execution and step markers
        if pre_steps or post_steps:
            post_workflows.append(
                EmbeddedWorkflowResult(
                    workflow_name=name,
                    pre_steps=pre_steps,
                    post_steps=post_steps,
                    context=embedded_context,
                    prompt_part_index=workflow.get_prompt_part_index() or 0,
                    total_workflow_steps=len(workflow.steps),
                )
            )

    # Save embedded workflow metadata (reversed to restore original order)
    if artifacts_dir and expanded_metadata:
        metadata_path = os.path.join(artifacts_dir, "embedded_workflows.json")
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(list(reversed(expanded_metadata)), f, indent=2)

    return query, post_workflows
