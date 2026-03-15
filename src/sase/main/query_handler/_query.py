"""Core query execution logic."""

import json
import os
import re
import tempfile
from dataclasses import dataclass, field
from typing import Any

from sase.chat_history import save_chat_history
from sase.running_field import claim_workspace, release_workspace
from sase.shared_utils import (
    apply_section_marker_handling,
    content_ends_with_markdown_heading,
    create_artifacts_directory,
)
from sase.xprompt.models import UNSET
from sase.xprompt.workflow_models import WorkflowStep

from ..utils import ensure_project_file_and_get_workspace_num


def _resolve_vcs_cwd(query: str) -> str | None:
    """Detect VCS workflow refs in the query and resolve workspace CWD.

    If the query contains a VCS workflow reference (e.g., ``#gh:sase``),
    resolves the ref to the primary workspace directory and changes CWD.
    This ensures that project-specific workflows are discoverable and
    CWD-relative paths in workflow steps work correctly.

    Mirrors the TUI behavior where the subprocess CWD is set to the
    resolved workspace directory before the workflow runs.

    Args:
        query: The query text.

    Returns:
        The resolved project name, or None if no VCS ref was found.
    """
    if "#" not in query:
        return None

    from sase.workspace_provider import get_workflow_names, resolve_ref
    from sase.xprompt._parsing import normalize_vcs_underscore_refs

    normalized = normalize_vcs_underscore_refs(query)

    for workflow_type in get_workflow_names():
        pattern = rf"#({re.escape(workflow_type)}):([a-zA-Z0-9_.~/-]+)"
        match = re.search(pattern, normalized)
        if match:
            ref = match.group(2)
            try:
                resolved = resolve_ref(ref, workflow_type)
            except (ValueError, Exception):
                continue
            if resolved and resolved.primary_workspace_dir:
                os.chdir(resolved.primary_workspace_dir)
                # Clear cached project detection since CWD changed
                from sase.xprompt.loader import detect_project

                detect_project.cache_clear()
                return resolved.project_name or ref

    return None


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


# Pattern to match workflow references in prompts
_WORKFLOW_REF_PATTERN = (
    r"(?:^|(?<=\s)|(?<=[(\[{\"']))"
    r"#([a-zA-Z_][a-zA-Z0-9_]*(?:/[a-zA-Z_][a-zA-Z0-9_]*)*)"
    r"(?:(\()|:(`[^`]*`|[a-zA-Z0-9_.~/-]+)|(\+))?"  # Supports backtick-delimited colon args
)


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
        find_matching_paren_for_args,
        normalize_vcs_underscore_refs,
        parse_args,
    )
    from sase.xprompt.loader import get_all_workflows
    from sase.xprompt.processor import process_xprompt_references
    from sase.xprompt.workflow_executor_utils import render_template

    workflows = get_all_workflows()
    post_workflows: list[EmbeddedWorkflowResult] = []
    expanded_metadata: list[dict[str, Any]] = []

    # Normalize #gh_sase → #gh:sase so the workflow ref pattern can
    # correctly split VCS prefix from ref name.
    query = normalize_vcs_underscore_refs(query)

    # Compute fenced code block ranges so we can skip references inside them.
    fenced_ranges = fenced_block_ranges(query)

    # Find all potential workflow references
    matches = list(re.finditer(_WORKFLOW_REF_PATTERN, query, re.MULTILINE))

    # Process from last to first to preserve positions
    for match in reversed(matches):
        name = match.group(1)

        # Skip references inside fenced code blocks
        if any(start <= match.start() < end for start, end in fenced_ranges):
            continue

        # Skip if not a workflow
        if name not in workflows:
            continue

        workflow = workflows[name]

        # Skip workflows without prompt_part (execute as full workflow)
        if not workflow.has_prompt_part():
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
            paren_end = find_matching_paren_for_args(query, paren_start)
            if paren_end is not None:
                paren_content = query[paren_start + 1 : paren_end]
                positional_args, named_args = parse_args(paren_content)
                match_end = paren_end + 1
        elif colon_arg is not None:
            # Strip backticks if present (backtick-delimited syntax)
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

        # Capture explicit args before applying defaults
        explicit_args = dict(args)
        expanded_metadata.append({"name": name, "args": explicit_args})

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

        # Render prompt_part with the embedded context (args + pre-step outputs)
        prompt_part_content = workflow.get_prompt_part_content()
        if prompt_part_content:
            prompt_part_content = render_template(prompt_part_content, embedded_context)
            prompt_part_content = process_xprompt_references(prompt_part_content)

            # Handle section markers (### or ---) with proper line positioning
            is_at_line_start = match.start() == 0 or query[match.start() - 1] == "\n"
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
        query = query[: match.start()] + prompt_part_content + query[match_end:]

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


