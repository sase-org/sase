"""Empty-state rendering for the agent prompt panel."""

from __future__ import annotations

from rich.text import Text

from ._agent_display_header_summary import clear_detail_header_summary_cache
from ._agent_display_hints import clear_agent_hint_render_cache


class AgentDisplayEmptyMixin:
    """Clear per-agent display state and show the empty panel."""

    def show_empty(self) -> None:
        """Show empty state."""
        clearer = getattr(self, "_clear_tribe_complete_memo", None)
        if callable(clearer):
            clearer()
        reset_sections = getattr(self, "reset_section_document", None)
        if callable(reset_sections):
            reset_sections()
        cancel_slow_tick = getattr(self, "_cancel_slow_tool_render_tick", None)
        if callable(cancel_slow_tick):
            cancel_slow_tick()
        current_worker = getattr(self, "_agent_bead_display_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_worker.cancel()
        current_worker = getattr(self, "_agent_detail_header_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_worker.cancel()
        current_worker = getattr(self, "_clan_section_worker", None)
        if current_worker is not None and getattr(current_worker, "is_running", False):
            current_worker.cancel()
        cancel_tribe_worker = getattr(
            self, "_cancel_tribe_section_worker_for_agent_selection", None
        )
        if callable(cancel_tribe_worker):
            cancel_tribe_worker()
        clear_detail_header_summary_cache(self)
        clear_agent_hint_render_cache(self)
        # Cardless on purpose: deck-panel-core delegates show_empty in deck mode.
        text = Text("No agent selected", style="dim italic")
        self.update(text)  # type: ignore[attr-defined]
