"""Archive hydration and preview rendering for the revive agent modal."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from rich.text import Text
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..models.agent import Agent
from .revive_agent_types import STEP_TYPE_COLORS, DismissedEntry

if TYPE_CHECKING:
    from ...agent_query.archive_planner import ArchiveQueryResult


class ReviveAgentPreviewMixin:
    """Archive hydration and right-pane preview behavior."""

    def _hydrate_entry(self: Any, entry: DismissedEntry) -> Agent | None:
        """Hydrate an archive-backed entry on demand."""
        if entry.agent is not None:
            return entry.agent
        if entry.archive_result is None or self._archive_query_provider is None:
            return None

        try:
            agents = self._archive_query_provider.hydrate(entry.archive_result)
        except Exception:
            return None
        if not agents:
            return None

        self._merge_hydrated_agents(agents)
        selected = self._select_agent_from_hydrated_group(agents, entry.archive_result)
        entry.agent = selected
        return selected

    def _merge_hydrated_agents(self: Any, agents: list[Agent]) -> None:
        """Add lazily hydrated archive rows to the modal's child lookup set."""
        seen = {agent.identity for agent in self._all_dismissed}
        for agent in agents:
            if agent.identity in seen:
                continue
            self._all_dismissed.append(agent)
            seen.add(agent.identity)
        self._step_counts = self._compute_step_counts()

    def _select_agent_from_hydrated_group(
        self: Any,
        agents: list[Agent],
        result: ArchiveQueryResult,
    ) -> Agent | None:
        """Pick the archive result's matching agent from a hydrated bundle."""
        for agent in agents:
            if (
                agent.raw_suffix == result.raw_suffix
                and agent.step_index == result.step_index
                and agent.is_workflow_child == result.is_workflow_child
            ):
                return agent
        for agent in agents:
            if agent.raw_suffix == result.raw_suffix and not agent.is_workflow_child:
                return agent
        return agents[0]

    def _update_preview_for_entry(self: Any, entry: DismissedEntry) -> None:
        """Update preview, hydrating archive rows only when highlighted."""
        agent = self._hydrate_entry(entry)
        if agent is None and entry.archive_result is not None:
            self._update_archive_summary_preview(entry.archive_result)
            return
        if agent is not None:
            self._update_preview(agent)
        else:
            self._clear_preview()

    def _update_archive_summary_preview(self: Any, result: ArchiveQueryResult) -> None:
        """Show compact metadata when a bundle cannot be hydrated."""
        try:
            metadata_widget = self.query_one("#dismissed-preview-metadata", Static)
            content_widget = self.query_one("#dismissed-preview-content", Static)
            meta = Text()
            meta.append("Archive result\n\n", style="bold")
            meta.append(f"  {'Status':<12}", style="bold")
            meta.append(
                f"{result.status}\n", style=self._get_status_style(result.status)
            )
            meta.append(f"  {'CL':<12}", style="bold")
            meta.append(f"{result.cl_name}\n", style="dim")
            if result.agent_name:
                meta.append(f"  {'Agent':<12}", style="bold")
                meta.append(f"@{result.agent_name}\n", style="#87D7FF")
            if result.project_name:
                meta.append(f"  {'Project':<12}", style="bold")
                meta.append(f"{result.project_name}\n", style="dim")
            if result.model:
                meta.append(f"  {'Model':<12}", style="bold")
                meta.append(f"{result.model}\n", style="dim italic")
            metadata_widget.update(meta)
            content_widget.update(
                Text("(bundle preview unavailable)", style="dim italic")
            )
        except Exception:
            pass

    def scroll_preview_down(self: Any) -> None:
        """Scroll preview panel down (half page)."""
        scroll = self.query_one("#dismissed-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=height // 2, animate=False)

    def scroll_preview_up(self: Any) -> None:
        """Scroll preview panel up (half page)."""
        scroll = self.query_one("#dismissed-preview-scroll", VerticalScroll)
        height = scroll.scrollable_content_region.height
        scroll.scroll_relative(y=-(height // 2), animate=False)

    def _update_preview(self: Any, agent: Agent) -> None:
        """Update preview panel with structured agent metadata and response."""
        try:
            metadata_widget = self.query_one("#dismissed-preview-metadata", Static)
            content_widget = self.query_one("#dismissed-preview-content", Static)

            meta = Text()

            type_color = self._get_type_color(agent)
            header = f"[{agent.display_type}] {agent.display_name}"
            meta.append("\u2501\u2501\u2501 ", style="dim")
            meta.append(header, style=f"bold {type_color}")
            meta.append(
                " " + "\u2501" * max(1, 36 - len(header)),
                style="dim",
            )
            meta.append("\n\n")

            label_width = 12

            meta.append(f"  {'Status':<{label_width}}", style="bold")
            meta.append(agent.status, style=self._get_status_style(agent.status))
            meta.append("\n")

            meta.append(f"  {'Started':<{label_width}}", style="bold")
            meta.append(f"{agent.start_time_display}\n", style="dim")

            meta.append(f"  {'Duration':<{label_width}}", style="bold")
            meta.append(f"{agent.duration_display}\n", style="dim")

            if agent.model:
                meta.append(f"  {'Model':<{label_width}}", style="bold")
                meta.append(f"{agent.model}\n", style="dim italic")

            if agent.llm_provider:
                meta.append(f"  {'Provider':<{label_width}}", style="bold")
                meta.append(f"{agent.llm_provider}\n", style="dim")

            if agent.agent_name:
                meta.append(f"  {'Agent':<{label_width}}", style="bold")
                meta.append(f"@{agent.agent_name}\n", style="#87D7FF")

            if agent.workflow and not agent.appears_as_agent:
                meta.append(f"  {'Workflow':<{label_width}}", style="bold")
                meta.append(f"{agent.workflow}\n", style="dim")

            children = self._get_child_steps(agent)
            if children:
                meta.append(f"\n  \u2500\u2500 Steps ({len(children)}) ")
                meta.append(
                    "\u2500" * 24 + "\n",
                    style="dim",
                )
                for i, child in enumerate(children, 1):
                    step_type = child.step_type or "step"
                    step_name = child.step_name or child.cl_name
                    status_style = self._get_status_style(child.status)
                    meta.append(f"  {i}. ", style="dim #AAAAAA")
                    step_color = STEP_TYPE_COLORS.get(step_type, type_color)
                    meta.append(f"[{step_type}] ", style=f"dim {step_color}")
                    meta.append(f"{step_name:<20}", style="dim")
                    meta.append(f"{child.status}\n", style=status_style)

            if agent.error_message:
                meta.append("\n  \u2500\u2500 Error ")
                meta.append("\u2500" * 28 + "\n", style="dim")
                meta.append(f"  {agent.error_message}\n", style="bold #FF5F5F")
                if agent.error_traceback:
                    meta.append(f"  {agent.error_traceback}\n", style="dim #FF5F5F")

            metadata_widget.update(meta)

            raw = agent.get_response_content()
            content = raw.strip() if raw else None

            if content:
                preview = Text()
                preview.append(
                    "\n  \u2500\u2500 Response " + "\u2500" * 26 + "\n",
                    style="dim",
                )
                preview.append(content[:5000])
                if len(content) > 5000:
                    preview.append("\n... (truncated)", style="dim")
                content_widget.update(preview)
            else:
                content_widget.update(Text("(no response content)", style="dim italic"))

        except Exception:
            pass

    def _clear_preview(self: Any) -> None:
        """Clear the preview panel."""
        try:
            self.query_one("#dismissed-preview-metadata", Static).update("")
            self.query_one("#dismissed-preview-content", Static).update("")
        except Exception:
            pass
