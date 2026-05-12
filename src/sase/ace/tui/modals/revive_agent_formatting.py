"""Formatting and filtering helpers for the revive agent modal."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets.option_list import Option

from ..models.agent import Agent, AgentType
from .revive_agent_types import (
    STATUS_COLORS,
    STEP_TYPE_COLORS,
    TYPE_COLORS,
    DismissedEntry,
)


class ReviveAgentFormattingMixin:
    """List row formatting and in-memory filtering for revive entries."""

    def _compute_step_counts(self: Any) -> dict[str, int]:
        """Count child steps per parent (keyed by raw_suffix)."""
        counts: dict[str, int] = {}
        for agent in self._all_dismissed:
            if agent.is_workflow_child and agent.parent_timestamp:
                counts[agent.parent_timestamp] = (
                    counts.get(agent.parent_timestamp, 0) + 1
                )
        return counts

    def _get_child_steps(self: Any, agent: Agent) -> list[Agent]:
        """Get child steps for a parent workflow agent, sorted by step_index."""
        if not agent.raw_suffix:
            return []
        children = [
            a
            for a in self._all_dismissed
            if a.is_workflow_child and a.parent_timestamp == agent.raw_suffix
        ]
        children.sort(key=lambda a: a.step_index if a.step_index is not None else 0)
        return children

    def _get_type_color(self: Any, agent: Agent) -> str:
        """Get the color for an agent's type label."""
        if agent.appears_as_agent:
            return TYPE_COLORS[AgentType.RUNNING]
        if agent.is_workflow_child and agent.step_type in STEP_TYPE_COLORS:
            return STEP_TYPE_COLORS[agent.step_type]
        return TYPE_COLORS.get(agent.agent_type, "#FFFFFF")

    def _get_status_style(self: Any, status: str) -> str:
        """Get Rich style string for a status value."""
        color = STATUS_COLORS.get(status)
        if color:
            return f"bold {color}"
        return "dim"

    def _format_agent_label(self: Any, agent: Agent, orig_idx: int = -1) -> Text:
        """Create styled text for an agent option."""
        text = Text()

        if orig_idx in self._marked:
            text.append(" \u25cf ", style="bold #00D7D7")
        else:
            text.append("   ")

        if agent.status == "DONE":
            text.append("\u2714 ", style="bold #5FD75F")
        elif agent.status == "FAILED":
            text.append("\u2718 ", style="bold #FF5F5F")
        else:
            text.append("\u25cb ", style="dim")

        type_color = self._get_type_color(agent)
        text.append(f"[{agent.display_type}]", style=f"bold {type_color}")
        text.append(" ")

        text.append(agent.display_name, style="bold")

        if agent.agent_name:
            text.append("  ")
            text.append(f"@{agent.agent_name}", style="#87D7FF")

        text.append("  ")
        text.append(agent.start_time_compact, style="dim")

        if agent.model:
            text.append("  ")
            text.append(agent.model, style="dim italic")

        if agent.raw_suffix and agent.raw_suffix in self._step_counts:
            count = self._step_counts[agent.raw_suffix]
            text.append("  ")
            text.append(f"({count} steps)", style="dim #00D7D7")

        return text

    def _format_archive_label(self: Any, result: Any, orig_idx: int = -1) -> Text:
        """Create styled text for an archive summary row."""
        text = Text()
        text.append(
            " \u25cf " if orig_idx in self._marked else "   ", style="bold #00D7D7"
        )
        if result.status == "DONE":
            text.append("\u2714 ", style="bold #5FD75F")
        elif result.status == "FAILED":
            text.append("\u2718 ", style="bold #FF5F5F")
        else:
            text.append("\u25cb ", style="dim")
        display_type = "workflow" if result.step_type else "agent"
        text.append(f"[{display_type}]", style="bold #87AFFF")
        text.append(" ")
        text.append(result.cl_name, style="bold")
        if result.agent_name:
            text.append("  ")
            text.append(f"@{result.agent_name}", style="#87D7FF")
        if result.start_time:
            text.append("  ")
            text.append(result.start_time[:16].replace("T", " "), style="dim")
        if result.model:
            text.append("  ")
            text.append(result.model, style="dim italic")
        if result.project_name:
            text.append("  ")
            text.append(result.project_name, style="dim")
        return text

    def _format_entry_label(
        self: Any, entry: DismissedEntry, orig_idx: int = -1
    ) -> Text:
        """Create styled text for either a hydrated agent or summary row."""
        if entry.agent is not None:
            return self._format_agent_label(entry.agent, orig_idx)
        if entry.archive_result is not None:
            return self._format_archive_label(entry.archive_result, orig_idx)
        return Text("(invalid archive row)", style="dim")

    def _create_options(self: Any, entries: list[DismissedEntry]) -> list[Option]:
        """Create options from modal entries."""
        return [
            Option(self._format_entry_label(entry, i), id=str(i))
            for i, entry in enumerate(entries)
        ]

    def _create_options_or_placeholder(self: Any) -> list[Option]:
        """Create agent options or a disabled loading/empty placeholder."""
        if self._entries:
            return self._create_options(self._entries)
        if self._loading_archive:
            return [
                Option(Text("Loading dismissed archive...", style="dim"), disabled=True)
            ]
        return [
            Option(
                Text("No dismissed agents in this scope", style="dim"), disabled=True
            )
        ]

    def _get_filtered_entries(
        self: Any, filter_text: str
    ) -> list[tuple[int, DismissedEntry]]:
        """Get in-memory entries matching the legacy substring filter."""
        if not filter_text:
            return list(enumerate(self._entries))
        filter_lower = filter_text.lower()
        results: list[tuple[int, DismissedEntry]] = []
        for i, entry in enumerate(self._entries):
            agent = entry.agent
            if agent is None:
                continue
            label = f"[{agent.display_type}] {agent.display_name}"
            if agent.agent_name:
                label += f" @{agent.agent_name}"
            if filter_lower in label.lower():
                results.append((i, entry))
                continue
            if i in self._chat_contents and filter_lower in self._chat_contents[i]:
                results.append((i, entry))
        return results
