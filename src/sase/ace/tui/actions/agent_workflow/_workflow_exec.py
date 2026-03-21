"""Workflow execution mixin for agent workflow."""

from __future__ import annotations

import logging
import os
import sys
from typing import TYPE_CHECKING

from ._types import PromptContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


class WorkflowExecMixin:
    """Mixin providing workflow execution functionality."""

    # Type hint for attribute from AgentLaunchMixin (resolved at runtime via MRO)
    _prompt_context: PromptContext | None

    def _try_execute_workflow(self, prompt: str) -> bool | str:
        """Try to execute a workflow reference.

        Args:
            prompt: The prompt starting with # (e.g., "#test_workflow" or "#split(arg)").

        Returns:
            True if workflow was executed, False if not a valid workflow reference,
            or a str with the rendered prompt for simple xprompts.
        """
        from sase.xprompt import (
            get_all_prompts,
            parse_workflow_reference,
            strip_hitl_suffix,
        )

        workflow_ref = prompt[1:]  # Strip the #
        workflow_ref, hitl_override = strip_hitl_suffix(workflow_ref)
        workflow_name, positional_args, named_args = parse_workflow_reference(
            workflow_ref
        )

        project = None
        if "/" in workflow_name:
            project = workflow_name.split("/")[0]

        # Use get_all_prompts() to detect both workflows and simple xprompts
        prompts = get_all_prompts(project=project)
        if workflow_name not in prompts:
            return False

        workflow = prompts[workflow_name]

        # Simple xprompts: expand inline instead of spawning workflow
        if workflow.is_simple_xprompt():
            from sase.xprompt.models import UNSET
            from sase.xprompt.workflow_executor_utils import render_template

            render_ctx: dict[str, object] = dict(named_args)
            for i, value in enumerate(positional_args):
                if i < len(workflow.inputs):
                    input_arg = workflow.inputs[i]
                    if input_arg.name not in render_ctx:
                        render_ctx[input_arg.name] = value
            for input_arg in workflow.inputs:
                if input_arg.name not in render_ctx and input_arg.default is not UNSET:
                    render_ctx[input_arg.name] = (
                        "null" if input_arg.default is None else str(input_arg.default)
                    )
            content = workflow.get_prompt_part_content()
            return render_template(content, render_ctx)

        # Multi-step workflows with prompt_part are designed for embedding,
        # not standalone execution (e.g., #gh, #hg)
        if workflow.has_prompt_part():
            return False

        # Check if we have changespec context (not home mode)
        ctx = self._prompt_context
        has_changespec_context = (
            ctx is not None and not ctx.is_home_mode and ctx.project_file
        )

        if has_changespec_context:
            # Launch as subprocess with workspace claiming
            return self._launch_workflow_subprocess(
                workflow_name, positional_args, named_args, hitl_override=hitl_override
            )

        # Original behavior: daemon thread for home mode or no context
        return self._execute_workflow_in_thread(
            workflow_name, positional_args, named_args, hitl_override=hitl_override
        )

    def _execute_workflow_in_thread(
        self,
        workflow_name: str,
        positional_args: list[str],
        named_args: dict[str, str],
        hitl_override: bool | None = None,
    ) -> bool:
        """Execute workflow in a daemon thread (for home mode).

        Args:
            workflow_name: Name of the workflow to execute.
            positional_args: Positional arguments for the workflow.
            named_args: Named arguments for the workflow.

        Returns:
            True if workflow was started, False on error.
        """
        from datetime import datetime
        from pathlib import Path

        from sase.xprompt import execute_workflow

        # Create proper artifacts directory for workflow state persistence
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        base_workflow = (
            workflow_name.split("/")[-1] if "/" in workflow_name else workflow_name
        )
        artifacts_dir = (
            Path.home()
            / ".sase"
            / "projects"
            / "home"
            / "artifacts"
            / f"workflow-{base_workflow}"
            / timestamp
        )
        artifacts_dir.mkdir(parents=True, exist_ok=True)

        try:
            # Execute workflow in background thread to not block TUI
            import threading

            # Extract project from workflow_name (e.g., "eval/foo" → "eval")
            project: str | None = None
            if "/" in workflow_name:
                project = workflow_name.split("/")[0]

            def run_workflow() -> None:
                try:
                    execute_workflow(
                        workflow_name,
                        positional_args,
                        named_args,
                        artifacts_dir=str(artifacts_dir),
                        silent=True,
                        project=project,
                        hitl_override=hitl_override,
                    )
                except Exception:
                    log.exception("Workflow '%s' failed", workflow_name)
                    self.call_later(  # type: ignore[attr-defined]
                        lambda: self.notify(  # type: ignore[attr-defined]
                            f"Workflow '{workflow_name}' failed (see log)",
                            severity="error",
                        )
                    )

            thread = threading.Thread(target=run_workflow, daemon=True)
            thread.start()
            self.notify(f"Workflow '{workflow_name}' started")  # type: ignore[attr-defined]
            return True
        except Exception as e:
            log.exception("Workflow '%s' failed to start", workflow_name)
            self.notify(f"Workflow error: {e}", severity="error")  # type: ignore[attr-defined]
            return False

    def _launch_workflow_subprocess(
        self,
        workflow_name: str,
        positional_args: list[str],
        named_args: dict[str, str],
        hitl_override: bool | None = None,
    ) -> bool:
        """Launch workflow as subprocess with workspace claiming.

        Args:
            workflow_name: Name of the workflow to execute.
            positional_args: Positional arguments for the workflow.
            named_args: Named arguments for the workflow.

        Returns:
            True if workflow was started, False on error.
        """
        import json
        import subprocess
        from datetime import datetime

        from sase.running_field import claim_workspace

        ctx = self._prompt_context
        if ctx is None:
            self.notify("No prompt context", severity="error")  # type: ignore[attr-defined]
            return False

        # Build artifacts directory using project context
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        project_name = os.path.basename(os.path.dirname(ctx.project_file))
        base_workflow = (
            workflow_name.split("/")[-1] if "/" in workflow_name else workflow_name
        )
        artifacts_dir = os.path.expanduser(
            f"~/.sase/projects/{project_name}/artifacts/workflow-{base_workflow}/{timestamp}"
        )
        os.makedirs(artifacts_dir, exist_ok=True)

        # Build runner script path
        # From src/ace/tui/actions/agent_workflow/ we need 5 dirname calls to get to src/
        runner_script = os.path.join(
            os.path.dirname(
                os.path.dirname(
                    os.path.dirname(
                        os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                    )
                )
            ),
            "axe",
            "run_workflow_runner.py",
        )

        # Build output log path
        output_path = os.path.join(artifacts_dir, "workflow.log")

        # Inject cl_name from display context so the runner knows the CL name
        if ctx.display_name:
            named_args = dict(named_args)
            named_args.setdefault("cl_name", ctx.display_name)

        # Launch subprocess with output redirection
        try:
            with open(output_path, "w") as output_file:
                process = subprocess.Popen(
                    [
                        sys.executable,
                        runner_script,
                        workflow_name,
                        json.dumps(positional_args),
                        json.dumps(named_args),
                        ctx.project_file,
                        ctx.workspace_dir,
                        str(ctx.workspace_num),
                        artifacts_dir,
                        ctx.update_target,
                        "",  # not home mode
                        (
                            "1"
                            if hitl_override is True
                            else ("0" if hitl_override is False else "")
                        ),
                    ],
                    cwd=ctx.workspace_dir,
                    stdout=output_file,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,  # Detach from TUI process
                    env=os.environ,
                )
        except Exception as e:
            log.exception("Failed to start workflow subprocess for '%s'", workflow_name)
            self.notify(f"Failed to start workflow: {e}", severity="error")  # type: ignore[attr-defined]
            return False

        # Claim workspace with subprocess PID
        workflow_field_name = f"workflow({workflow_name})"
        if not claim_workspace(
            ctx.project_file,
            ctx.workspace_num,
            workflow_field_name,
            process.pid,
            ctx.display_name,
            artifacts_timestamp=timestamp,
        ):
            self.notify("Failed to claim workspace", severity="error")  # type: ignore[attr-defined]
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            return False

        self.notify(f"Workflow '{workflow_name}' started")  # type: ignore[attr-defined]
        return True
