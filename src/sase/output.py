"""
Rich formatting utilities for SASE workflow system.

This module provides utilities for creating visually appealing command-line output
using the Rich library for status messages, progress indicators, and structured data display.
"""

import threading
import time
from collections.abc import Generator
from contextlib import contextmanager

from rich.console import Console
from rich.live import Live
from rich.markup import escape as escape_markup
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

# Re-export shared consoles and escaping for convenient, consistent CLI output.
__all__ = ["console", "error_console", "escape_markup"]

# Global console instance for consistent styling
console = Console()
error_console = Console(stderr=True)

_PROVIDER_TIMER_INTERVAL_SECONDS = 0.5
_PROVIDER_TIMER_JOIN_TIMEOUT_SECONDS = 1.0
_PROVIDER_TIMER_COMPLETION_DISPLAY_SECONDS = 0.3


def print_workflow_header(workflow_name: str, tag: str = "") -> None:
    """Print a formatted workflow header."""
    header_text = f"🚀 SASE {escape_markup(workflow_name.upper())} Workflow"
    if tag:
        header_text += f" ({escape_markup(tag)})"

    console.print(
        Panel(
            f"[bold blue]{header_text}[/bold blue]",
            title="System",
            border_style="blue",
            padding=(1, 2),
        )
    )


def print_status(message: str, status_type: str = "info") -> None:
    """Print a status message with appropriate styling."""
    icons = {
        "info": "ℹ️",
        "success": "✅",
        "warning": "⚠️",
        "error": "❌",
        "progress": "🔄",
    }

    styles = {
        "info": "blue",
        "success": "green",
        "warning": "yellow",
        "error": "red",
        "progress": "cyan",
    }

    icon = icons.get(status_type, "ℹ️")
    style = styles.get(status_type, "white")

    console.print(f"[{style}]{icon} {escape_markup(message)}[/{style}]")


def print_artifact_created(artifact_path: str) -> None:
    """Print notification about artifact creation."""
    console.print(f"[dim]📄 Created artifact: {escape_markup(artifact_path)}[/dim]")


def print_file_operation(operation: str, file_path: str, success: bool = True) -> None:
    """Print formatted file operation message."""
    icon = "✅" if success else "❌"
    color = "green" if success else "red"
    console.print(
        f"[{color}]{icon} {escape_markup(operation)}: "
        f"{escape_markup(file_path)}[/{color}]"
    )


def print_prompt_and_response(
    prompt: str,
    response: str,
    agent_type: str = "agent",
    iteration: int | None = None,
    show_prompt: bool = True,
    show_response: bool = True,
) -> None:
    """Print formatted prompt and response using Rich."""
    # Configure agent display based on type
    agent_configs = {
        "editor": ("🛠️ Editor Agent", "cyan"),
        "planner": ("📋 Planner Agent", "magenta"),
        "research_cl_scope": ("🔍 PR Scope Research", "yellow"),
        "research_similar_tests": ("🔍 Similar Tests Research", "yellow"),
        "research_test_failure": ("🔍 Test Failure Research", "yellow"),
        "research_prior_work_analysis": ("🔍 Prior Work Research", "yellow"),
        "research_cl_analysis": ("🔍 PR Analysis Research", "yellow"),
        "research_synthesis": ("🔬 Research Synthesis", "bright_magenta"),
        "verification": ("✅ Verification Agent", "green"),
        "add_tests": ("🧪 Add Tests Agent", "blue"),
        "test_failure_comparison": ("📊 Test Comparison Agent", "bright_yellow"),
        "postmortem": ("🔍 Postmortem Agent", "red"),
    }

    title, border_color = agent_configs.get(
        agent_type, (f"🤖 {agent_type.title()} Agent", "white")
    )

    if iteration is not None:
        title += f" (Iteration {iteration})"

    # Print prompt if requested
    if show_prompt and prompt:
        console.print(
            Panel(
                Syntax(prompt, "markdown", theme="monokai", word_wrap=True),
                title=f"{title} - Prompt",
                border_style=border_color,
                padding=(1, 2),
            )
        )

    # Print response if requested
    if show_response and response:
        console.print(
            Panel(
                Syntax(response, "markdown", theme="monokai", word_wrap=True),
                title=f"{title} - Response",
                border_style=border_color,
                padding=(1, 2),
            )
        )


def print_decision_counts(decision_counts: dict) -> None:
    """Print planning agent decision counts using Rich formatting."""
    if not decision_counts:
        return

    table = Table(
        title="🎯 Planning Agent Decision Counts",
        show_header=True,
        header_style="bold cyan",
    )
    table.add_column("Decision Type", style="cyan")
    table.add_column("Count", style="yellow", justify="right")

    table.add_row("New Editor", str(decision_counts.get("new_editor", 0)))
    table.add_row("Existing Editor", str(decision_counts.get("next_editor", 0)))
    table.add_row("Researcher", str(decision_counts.get("research", 0)))

    console.print(table)


@contextmanager
def provider_timer(
    message: str = "Waiting for provider",
) -> Generator[None, None, None]:
    """
    Display a live updating timer showing elapsed time while waiting on an agent.

    This context manager displays a timer that updates every second, showing
    how long the provider invocation has been running. The timer appears
    directly below the pretty-printed prompt.

    Args:
        message: The message to display alongside the timer

    Yields:
        None

    Example:
        >>> with provider_timer("Waiting for Antigravity"):
        ...     result = subprocess.run(["agy", "--print", prompt], ...)
    """
    start_time = time.time()

    def _format_elapsed(elapsed_seconds: float) -> str:
        """Format elapsed time as MM:SS or HH:MM:SS."""
        total_seconds = int(elapsed_seconds)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        else:
            return f"{minutes:02d}:{seconds:02d}"

    # Create a Text object for the timer display
    def _get_timer_text() -> Text:
        elapsed = time.time() - start_time
        elapsed_str = _format_elapsed(elapsed)
        # Use a spinner and elapsed time format similar to TimeElapsedColumn
        text = Text()
        text.append("⏱️  ", style="bold cyan")
        text.append(message, style="bold")
        text.append(f" [{elapsed_str}]", style="cyan")
        return text

    # Use Rich Live to update the timer in place
    with Live(_get_timer_text(), refresh_per_second=2, console=console) as live:
        stop_event = threading.Event()

        def _update_timer() -> None:
            while not stop_event.wait(_PROVIDER_TIMER_INTERVAL_SECONDS):
                live.update(_get_timer_text())

        timer_thread = threading.Thread(
            target=_update_timer,
            name="sase-provider-timer",
            daemon=True,
        )
        timer_thread.start()

        try:
            # Yield control back to the caller
            yield

        finally:
            stop_event.set()
            timer_thread.join(timeout=_PROVIDER_TIMER_JOIN_TIMEOUT_SECONDS)
            # Final update with the total elapsed time
            elapsed = time.time() - start_time
            elapsed_str = _format_elapsed(elapsed)
            final_text = Text()
            final_text.append("✅ ", style="bold green")
            final_text.append(message, style="bold")
            final_text.append(f" completed in {elapsed_str}", style="green")
            live.update(final_text)
            # Give a moment to show the final message
            time.sleep(_PROVIDER_TIMER_COMPLETION_DISPLAY_SECONDS)
