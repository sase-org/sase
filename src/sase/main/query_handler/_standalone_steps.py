"""Standalone workflow step execution outside the full WorkflowExecutor."""

import os
import tempfile
from typing import Any

from sase.xprompt.workflow_models import WorkflowStep


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

    from sase.xprompt.workflow_executor_types import output_types_from_step
    from sase.xprompt.workflow_executor_utils import (
        coerce_output_types,
        parse_bash_output,
        render_template,
    )
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

            # Save stdout artifact before parsing key=value output
            artifact_path: str | None = None
            if step.artifact == "stdout" and result.stdout.strip() and artifacts_dir:
                artifact_path = os.path.join(artifacts_dir, f"{step.name}.stdout")
                with open(artifact_path, "w") as f:
                    f.write(result.stdout)

            output = parse_bash_output(result.stdout)
            step_output_types = output_types_from_step(step)
            if step_output_types:
                coerce_output_types(output, step_output_types)
            # Handle _chdir special output: change executor's working directory
            if "_chdir" in output:
                chdir_path = str(output.pop("_chdir"))
                if not os.path.isabs(chdir_path):
                    chdir_path = os.path.abspath(chdir_path)
                os.chdir(chdir_path)
            if artifact_path is not None:
                output["_artifact"] = artifact_path
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

            # Save stdout artifact before parsing key=value output
            artifact_path_py: str | None = None
            if step.artifact == "stdout" and result.stdout.strip() and artifacts_dir:
                artifact_path_py = os.path.join(artifacts_dir, f"{step.name}.stdout")
                with open(artifact_path_py, "w") as f:
                    f.write(result.stdout)

            output = parse_bash_output(result.stdout)
            step_output_types = output_types_from_step(step)
            if step_output_types:
                coerce_output_types(output, step_output_types)
            # Handle _chdir special output: change executor's working directory
            if "_chdir" in output:
                chdir_path = str(output.pop("_chdir"))
                if not os.path.isabs(chdir_path):
                    chdir_path = os.path.abspath(chdir_path)
                os.chdir(chdir_path)
            if artifact_path_py is not None:
                output["_artifact"] = artifact_path_py
            context[step.name] = output

        elif step.is_agent_step() and step.agent:
            from sase.content import ensure_str_content
            from sase.llm_provider import LLMInvocationError, invoke_agent
            from sase.xprompt import process_xprompt_references

            rendered_prompt = render_template(step.agent, context)
            expanded_prompt = process_xprompt_references(rendered_prompt)

            # Create temp artifacts dir if not provided
            step_artifacts_dir = artifacts_dir
            if step_artifacts_dir is None:
                from sase.core.paths import get_sase_tmpdir

                step_artifacts_dir = tempfile.mkdtemp(
                    prefix=f"embedded-{workflow_name}-",
                    dir=get_sase_tmpdir(),
                )

            try:
                response = invoke_agent(
                    expanded_prompt,
                    agent_type=f"embedded-{workflow_name}-{step.name}",
                    artifacts_dir=step_artifacts_dir,
                )
                response_text = ensure_str_content(response.content)
            except LLMInvocationError as e:
                response_text = str(e)

            # Store raw output for prompt steps
            context[step.name] = {"_raw": response_text}

    return context
