"""Jump-panel wiring for AgentDetail (sase's TUI)."""

from __future__ import annotations

from typing import Any

from textual.widgets import Static


class AgentDetailJumpMixin(Static):
    """Mixin attaching the sticky jump panel to the prompt panel's jump sink.

    Mixed into ``AgentDetail`` — ``query_one`` / ``post_message`` come from
    that class through ``Static`` for the type checker.
    """

    def _jump_panel_or_none(self) -> Any | None:
        """Return the jump panel when mounted, else None."""
        try:
            from .agent_jump_panel import AgentJumpPanel

            return self.query_one("#agent-jump-panel", AgentJumpPanel)
        except Exception:
            return None

    def _attach_jump_panel_sink(self) -> None:
        """Attach the prompt panel's jump sink to the jump panel."""
        from ._agent_detail_helpers import agent_prompt_panel_type

        try:
            prompt_panel = self.query_one(
                "#agent-prompt-panel", agent_prompt_panel_type()
            )
        except Exception:
            return
        try:
            prompt_panel.attach_member_jump_map_sink(self._on_member_jump_map)
        except Exception:
            pass
        self._sync_jump_panel_visibility()

    def _on_member_jump_map(
        self, jump_map: Any | None, roster: Any | None = None
    ) -> None:
        """Show the published jump map, then sync jump-panel visibility."""
        panel = self._jump_panel_or_none()
        if panel is None:
            return
        try:
            panel.show_jump_map(jump_map, roster=roster)
        except Exception:
            pass
        self._sync_jump_panel_visibility()

    def _sync_jump_panel_visibility(self) -> None:
        """Hide the jump panel unless the document has numbered targets."""
        panel = self._jump_panel_or_none()
        if panel is None:
            return
        try:
            visible = bool(panel.has_targets)
        except Exception:
            visible = False
        try:
            if visible:
                panel.remove_class("hidden")
            else:
                panel.add_class("hidden")
        except Exception:
            pass

    def _reset_jump_panel_scroll(self) -> None:
        """Scroll the jump panel back to the top on document identity change."""
        panel = self._jump_panel_or_none()
        if panel is None:
            return
        try:
            # Assign directly: the jump sink hides the panel before publish
            # runs, and scroll_to() is a no-op on hidden widgets.
            panel.scroll_y = 0
        except Exception:
            pass

    def jump_panel_toggle_available(self) -> bool:
        """Return whether the jump panel can be toggled."""
        panel = self._jump_panel_or_none()
        if panel is None:
            return False
        try:
            return bool(panel.has_targets) and not panel.has_class("hidden")
        except Exception:
            return False

    def toggle_jump_panel_expanded(self) -> bool:
        """Flip the jump panel state and keep a bottom pin in place."""
        panel = self._jump_panel_or_none()
        if panel is None:
            return False
        try:
            expanded = bool(panel.toggle_expanded())
        except Exception:
            return False
        try:
            reapply = getattr(self, "reapply_main_view_pins", None)
            if callable(reapply):
                reapply()
        except Exception:
            pass
        return expanded

    def set_jump_panel_prefix(self, prefix: str | None) -> None:
        """Narrow the jump panel to ``prefix`` candidates, or restore it."""
        panel = self._jump_panel_or_none()
        if panel is None:
            return
        try:
            panel.set_pending_prefix(prefix)
        except Exception:
            pass


__all__ = ["AgentDetailJumpMixin"]
