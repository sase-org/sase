"""Workflow display mixin for the agent prompt panel."""

import json
from pathlib import Path
from typing import Any

from rich.console import Group
from rich.syntax import Syntax
from rich.text import Text

from ...models.agent import Agent
from ._helpers import aggregate_meta_fields, format_output, get_status_indicator


class WorkflowDisplayMixin:
    """Mixin providing workflow-specific display methods for AgentPromptPanel."""

    def _update_workflow_display(self, agent: Agent) -> None:
        """Update display for a workflow agent.

        Args:
            agent: The workflow agent to display.
        """
        header_text = Text()

        # Header - WORKFLOW DETAILS
        header_text.append("WORKFLOW DETAILS\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        # Workflow name (stored in workflow field)
        header_text.append("Workflow: ", style="bold #87D7FF")
        header_text.append(f"{agent.workflow or 'unknown'}\n", style="#AF87D7 bold")

        # Extract meta_* overrides from step outputs
        meta_project = None
        meta_changespec = None
        meta_workspace = None
        meta_fields_data = self._load_workflow_meta_raw(agent)
        if meta_fields_data:
            meta_project = meta_fields_data.get("meta_project")
            meta_changespec = meta_fields_data.get("meta_changespec")
            meta_workspace = meta_fields_data.get("meta_workspace")

        # Project/ChangeSpec with meta_* priority
        if meta_project:
            header_text.append("Project: ", style="bold #87D7FF")
            header_text.append(f"{meta_project}\n", style="#00D7AF")
        elif meta_changespec:
            header_text.append("ChangeSpec: ", style="bold #87D7FF")
            header_text.append(f"{meta_changespec}\n", style="#00D7AF")
        else:
            header_text.append("ChangeSpec: ", style="bold #87D7FF")
            header_text.append(f"{agent.cl_name}\n", style="#00D7AF")

        # Workspace (if available) - check meta_workspace first, then agent field
        workspace_num = meta_workspace or agent.workspace_num
        if workspace_num is not None:
            header_text.append("Workspace: ", style="bold #87D7FF")
            header_text.append(f"#{workspace_num}\n", style="#5FD7FF")

        # Model (if explicitly set via %model directive)
        if agent.model:
            header_text.append("Model: ", style="bold #87D7FF")
            header_text.append(f"{agent.model}\n", style="#AF87D7")

        # VCS provider
        if agent.vcs_provider:
            header_text.append("VCS: ", style="bold #87D7FF")
            header_text.append(f"{agent.vcs_provider}\n", style="#5FD7AF")

        # Status
        header_text.append("Status: ", style="bold #87D7FF")
        status_style = {
            "RUNNING": "#87D7FF",
            "WAITING INPUT": "#FFAF5F",
            "DONE": "#5FD75F",
            "FAILED": "#FF5F5F",
        }.get(agent.status, "#D7D7FF")
        header_text.append(f"{agent.status}\n", style=status_style)

        # Timestamp
        header_text.append("Timestamp: ", style="bold #87D7FF")
        header_text.append(f"{agent.start_time_display}\n", style="#D7D7FF")

        # PID (if available)
        if agent.pid:
            header_text.append("PID: ", style="bold #87D7FF")
            header_text.append(f"{agent.pid}\n", style="#FF87D7 bold")

        # Meta fields aggregated from all step outputs
        meta_fields = self._load_workflow_meta_fields(agent)
        if meta_fields:
            header_text.append("\n")
            for name, value in meta_fields:
                header_text.append(f"{name}: ", style="bold #87D7FF")
                header_text.append(f"{value}\n", style="#5FD75F")

        # Inputs (if available)
        inputs = self._load_workflow_inputs(agent)
        if inputs:
            header_text.append("\n")
            header_text.append("INPUTS\n", style="bold #D7AF5F underline")
            for key, value in inputs.items():
                header_text.append(f"  {key}: ", style="bold #87D7FF")
                if isinstance(value, str):
                    header_text.append(f'"{value}"\n', style="#5FD75F")
                else:
                    header_text.append(f"{value}\n", style="#5FD75F")

        # Separator
        header_text.append("\n")
        header_text.append("─" * 50 + "\n", style="dim")
        header_text.append("\n")
        header_text.append("WORKFLOW STEPS\n", style="bold #D7AF5F underline")
        header_text.append("\n")

        # Load and format workflow steps from workflow_state.json
        steps_content = self._load_workflow_steps(agent)
        if steps_content:
            # Render as YAML with syntax highlighting
            steps_syntax = Syntax(
                steps_content,
                "yaml",
                theme="monokai",
                word_wrap=True,
            )
            self.update(Group(header_text, steps_syntax))  # type: ignore[attr-defined]
        else:
            header_text.append("No workflow state found.\n", style="dim italic")
            self.update(header_text)  # type: ignore[attr-defined]

    def _load_workflow_inputs(self, agent: Agent) -> dict[str, Any] | None:
        """Load workflow inputs from workflow_state.json.

        Args:
            agent: The workflow agent.

        Returns:
            Dict of workflow inputs, or None if not found.
        """
        artifacts_dir = agent.get_artifacts_dir()
        if artifacts_dir is None:
            return None

        state_file = Path(artifacts_dir) / "workflow_state.json"
        if not state_file.exists():
            return None

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        return data.get("inputs")

    def _load_workflow_meta_raw(self, agent: Agent) -> dict[str, str] | None:
        """Load raw meta_* fields from workflow step outputs as a dict.

        Args:
            agent: The workflow agent.

        Returns:
            Dict of meta_* key to value, or None if not found.
        """
        artifacts_dir = agent.get_artifacts_dir()
        if artifacts_dir is None:
            return None

        state_file = Path(artifacts_dir) / "workflow_state.json"
        if not state_file.exists():
            return None

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        meta: dict[str, str] = {}
        for step in data.get("steps", []):
            output = step.get("output")
            if isinstance(output, dict):
                for k, v in output.items():
                    if k.startswith("meta_") and v:
                        meta[k] = str(v)
        return meta if meta else None

    def _load_workflow_meta_fields(self, agent: Agent) -> list[tuple[str, str]]:
        """Load aggregated meta_* fields from workflow step outputs.

        Args:
            agent: The workflow agent.

        Returns:
            List of (display_name, value) tuples.
        """
        artifacts_dir = agent.get_artifacts_dir()
        if artifacts_dir is None:
            return []

        state_file = Path(artifacts_dir) / "workflow_state.json"
        if not state_file.exists():
            return []

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return []

        steps = data.get("steps", [])
        return aggregate_meta_fields(steps)

    def _load_workflow_steps(self, agent: Agent) -> str | None:
        """Load and format workflow steps from workflow_state.json.

        Args:
            agent: The workflow agent.

        Returns:
            Formatted string of step details, or None if not found.
        """
        artifacts_dir = agent.get_artifacts_dir()
        if artifacts_dir is None:
            return None

        state_file = Path(artifacts_dir) / "workflow_state.json"
        if not state_file.exists():
            return None

        try:
            with open(state_file, encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return None

        steps = data.get("steps", [])
        if not steps:
            # Check for workflow-level error (e.g., validation failure)
            error = data.get("error")
            if error:
                tb = data.get("traceback")
                if tb:
                    return f"Error: {error}\n\nTraceback:\n{tb}"
                return f"Error: {error}"
            return None

        return self._format_workflow_steps(steps, data.get("context", {}))

    def _format_workflow_steps(
        self, steps: list[dict[str, Any]], _context: dict[str, Any]
    ) -> str:
        """Format workflow steps for display.

        Args:
            steps: List of step state dictionaries from workflow_state.json.
            _context: The workflow context with variables (unused, for future use).

        Returns:
            Formatted string for display.
        """
        lines: list[str] = []
        total_steps = len(steps)

        for i, step in enumerate(steps):
            step_name = step.get("name", "unknown")
            status = step.get("status", "pending")
            output = step.get("output")
            error = step.get("error")
            tb = step.get("traceback")

            # Step header
            status_indicator = get_status_indicator(status)
            lines.append(f"Step {i + 1}/{total_steps}: {step_name} {status_indicator}")
            lines.append("-" * 40)

            # Status
            lines.append(f"  Status: {status}")

            # Error (if any)
            if error:
                lines.append(f"  Error: {error}")

            # Traceback (if any)
            if tb:
                lines.append("  Traceback:")
                for line in tb.splitlines():
                    lines.append(f"    {line}")

            # Output (if any)
            if output:
                output_str = format_output(output)
                lines.append("  Output:")
                for line in output_str.splitlines():
                    lines.append(f"    {line}")

            lines.append("")

        return "\n".join(lines)
