"""Workflow execution mixin for agent workflow."""

from __future__ import annotations

# ``call_later`` usages in this module intentionally marshal synchronous
# ``notify`` lambdas from launch/background-thread paths. Workflow execution
# itself runs in a daemon thread or subprocess and is never awaited by the pump.

import logging
import os
import sys
from typing import TYPE_CHECKING

from sase.core.paths import sase_projects_dir

from ..failure_messages import with_log_panel_hint
from ._types import PromptContext

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    pass


def _stash_failed_workflow_prompt(submitted_prompt: str | None) -> None:
    """Preserve a lost workflow-launch prompt in the stash (best-effort)."""
    if submitted_prompt is None:
        return
    from sase.agent.failed_launch_prompt_stash import stash_failed_launch_prompt

    stash_failed_launch_prompt(submitted_prompt)


class WorkflowExecMixin:
    """Mixin providing workflow execution functionality."""

    # Type hint for attribute from AgentLaunchMixin (resolved at runtime via MRO)
    _prompt_context: PromptContext | None

    def _try_execute_workflow(
        self,
        prompt: str,
        has_vcs_ref: bool = False,
        *,
        submitted_prompt: str | None = None,
    ) -> bool | str:
        """Try to execute a workflow reference.

        Args:
            prompt: The prompt starting with # (e.g., "#test_workflow" or "#split(arg)").
            has_vcs_ref: True if the original prompt contained a VCS ref (e.g.,
                "#gh:sase"). When True, simple xprompts are not rendered here —
                the caller will expand them downstream via
                ``process_xprompt_references`` (which splits colon args on
                commas), and the rendered value would be discarded anyway.
            submitted_prompt: The original prompt-bar submission, preserved in
                the prompt stash if a workflow start/claim failure loses it.

        Returns:
            True if workflow was executed, False if not a valid workflow reference,
            or a str with the rendered prompt for simple xprompts.
        """
        from sase.xprompt import (
            get_all_prompts,
            iter_xprompt_references,
            parse_workflow_reference,
            strip_hitl_suffix,
        )

        refs = iter_xprompt_references(prompt)
        leading_ref = refs[0] if refs and refs[0].start == 0 else None
        exact_ref = (
            leading_ref
            if leading_ref is not None and leading_ref.end == len(prompt.strip())
            else None
        )

        if exact_ref is not None:
            workflow_name = exact_ref.name
            positional_args, named_args = exact_ref.parse_arguments()
            hitl_override = exact_ref.hitl_override
            explicit_standalone_marker = exact_ref.is_standalone_marker
        else:
            workflow_ref = prompt[1:]  # Strip the #
            workflow_ref, hitl_override = strip_hitl_suffix(workflow_ref)
            workflow_name, positional_args, named_args = parse_workflow_reference(
                workflow_ref
            )
            explicit_standalone_marker = False

        project = None
        if "/" in workflow_name:
            project = workflow_name.split("/")[0]
            from sase.agent.launch_projects import enable_known_project_for_launch_ref

            try:
                enable_known_project_for_launch_ref(project)
            except RuntimeError as exc:
                message = str(exc)
                _stash_failed_workflow_prompt(submitted_prompt)
                self.call_later(  # type: ignore[attr-defined]
                    lambda: self.notify(  # type: ignore[attr-defined]
                        message,
                        severity="error",
                    )
                )
                return True

        # Use get_all_prompts() to detect both workflows and simple xprompts
        prompts = get_all_prompts(project=project)
        if workflow_name not in prompts:
            return False

        workflow = prompts[workflow_name]
        if explicit_standalone_marker and workflow.has_prompt_part():
            from sase.xprompt.workflow_runner import invalid_explicit_standalone_message

            msg = invalid_explicit_standalone_message(workflow_name)
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(msg, severity="error")  # type: ignore[attr-defined]
            )
            return True

        if exact_ref is None:
            return False

        # Simple xprompts: expand inline instead of spawning workflow.
        # When the caller has a VCS ref, the rendered value is discarded —
        # defer to process_xprompt_references() downstream, which handles
        # colon-comma args correctly.
        if workflow.is_simple_xprompt():
            if has_vcs_ref:
                return False

            from sase.xprompt.input_binding import bind_input_args
            from sase.xprompt.workflow_executor_utils import render_template

            render_ctx = bind_input_args(
                workflow.inputs, positional_args, named_args
            ).values
            content = workflow.get_prompt_part_content()
            return render_template(content, render_ctx)

        # Multi-step workflows with prompt_part are designed for embedding,
        # not standalone execution (e.g. registered workspace workflows)
        if workflow.has_prompt_part():
            return False

        if not explicit_standalone_marker:
            from sase.xprompt.workflow_runner import standalone_deprecation_message

            msg = standalone_deprecation_message(workflow_name)
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(msg, severity="warning")  # type: ignore[attr-defined]
            )

        # Check if we have patch context (not home mode)
        ctx = self._prompt_context
        has_patch_context = (
            ctx is not None and not ctx.is_home_mode and ctx.project_file
        )

        if has_patch_context:
            # Launch as subprocess with workspace claiming
            return self._launch_workflow_subprocess(
                workflow_name,
                positional_args,
                named_args,
                hitl_override=hitl_override,
                submitted_prompt=submitted_prompt,
            )

        # Original behavior: daemon thread for home mode or no context
        return self._execute_workflow_in_thread(
            workflow_name,
            positional_args,
            named_args,
            hitl_override=hitl_override,
            submitted_prompt=submitted_prompt,
        )

    def _execute_workflow_in_thread(
        self,
        workflow_name: str,
        positional_args: list[str],
        named_args: dict[str, str],
        hitl_override: bool | None = None,
        *,
        submitted_prompt: str | None = None,
    ) -> bool:
        """Execute workflow in a daemon thread (for home mode).

        Args:
            workflow_name: Name of the workflow to execute.
            positional_args: Positional arguments for the workflow.
            named_args: Named arguments for the workflow.

        Returns:
            True if workflow was started, False on error.
        """
        from pathlib import Path

        from sase.core.time import local_now
        from sase.xprompt import execute_workflow

        # Create proper artifacts directory for workflow state persistence
        timestamp = local_now().strftime("%Y%m%d%H%M%S")
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
                except Exception as exc:
                    log.exception("Workflow '%s' failed", workflow_name)
                    from sase.logs import log_launch_failure

                    log_launch_failure(
                        kind="workflow",
                        display_name=workflow_name,
                        exc=exc,
                        project=project,
                        workflow_name=workflow_name,
                    )
                    self.call_later(  # type: ignore[attr-defined]
                        lambda: self.notify(  # type: ignore[attr-defined]
                            with_log_panel_hint(f"Workflow '{workflow_name}' failed"),
                            severity="error",
                        )
                    )

            thread = threading.Thread(target=run_workflow, daemon=True)
            thread.start()
            started_msg = f"Workflow '{workflow_name}' started"
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(started_msg)  # type: ignore[attr-defined]
            )
            return True
        except Exception as e:
            log.exception("Workflow '%s' failed to start", workflow_name)
            from sase.logs import log_launch_failure

            _stash_failed_workflow_prompt(submitted_prompt)
            log_launch_failure(
                kind="workflow",
                display_name=workflow_name,
                exc=e,
                project=(workflow_name.split("/")[0] if "/" in workflow_name else None),
                workflow_name=workflow_name,
                stage="start",
            )
            err_msg = f"Workflow error: {e}"
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(err_msg, severity="error")  # type: ignore[attr-defined]
            )
            return False

    def _launch_workflow_subprocess(
        self,
        workflow_name: str,
        positional_args: list[str],
        named_args: dict[str, str],
        hitl_override: bool | None = None,
        *,
        submitted_prompt: str | None = None,
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

        from sase.core.time import local_now
        from sase.running_field import claim_workspace

        ctx = self._prompt_context
        if ctx is None:
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(  # type: ignore[attr-defined]
                    "No prompt context", severity="error"
                )
            )
            return False

        # Build artifacts directory using project context
        timestamp = local_now().strftime("%Y%m%d%H%M%S")
        project_name = os.path.basename(os.path.dirname(ctx.project_file))
        base_workflow = (
            workflow_name.split("/")[-1] if "/" in workflow_name else workflow_name
        )
        artifacts_dir = str(
            sase_projects_dir()
            / project_name
            / "artifacts"
            / f"workflow-{base_workflow}"
            / timestamp
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

        # Inject cl_name from display context so the runner knows the Patch name
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
            _stash_failed_workflow_prompt(submitted_prompt)
            err_msg = f"Failed to start workflow: {e}"
            self.call_later(  # type: ignore[attr-defined]
                lambda: self.notify(err_msg, severity="error")  # type: ignore[attr-defined]
            )
            return False

        # Claim workspace with subprocess PID
        workflow_field_name = f"workflow({workflow_name})"
        claim_result = claim_workspace(
            ctx.project_file,
            ctx.workspace_num,
            workflow_field_name,
            process.pid,
            ctx.display_name,
            artifacts_timestamp=timestamp,
        )
        if not claim_result.success:
            err = claim_result.error or "unknown reason"
            _stash_failed_workflow_prompt(submitted_prompt)
            self.call_later(  # type: ignore[attr-defined]
                lambda err=err: self.notify(  # type: ignore[attr-defined]
                    f"Failed to claim workspace: {err}", severity="error"
                )
            )
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            return False

        started_msg = f"Workflow '{workflow_name}' started"
        self.call_later(  # type: ignore[attr-defined]
            lambda: self.notify(started_msg)  # type: ignore[attr-defined]
        )
        return True
