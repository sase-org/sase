"""Modal showing all currently running processes and agents."""

from datetime import datetime

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from ._runners_data import RunnerInfo, collect_runners, get_runner_count
from .base import CopyModeForwardingMixin

# Re-export for public API
__all__ = ["RunnersModal", "get_runner_count"]

# Dynamic box sizing constants
_CSS_MAX_WIDTH = 200  # Must match max-width in styles.tcss for RunnersModal
_CSS_CHROME = 8  # Border (2) + padding (2*2) + extra (2) from CSS container
_PREFIX_SUFFIX = 7  # "  │  " (5 chars) + " │" (2 chars)
_MIN_BOX_WIDTH = 60


def _abbreviate_agent_type(agent_type: str) -> str:
    """Abbreviate long agent type strings for display.

    Args:
        agent_type: Full agent type string (e.g., "mentor:code:comments").

    Returns:
        Abbreviated string (e.g., "m:code:comm").
    """
    # Common abbreviations
    abbrevs = {
        "mentor": "m",
        "summarize-hook": "sum",
        "fix-hook": "fix",
        "comments": "comm",
    }

    parts = agent_type.split(":")
    abbreviated_parts = []
    for part in parts:
        if part in abbrevs:
            abbreviated_parts.append(abbrevs[part])
        elif len(part) > 6:
            abbreviated_parts.append(part[:4])
        else:
            abbreviated_parts.append(part)

    result = ":".join(abbreviated_parts)
    return result


def _format_duration(start_time: datetime | None) -> str:
    """Format duration from start time to now.

    Args:
        start_time: The start time, or None.

    Returns:
        Duration string like "5m23s" or "?" if unknown.
    """
    if start_time is None:
        return "?"
    delta = datetime.now() - start_time
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return f"{total_seconds}s"
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    if minutes < 60:
        return f"{minutes}m{seconds}s"
    hours = minutes // 60
    minutes = minutes % 60
    return f"{hours}h{minutes}m"