def _evaluate_standalone_condition(condition: str, context: dict[str, Any]) -> bool:
    """Evaluate a Jinja2 condition expression for standalone step execution.

    Mirrors WorkflowExecutor._evaluate_condition but operates on a plain dict
    context instead of the full executor state.

    Args:
        condition: The Jinja2 condition expression to evaluate.
        context: The current step context dictionary.

    Returns:
        True if condition evaluates to truthy, False otherwise.
    """
    from sase.xprompt.workflow_executor_utils import create_jinja_env

    env = create_jinja_env()
    try:
        template = env.from_string(condition)
        result = template.render(context)
        if isinstance(result, bool):
            return result
        result_str = result.strip().lower()
        return result_str not in ("", "false", "none", "0", "[]", "{}")
    except Exception:
        return False


def execute_standalone_steps(
    steps: list[WorkflowStep],
    context: dict[str, Any],
    workflow_name: str,
    artifacts_dir: str | None = None,
) -> dict[str, Any]:
    """Execute workflow steps in a standalone context.

    Used for running pre/post steps from embedded workflows outside of
    the normal workflow executor context.

    Args:
        steps: List of workflow steps to execute.
        context: Initial context (args).
        workflow_name: Name of the workflow (for artifacts).
        artifacts_dir: Optional directory for artifacts.

    Returns:
        Updated context with step outputs.

    Raises:
        WorkflowExecutionError: If any step fails.
    """
    import subprocess
    import sys

    from sase.xprompt.workflow_executor_utils import parse_bash_output, render_template
    from sase.xprompt.workflow_models import WorkflowExecutionError

    for step in steps:
        # Evaluate step condition (if: field) - skip step if condition is false
        if step.condition and not _evaluate_standalone_condition(
            step.condition, context
        ):
            context[step.name] = {}
            continue

        if step.is_bash_step() and step.bash:
            rendered_command = render_template(step.bash, context)
            try:
                result = subprocess.run(
                    rendered_command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=os.getcwd(),
                )
            except Exception as e:
                raise WorkflowExecutionError(
                    f"Failed to execute bash step '{step.name}': {e}"
                ) from e

            if result.returncode != 0:
                error_msg = (
                    result.stderr.strip()
                    if result.stderr
                    else f"Exit code {result.returncode}"
                )
                raise WorkflowExecutionError(
                    f"Bash step '{step.name}' failed: {error_msg}"
                )

            output = parse_bash_output(result.stdout)
            # Handle _chdir special output: change executor's working directory
            if "_chdir" in output:
                chdir_path = str(output.pop("_chdir"))
                if not os.path.isabs(chdir_path):
                    chdir_path = os.path.abspath(chdir_path)
                os.chdir(chdir_path)
            context[step.name] = output

        elif step.is_python_step() and step.python:
            rendered_code = render_template(step.python, context)
            try:
                result = subprocess.run(
                    [sys.executable, "-c", rendered_code],
                    capture_output=True,
                    text=True,
                    cwd=os.getcwd(),
                )
            except Exception as e:
                raise WorkflowExecutionError(
                    f"Failed to execute python step '{step.name}': {e}"
                ) from e

            if result.returncode != 0:
                error_msg = (
                    result.stderr.strip()
                    if result.stderr
                    else f"Exit code {result.returncode}"
                )
                raise WorkflowExecutionError(
                    f"Python step '{step.name}' failed: {error_msg}"
                )

            output = parse_bash_output(result.stdout)
            # Handle _chdir special output: change executor's working directory
            if "_chdir" in output:
                chdir_path = str(output.pop("_chdir"))
                if not os.path.isabs(chdir_path):
                    chdir_path = os.path.abspath(chdir_path)
                os.chdir(chdir_path)
            context[step.name] = output

        elif step.is_agent_step() and step.agent:
            from sase.llm_provider import invoke_agent
            from sase.shared_utils import ensure_str_content
            from sase.xprompt import process_xprompt_references

            rendered_prompt = render_template(step.agent, context)
            expanded_prompt = process_xprompt_references(rendered_prompt)

            # Create temp artifacts dir if not provided
            step_artifacts_dir = artifacts_dir
            if step_artifacts_dir is None:
                from sase.sase_utils import get_sase_tmpdir

                step_artifacts_dir = tempfile.mkdtemp(
                    prefix=f"embedded-{workflow_name}-",
                    dir=get_sase_tmpdir(),
                )

            response = invoke_agent(
                expanded_prompt,
                agent_type=f"embedded-{workflow_name}-{step.name}",
                artifacts_dir=step_artifacts_dir,
            )
            response_text = ensure_str_content(response.content)

            # Store raw output for prompt steps
            context[step.name] = {"_raw": response_text}

    return context


