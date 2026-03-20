"""Script step execution mixin (bash and python steps)."""

import os
import subprocess
import sys
import threading
from typing import TYPE_CHECKING, Any

from sase.xprompt.workflow_executor_types import HITLHandler, output_types_from_step
from sase.xprompt.workflow_executor_utils import (
    coerce_output_types,
    parse_bash_output,
    render_template,
)
from sase.xprompt.workflow_models import (
    StepState,
    StepStatus,
    WorkflowExecutionError,
    WorkflowState,
)

if TYPE_CHECKING:
    from sase.xprompt.workflow_models import WorkflowStep
    from sase.xprompt.workflow_output import WorkflowOutputHandler


class ScriptStepMixin:
    """Mixin class providing bash and python step execution.

    This mixin requires the following attributes on self:
        - context: dict[str, Any]
        - artifacts_dir: str
        - hitl_handler: HITLHandler | None
        - state: WorkflowState

    This mixin requires the following methods on self:
        - _save_state() -> None
        - _save_prompt_step_marker(step_name, step_state, ...) -> None
    """

    # Type hints for attributes from WorkflowExecutor
    context: dict[str, Any]
    artifacts_dir: str
    hitl_handler: HITLHandler | None
    output_handler: "WorkflowOutputHandler | None"
    state: WorkflowState

    # Method stubs for type checking - implemented in main class
    def _should_hitl(self, step: "WorkflowStep") -> bool:
        """Determine whether HITL review is required for a step."""
        raise NotImplementedError

    def _save_state(self) -> None:
        """Save workflow state to JSON file."""
        raise NotImplementedError

    def _save_prompt_step_marker(
        self,
        step_name: str,
        step_state: StepState,
        step_type: str = "agent",
        step_source: str | None = None,
        step_index: int | None = None,
        parent_step_index: int | None = None,
        parent_total_steps: int | None = None,
        is_pre_prompt_step: bool = False,
        diff_path: str | None = None,
        hidden: bool = False,
        output_types: dict[str, str] | None = None,
        embedded_workflow_name: str | None = None,
    ) -> None:
        """Save a marker file for prompt steps to track them in the TUI."""
        raise NotImplementedError

    def _execute_bash_step(
        self,
        step: "WorkflowStep",
        step_state: StepState,
    ) -> bool:
        """Execute a bash step.

        Args:
            step: The workflow step definition.
            step_state: The runtime state for this step.

        Returns:
            True if step succeeded, False if rejected by user.
        """
        if not step.bash:
            raise WorkflowExecutionError(f"Bash step '{step.name}' has no command")

        # Render command with Jinja2 context
        rendered_command = render_template(step.bash, self.context)

        # Build env with Python's bin dir on PATH so that sase entry-point
        # scripts (e.g. sase_cl_workflow) are discoverable by /bin/sh.
        env = os.environ.copy()
        python_bin_dir = os.path.dirname(sys.executable)
        current_path = env.get("PATH", "")
        if python_bin_dir not in current_path.split(os.pathsep):
            env["PATH"] = python_bin_dir + os.pathsep + current_path

        # Execute command
        try:
            result = subprocess.run(
                rendered_command,
                shell=True,
                capture_output=True,
                text=True,
                cwd=os.getcwd(),
                env=env,
            )
        except Exception as e:
            raise WorkflowExecutionError(
                f"Failed to execute bash step '{step.name}': {e}"
            ) from e

        if result.returncode != 0:
            error_msg = (
                result.stderr.strip()
                if result.stderr
                else (
                    result.stdout.strip()
                    if result.stdout
                    else f"Exit code {result.returncode}"
                )
            )
            raise WorkflowExecutionError(f"Bash step '{step.name}' failed: {error_msg}")

        # Save stdout artifact before parsing key=value output
        artifact_path: str | None = None
        if step.artifact == "stdout" and result.stdout.strip():
            artifact_path = os.path.join(self.artifacts_dir, f"{step.name}.stdout")
            with open(artifact_path, "w") as f:
                f.write(result.stdout)

        # Parse output
        output = parse_bash_output(result.stdout)

        # Coerce types based on output schema (e.g. "true" → True for bool fields)
        step_output_types = output_types_from_step(step)
        if step_output_types:
            coerce_output_types(output, step_output_types)

        # Validate output against schema if specified
        if step.output and step.output.schema:
            from sase.xprompt.output_validation import validate_against_schema

            is_valid, validation_err = validate_against_schema(
                output, step.output.schema
            )
            if not is_valid:
                raise WorkflowExecutionError(
                    f"Bash step '{step.name}' output validation failed: {validation_err}"
                )

        # Make path fields absolute for cross-process HITL communication
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
                step_type="bash",
                step_source=rendered_command,
                hidden=step.hidden,
                embedded_workflow_name=getattr(
                    self, "_current_embedded_workflow_name", None
                ),
            )

            result_hitl = self.hitl_handler.prompt(
                step.name,
                "bash",
                output,
                has_output=step.output is not None,
                output_types=output_types_from_step(step),
            )

            if result_hitl.action == "reject":
                return False
            elif result_hitl.action == "accept":
                # Set approved flag in output for subsequent steps
                output["approved"] = True
            elif result_hitl.action == "edit":
                if result_hitl.edited_output is not None:
                    output = result_hitl.edited_output
                # Continue with edited output
            # Future: handle rerun

            # Resume running status after HITL acceptance
            self.state.status = "running"
            self._save_state()

        # Mark step completed after HITL
        step_state.status = StepStatus.COMPLETED
        self._save_prompt_step_marker(
            step.name,
            step_state,
            step_type="bash",
            step_source=rendered_command,
            hidden=step.hidden,
            embedded_workflow_name=getattr(
                self, "_current_embedded_workflow_name", None
            ),
        )

        # Handle _chdir special output: change executor's working directory
        if "_chdir" in output:
            chdir_path = str(output.pop("_chdir"))
            if not os.path.isabs(chdir_path):
                chdir_path = os.path.abspath(chdir_path)
            os.chdir(chdir_path)

        # Add artifact path to output if created
        if artifact_path is not None:
            output["_artifact"] = artifact_path

        # Store output in context under step name
        step_state.output = output
        self.context[step.name] = output
        self.state.context = dict(self.context)

        return True

    def _execute_python_step(
        self,
        step: "WorkflowStep",
        step_state: StepState,
    ) -> bool:
        """Execute a python step.

        Args:
            step: The workflow step definition.
            step_state: The runtime state for this step.

        Returns:
            True if step succeeded, False if rejected by user.
        """
        if not step.python:
            raise WorkflowExecutionError(f"Python step '{step.name}' has no code")

        # Render code with Jinja2 context
        rendered_code = render_template(step.python, self.context)

        # Execute python code using the same interpreter.
        # stderr is streamed in real-time so long-running subprocesses
        # (e.g. sase_hg_sync) surface progress output as it happens,
        # while also being collected for error reporting on failure.
        try:
            proc = subprocess.Popen(
                [sys.executable, "-c", rendered_code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=os.getcwd(),
            )
        except Exception as e:
            raise WorkflowExecutionError(
                f"Failed to execute python step '{step.name}': {e}"
            ) from e

        # Stream stderr to the terminal in real-time while collecting it.
        stderr_lines: list[str] = []

        def _stream_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                sys.stderr.write(line)
                sys.stderr.flush()
                stderr_lines.append(line)

        stderr_thread = threading.Thread(target=_stream_stderr)
        stderr_thread.start()

        assert proc.stdout is not None
        stdout = proc.stdout.read()
        proc.wait()
        stderr_thread.join()
        captured_stderr = "".join(stderr_lines)

        if proc.returncode != 0:
            # Prefer stderr (contains tracebacks), fall back to stdout,
            # then to a bare exit-code message.
            error_msg = (
                captured_stderr.strip()
                or stdout.strip()
                or f"Exit code {proc.returncode}"
            )
            raise WorkflowExecutionError(
                f"Python step '{step.name}' failed: {error_msg}"
            )

        # Save stdout artifact before parsing key=value output
        artifact_path: str | None = None
        if step.artifact == "stdout" and stdout.strip():
            artifact_path = os.path.join(self.artifacts_dir, f"{step.name}.stdout")
            with open(artifact_path, "w") as f:
                f.write(stdout)

        # Parse output (same formats as bash: JSON, key=value, plain text)
        output = parse_bash_output(stdout)

        # Coerce types based on output schema (e.g. "true" → True for bool fields)
        step_output_types = output_types_from_step(step)
        if step_output_types:
            coerce_output_types(output, step_output_types)

        # Validate output against schema if specified
        if step.output and step.output.schema:
            from sase.xprompt.output_validation import validate_against_schema

            is_valid, validation_err = validate_against_schema(
                output, step.output.schema
            )
            if not is_valid:
                raise WorkflowExecutionError(
                    f"Python step '{step.name}' output validation failed: "
                    f"{validation_err}"
                )

        # Make path fields absolute for cross-process HITL communication
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
                step_type="python",
                step_source=rendered_code,
                hidden=step.hidden,
                embedded_workflow_name=getattr(
                    self, "_current_embedded_workflow_name", None
                ),
            )

            result_hitl = self.hitl_handler.prompt(
                step.name,
                "python",
                output,
                has_output=step.output is not None,
                output_types=output_types_from_step(step),
            )

            if result_hitl.action == "reject":
                return False
            elif result_hitl.action == "accept":
                # Set approved flag in output for subsequent steps
                output["approved"] = True
            elif result_hitl.action == "edit":
                if result_hitl.edited_output is not None:
                    output = result_hitl.edited_output
                # Continue with edited output
            # Future: handle rerun

            # Resume running status after HITL acceptance
            self.state.status = "running"
            self._save_state()

        # Mark step completed after HITL
        step_state.status = StepStatus.COMPLETED
        self._save_prompt_step_marker(
            step.name,
            step_state,
            step_type="python",
            step_source=rendered_code,
            hidden=step.hidden,
            embedded_workflow_name=getattr(
                self, "_current_embedded_workflow_name", None
            ),
        )

        # Handle _chdir special output: change executor's working directory
        if "_chdir" in output:
            chdir_path = str(output.pop("_chdir"))
            if not os.path.isabs(chdir_path):
                chdir_path = os.path.abspath(chdir_path)
            os.chdir(chdir_path)

        # Add artifact path to output if created
        if artifact_path is not None:
            output["_artifact"] = artifact_path

        # Store output in context under step name
        step_state.output = output
        self.context[step.name] = output
        self.state.context = dict(self.context)

        return True
