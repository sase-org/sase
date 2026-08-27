"""CLI human-in-the-loop handler for workflow execution."""

import os
import subprocess
import tempfile
from typing import Any

import yaml  # type: ignore[import-untyped]
from rich.console import Console
from rich.markup import escape as _esc
from rich.syntax import Syntax
from sase.content import dump_yaml

from sase.xprompt.workflow_executor_types import HITLResult

_EXTENSION_TO_LEXER: dict[str, str] = {
    ".diff": "diff",
    ".patch": "diff",
    ".py": "python",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".sh": "bash",
    ".bash": "bash",
    ".js": "javascript",
    ".ts": "typescript",
    ".md": "markdown",
    ".toml": "toml",
    ".xml": "xml",
    ".html": "html",
    ".css": "css",
}

# Timeout for TUI HITL handler (seconds) - 1 hour
_TUI_HITL_TIMEOUT = 3600


class TUIHITLHandler:
    """HITL handler for TUI contexts that uses file-based communication.

    This handler writes a request file and blocks waiting for a response file,
    allowing the TUI to present the HITL options to the user asynchronously.
    """

    def __init__(self, artifacts_dir: str, workflow_name: str = "") -> None:
        """Initialize the TUI HITL handler.

        Args:
            artifacts_dir: Directory for workflow artifacts where HITL files are written.
            workflow_name: Name of the workflow for notification context.
        """
        self.artifacts_dir = artifacts_dir
        self.workflow_name = workflow_name

    def prompt(
        self,
        step_name: str,
        step_type: str,
        output: Any,
        *,
        has_output: bool = False,
        output_types: dict[str, str] | None = None,
    ) -> HITLResult:
        """Create a HITL gate and block mechanically for its response.

        Args:
            step_name: Name of the step being reviewed.
            step_type: Either "agent" or "bash".
            output: The step's output data.
            has_output: Whether the step has an output field defined.
            output_types: Mapping of field names to their types (e.g. "path").

        Returns:
            HITLResult based on the user's response from the TUI.
        """
        from sase.xprompt.workflow_hitl_gate import (
            create_workflow_hitl_gate,
            create_workflow_hitl_shell_gate,
            maybe_handoff_workflow_hitl_from_agent,
            wait_for_workflow_hitl_gate,
            workflow_hitl_should_handoff_from_agent,
        )

        create = (
            create_workflow_hitl_shell_gate
            if workflow_hitl_should_handoff_from_agent()
            else create_workflow_hitl_gate
        )
        gate = create(
            step_name=step_name,
            step_type=step_type,
            output=output,
            workflow_name=self.workflow_name,
            artifacts_dir=self.artifacts_dir,
            has_output=has_output,
            output_types=output_types,
            timeout_seconds=_TUI_HITL_TIMEOUT,
        )
        if workflow_hitl_should_handoff_from_agent():
            maybe_handoff_workflow_hitl_from_agent(gate)
            return HITLResult(action="reject", approved=False)
        return wait_for_workflow_hitl_gate(gate.bundle_path)