def run_query(
    query: str,
    previous_history: str | None = None,
) -> None:
    """Execute a query through the unified workflow path.

    Creates an anonymous workflow and routes through WorkflowExecutor,
    producing workflow_state.json and step markers for TUI visibility.

    Args:
        query: The query to send to the agent.
        previous_history: Optional previous conversation history to continue from.
    """
    from sase.sase_utils import generate_timestamp
    from sase.xprompt.models import create_anonymous_workflow
    from sase.xprompt.workflow_runner import execute_workflow

    # Resolve VCS refs early so project-specific workflows are discoverable
    # and CWD-relative paths in workflow steps work correctly.  This mirrors
    # the TUI behavior where subprocess CWD is set before workflow execution.
    vcs_project = _resolve_vcs_cwd(query)

    # Get project info for workspace claiming (creates project file if needed)
    project_file, workspace_num, _ = ensure_project_file_and_get_workspace_num()

    # Resolve aliases before saving so history stores canonical names
    from sase.xprompt import resolve_xprompt_aliases

    query = resolve_xprompt_aliases(query)

    # Save prompt to history immediately (only for new queries, not resume)
    # This ensures the prompt is visible in `sase run .` from other terminals
    if previous_history is None:
        from sase.prompt_history import add_or_update_prompt

        add_or_update_prompt(query)

    try:
        # Build the full prompt
        if previous_history:
            full_prompt = f"""# Previous Conversation

{previous_history}

---

# New Query

{query}"""
        else:
            full_prompt = query

        # Convert escaped newlines to actual newlines
        full_prompt = full_prompt.replace("\\n", "\n")

        # Capture start timestamp for accurate duration calculation
        shared_timestamp = generate_timestamp()

        # Create artifacts directory for prompt persistence
        artifacts_timestamp: str | None = None
        try:
            artifacts_dir: str | None = create_artifacts_directory("run")
            # Extract timestamp from the directory path (last component)
            if artifacts_dir:
                artifacts_timestamp = os.path.basename(artifacts_dir)
        except RuntimeError:
            # Not in a recognized project - skip artifacts
            artifacts_dir = None

        # Claim workspace with artifacts timestamp for prompt lookup
        if project_file and workspace_num:
            claim_workspace(
                project_file,
                workspace_num,
                "run",
                os.getpid(),
                None,
                artifacts_timestamp=artifacts_timestamp,
            )

        # Create anonymous workflow and execute through WorkflowExecutor
        anon_workflow = create_anonymous_workflow(full_prompt)
        result = execute_workflow(
            anon_workflow.name,
            [],
            {},
            artifacts_dir=artifacts_dir,
            workflow_obj=anon_workflow,
            project=vcs_project,
        )

        # Extract response text for chat history
        response_content = result.response_text or ""

        # Prepare and save chat history
        saved_path = save_chat_history(
            prompt=query,
            response=response_content,
            workflow="run",
            previous_history=previous_history,
            timestamp=shared_timestamp,
        )

        print(f"\nChat history saved to: {saved_path}")

        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="user-agent",
            cl_name=None,
            success=True,
            notes=["Workflow completed via sase run"],
            action=None,
        )
    except Exception:
        from sase.notifications.senders import notify_workflow_complete

        notify_workflow_complete(
            sender="user-agent",
            cl_name=None,
            success=False,
            notes=["Workflow failed via sase run"],
            action=None,
        )
        raise
    finally:
        # Release workspace when done
        if project_file and workspace_num:
            release_workspace(project_file, workspace_num, "run", None)