class RunnersModal(CopyModeForwardingMixin, ModalScreen[None]):
    """Modal showing all currently running processes and agents."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("q", "close", "Close"),
        ("r", "close", "Close"),  # Same key closes
        ("ctrl+d", "scroll_down", "Scroll down"),
        ("ctrl+u", "scroll_up", "Scroll up"),
    ]

    def _compute_box_width(self) -> int:
        """Compute box width dynamically based on terminal size.

        Returns:
            The box width in characters.
        """
        terminal_width = self.app.size.width
        box_width = min(int(terminal_width * 0.9), _CSS_MAX_WIDTH) - _CSS_CHROME
        return max(box_width, _MIN_BOX_WIDTH)

    def compose(self) -> ComposeResult:
        """Compose the modal layout."""
        self._box_width = self._compute_box_width()
        self._content_width = self._box_width - _PREFIX_SUFFIX
        with Container(id="runners-modal-container"):
            yield Static(self._build_title(), id="runners-title")
            with VerticalScroll(id="runners-content-scroll"):
                yield Static(self._build_content(), id="runners-content")
            yield Static(
                "Press r / q / Esc to close  |  Ctrl+D/U to scroll",
                id="runners-footer",
            )

    def _build_title(self) -> Text:
        """Build the styled title."""
        text = Text()
        text.append("\n")
        text.append("  ", style="")
        text.append("\u2726 ", style="bold #FFD700")  # Star
        text.append("Running Processes & Agents", style="bold white")
        text.append(" \u2726", style="bold #FFD700")  # Star
        text.append("\n")
        return text

    def _build_content(self) -> Text:
        """Build the main content showing processes and agents."""
        processes, axe_agents, manual_agents = collect_runners()
        text = Text()

        # Manual Agents section (cyan) - user-started agents
        self._add_section_header(text, "Manual Agents", "#00CED1")
        if manual_agents:
            for runner in manual_agents:
                self._add_runner_entry(text, runner, "#00CED1")
        else:
            self._add_empty_row(text, "No manual agents", "#00CED1")
        self._add_section_footer(text, "#00CED1")

        text.append("\n")

        # Running Agents section (orange) - axe-spawned agents
        self._add_section_header(text, "Axe Agents", "#FF8C00")
        if axe_agents:
            for runner in axe_agents:
                self._add_runner_entry(text, runner, "#FF8C00")
        else:
            self._add_empty_row(text, "No axe agents", "#FF8C00")
        self._add_section_footer(text, "#FF8C00")

        text.append("\n")

        # Running Processes section (yellow) - axe hook processes
        self._add_section_header(text, "Running Processes", "#FFD700")
        if processes:
            for runner in processes:
                self._add_runner_entry(text, runner, "#FFD700")
        else:
            self._add_empty_row(text, "No running processes", "#FFD700")
        self._add_section_footer(text, "#FFD700")

        return text

    def _add_section_header(self, text: Text, title: str, color: str) -> None:
        """Add a section header with box drawing.

        Args:
            text: The Text object to append to.
            title: The section title.
            color: The color for the box drawing.
        """
        # Header: "  ┌─ TITLE ──────────────────────────────────────────┐"
        # "  ┌─ " = 5 chars, " " after title + dashes + "┐" fills to _BOX_WIDTH
        text.append("  \u250c\u2500 ", style=f"dim {color}")
        text.append(title, style=f"bold {color}")
        text.append(" ", style="")
        # 5 (prefix) + len(title) + 1 (space) + remaining + 1 (corner) = box_width
        remaining = self._box_width - 5 - len(title) - 1 - 1
        text.append("\u2500" * remaining + "\u2510", style=f"dim {color}")
        text.append("\n")

    def _add_section_footer(self, text: Text, color: str) -> None:
        """Add a section footer with box drawing.

        Args:
            text: The Text object to append to.
            color: The color for the box drawing.
        """
        # Footer: "  └─────────────────────────────────────────────────────┘"
        # "  └" = 3 chars, dashes + "┘" fills to box_width
        text.append("  \u2514", style=f"dim {color}")
        text.append("\u2500" * (self._box_width - 4), style=f"dim {color}")
        text.append("\u2518", style=f"dim {color}")
        text.append("\n")

    def _add_empty_row(self, text: Text, message: str, color: str) -> None:
        """Add an empty state row with right border.

        Args:
            text: The Text object to append to.
            message: The empty state message.
            color: The color for the box drawing border.
        """
        # "  │  " = 5 chars prefix, message, padding, " │" = 2 chars suffix
        text.append("  \u2502  ", style=f"dim {color}")
        padding = self._content_width - len(message)
        text.append(message, style="dim")
        text.append(" " * padding, style="")
        text.append(" \u2502", style=f"dim {color}")
        text.append("\n")

    def _add_runner_entry(self, text: Text, runner: RunnerInfo, color: str) -> None:
        """Add a single runner entry.

        Args:
            text: The Text object to append to.
            runner: The runner info to display.
            color: The color for the box drawing border.
        """
        # Build content parts and track length
        parts: list[tuple[str, str]] = []  # (text, style) tuples
        content_len = 0

        # Workspace number
        ws_str = (
            f"#{runner.workspace_num}" if runner.workspace_num is not None else "#?"
        )
        parts.append((ws_str, "bold #AF87FF"))
        parts.append((" ", ""))
        content_len += len(ws_str) + 1

        # CL name (no truncation)
        cl_name = runner.cl_name
        parts.append((cl_name, "bold #87D7FF"))
        parts.append((" ", ""))
        content_len += len(cl_name) + 1

        # Type indicator
        if runner.runner_type == "process":
            type_str = "($)"
            type_style = "bold #3D2B1F on #FFD700"
        else:
            agent_type = runner.agent_type or "agent"
            # Abbreviate long agent types (e.g., mentor:code:comments -> m:code:comm)
            agent_type = _abbreviate_agent_type(agent_type)
            type_str = f"(@:{agent_type})"
            type_style = "bold #FFFFFF on #FF8C00"
        parts.append((type_str, type_style))
        content_len += len(type_str)

        # Hook command if present (no truncation)
        if runner.hook_command:
            cmd = runner.hook_command
            parts.append((f" {cmd}", "#87AFAF"))
            content_len += len(cmd) + 1

        # Reviewer for CRS
        if runner.reviewer:
            reviewer_str = f" [{runner.reviewer}]"
            parts.append((reviewer_str, "#D7AF87"))
            content_len += len(reviewer_str)

        # PID and duration
        pid_str = str(runner.pid) if runner.pid else "?"
        duration = _format_duration(runner.start_time)
        pid_duration = f" (PID:{pid_str}, {duration})"
        parts.append((pid_duration, "dim"))
        content_len += len(pid_duration)

        # Truncate content if it exceeds the available width
        if content_len > self._content_width:
            max_len = self._content_width - 3  # reserve for "..."
            truncated_parts: list[tuple[str, str]] = []
            running_len = 0
            for part_text, part_style in parts:
                if running_len >= max_len:
                    break
                remaining = max_len - running_len
                if len(part_text) <= remaining:
                    truncated_parts.append((part_text, part_style))
                    running_len += len(part_text)
                else:
                    truncated_parts.append((part_text[:remaining], part_style))
                    running_len += remaining
            truncated_parts.append(("...", "dim"))
            parts = truncated_parts
            content_len = self._content_width

        # Write row with proper borders
        text.append("  \u2502  ", style=f"dim {color}")
        for part_text, part_style in parts:
            text.append(part_text, style=part_style)

        # Pad to content_width and add right border
        if content_len < self._content_width:
            text.append(" " * (self._content_width - content_len), style="")
        text.append(" \u2502", style=f"dim {color}")
        text.append("\n")

        # Show prompt preview on a second line for manual agents
        if runner.prompt_preview:
            self._add_prompt_preview_row(text, runner.prompt_preview, color)

    def _add_prompt_preview_row(self, text: Text, preview: str, color: str) -> None:
        """Add a prompt preview row below a runner entry.

        Args:
            text: The Text object to append to.
            preview: The prompt preview string.
            color: The color for the box drawing border.
        """
        indent = "    "  # 4-space indent for visual nesting
        max_preview_len = self._content_width - len(indent)
        if len(preview) > max_preview_len:
            preview = preview[: max_preview_len - 3] + "..."

        text.append("  \u2502  ", style=f"dim {color}")
        text.append(indent, style="")
        text.append(preview, style="dim italic")
        padding = self._content_width - len(indent) - len(preview)
        if padding > 0:
            text.append(" " * padding, style="")
        text.append(" \u2502", style=f"dim {color}")
        text.append("\n")

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)

    def action_scroll_down(self) -> None:
        """Scroll the content down by half a page."""
        scroll = self.query_one("#runners-content-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def action_scroll_up(self) -> None:
        """Scroll the content up by half a page."""
        scroll = self.query_one("#runners-content-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)