class CLIHITLHandler:
    """CLI handler for human-in-the-loop prompts during workflow execution."""

    def __init__(self, console: Console | None = None) -> None:
        """Initialize the CLI HITL handler.

        Args:
            console: Optional Rich console for output. Creates one if not provided.
        """
        self.console = console or Console()

    def prompt(
        self,
        step_name: str,
        step_type: str,
        output: Any,
        *,
        has_output: bool = False,
        output_types: dict[str, str] | None = None,
    ) -> HITLResult:
        """Prompt the user for action on step output.

        Args:
            step_name: Name of the step being reviewed.
            step_type: Either "agent" or "bash".
            output: The step's output data.
            has_output: Whether the step has an output field defined.
            output_types: Mapping of field names to their types (e.g. "path").

        Returns:
            HITLResult indicating the user's decision.
        """
        # Display step info and output
        self.console.print()
        self.console.print(
            f"[bold cyan]Step '{_esc(step_name)}' ({_esc(step_type)}) completed.[/bold cyan]"
        )
        self.console.print("[dim]" + "─" * 60 + "[/dim]")

        # Format and display output
        if isinstance(output, dict):
            # Unwrap _data if present for cleaner display
            display_data = output.get("_data", output)
            output_str = dump_yaml(display_data, sort_keys=False)
            syntax = Syntax(output_str, "yaml", theme="monokai", line_numbers=True)
            self.console.print(syntax)
        else:
            self.console.print(str(output))

        # Display file contents for path-typed output fields
        if output_types and isinstance(output, dict):
            for field_name, field_type in output_types.items():
                if field_type == "path":
                    path_value = output.get(field_name)
                    if path_value and os.path.isfile(str(path_value)):
                        self._display_path_file(str(path_value), field_name)

        self.console.print("[dim]" + "─" * 60 + "[/dim]")

        # Show available actions based on step type
        self.console.print()
        self.console.print("[bold cyan]What would you like to do?[/bold cyan]")
        self.console.print("  [green]a[/green] - Accept and continue")

        # Edit option available for agent steps, or bash/python with output field
        can_edit = step_type == "agent" or (
            step_type in ("bash", "python") and has_output
        )
        if can_edit:
            self.console.print("  [yellow]e[/yellow] - Edit the output")

        if step_type == "agent":
            self.console.print("  [blue]<text>[/blue] - Provide feedback to regenerate")
        elif step_type in ("bash", "python"):
            self.console.print("  [yellow]r[/yellow] - Re-run the command")

        self.console.print("  [red]x[/red] - Reject and abort workflow")
        self.console.print()

        # Get user input
        response = input("Choice: ").strip()

        if response.lower() == "a":
            return HITLResult(action="accept", approved=True)
        elif response.lower() == "x":
            return HITLResult(action="reject", approved=False)
        elif response.lower() == "e" and can_edit:
            edited_output = self._edit_output(output)
            if edited_output is not None:
                return HITLResult(action="edit", edited_output=edited_output)
            else:
                # User cancelled edit, treat as reject
                return HITLResult(action="reject")
        elif response.lower() == "r" and step_type in ("bash", "python"):
            return HITLResult(action="rerun")
        elif response and step_type == "agent":
            # Treat any other input as feedback for regeneration
            return HITLResult(action="feedback", feedback=response)
        else:
            # Default to accept for empty input
            return HITLResult(action="accept", approved=True)

    def _display_path_file(self, file_path: str, field_name: str) -> None:
        """Display the contents of a path-typed output file with syntax highlighting.

        Args:
            file_path: Path to the file to display.
            field_name: Name of the output field (for the header).
        """
        self.console.print()
        self.console.print(
            f"[bold green]File contents ({_esc(field_name)}):[/bold green] {_esc(file_path)}"
        )
        self.console.print("[dim]" + "─" * 60 + "[/dim]")
        try:
            with open(file_path, encoding="utf-8") as f:
                content = f.read()
            ext = os.path.splitext(file_path)[1].lower()
            lexer = _EXTENSION_TO_LEXER.get(ext, "text")
            syntax = Syntax(
                content, lexer, theme="monokai", line_numbers=True, word_wrap=True
            )
            self.console.print(syntax)
        except Exception as e:
            self.console.print(f"[red]Error reading file: {_esc(str(e))}[/red]")

    def _edit_output(self, output: Any) -> Any | None:
        """Open output in editor for user modification.

        Args:
            output: The output dict to edit.

        Returns:
            Edited output as dict, or None if cancelled.
        """
        # Unwrap _data if present
        data = output.get("_data", output) if isinstance(output, dict) else output

        # Convert to YAML
        yaml_content = dump_yaml(data, sort_keys=False)

        # Create temp file
        from sase.core.paths import get_sase_managed_tmpdir

        fd, temp_path = tempfile.mkstemp(
            suffix=".yml",
            prefix="workflow_edit_",
            dir=get_sase_managed_tmpdir("editors"),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(yaml_content)

            # Open in editor
            editor = os.environ.get("EDITOR", "nvim")
            subprocess.run([editor, temp_path], check=False)

            # Read edited content
            with open(temp_path, encoding="utf-8") as f:
                edited_content = f.read()
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        if not edited_content.strip():
            return None

        # Parse YAML back to dict/list
        try:
            edited_data = yaml.safe_load(edited_content)
            # Re-wrap in _data if original was wrapped
            if isinstance(output, dict) and "_data" in output:
                return {"_data": edited_data}
            return edited_data
        except yaml.YAMLError as e:
            self.console.print(f"[red]Invalid YAML: {_esc(str(e))}[/red]")
            return None
