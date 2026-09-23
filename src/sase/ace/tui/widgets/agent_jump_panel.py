"""Sticky jump-target legend panel for the Agents tab."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.color import Color
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..keymaps import key_display_name
from rich.text import Text

from ._agent_jump_legend import (
    JumpLegendRenderable,
    jump_legend_border_accent,
    jump_legend_title,
)
from .prompt_panel._member_roster import MemberJumpMap


class AgentJumpPanel(VerticalScroll):
    """Bordered sticky panel showing rosters when expanded, legend collapsed."""

    can_focus = False

    _jump_map: MemberJumpMap | None = None
    _member_roster: Text | None = None
    _expanded: bool = False
    _pending_prefix: str | None = None
    _last_accent: str | None = None
    _last_digest: str | None = None

    def compose(self) -> ComposeResult:
        """Compose the inner content static."""
        yield Static(id="agent-jump-content")

    @property
    def has_targets(self) -> bool:
        """Return whether a map with numbered targets is currently stored."""
        jump_map = self._jump_map
        return jump_map is not None and len(jump_map.targets) > 0

    @property
    def is_expanded(self) -> bool:
        """Return whether the panel shows the full target list."""
        return self._expanded

    def _effective_mode(self) -> str:
        """Return the narrowing prefix, else expanded or collapsed."""
        prefix = self._pending_prefix
        if prefix is not None:
            return prefix
        return "expanded" if self._expanded else "collapsed"

    def _toggle_key(self) -> str:
        """Return the live display name for the jump-panel toggle key."""
        try:
            registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
            if registry is not None:
                raw = getattr(
                    getattr(registry, "app", None), "toggle_agent_jump_panel", ""
                )
                if raw:
                    return key_display_name(str(raw))
                return ""
        except Exception:
            pass
        return "."

    def _subtitle_for(self, *, narrowed: bool) -> str:
        """Return the border subtitle hint for the current mode."""
        if narrowed:
            return "esc cancel"
        key = self._toggle_key()
        if not key:
            return ""
        if self._expanded:
            return f"\u25be {key} less"
        return f"\u25b4 {key} more"

    def _apply_chrome(self, jump_map: MemberJumpMap, subtitle: str) -> None:
        """Update the border title, subtitle, and dimmed accent border."""
        self.border_title = jump_legend_title(jump_map, prefix=self._pending_prefix)
        self.border_subtitle = subtitle
        accent = jump_legend_border_accent(jump_map)
        if self._last_accent != accent:
            self._last_accent = accent
            try:
                dimmed = Color.parse(accent).with_alpha(0.5)
                self.styles.border = ("round", dimmed)
            except Exception:
                try:
                    self.styles.border = ("round", accent)
                except Exception:
                    pass

    def show_jump_map(
        self, jump_map: MemberJumpMap | None, roster: Text | None = None
    ) -> None:
        """Render ``jump_map`` with its detached roster (or clear)."""
        from ..util.renderable_digest import renderable_content_digest

        self._jump_map = jump_map
        self._member_roster = roster
        try:
            content = self.query_one("#agent-jump-content", Static)
        except Exception:
            return
        if jump_map is None:
            self._last_digest = None
            self._last_accent = None
            self._member_roster = None
            content.update("")
            self.border_title = ""
            self.border_subtitle = ""
            return
        mode = self._effective_mode()
        narrowed = self._pending_prefix is not None
        if narrowed:
            shown: JumpLegendRenderable | Text = JumpLegendRenderable(
                jump_map, mode=self._pending_prefix or "collapsed"
            )
        elif self._expanded and roster is not None:
            shown = roster
        else:
            shown = JumpLegendRenderable(jump_map, mode="collapsed")
        subtitle = self._subtitle_for(narrowed=narrowed)
        try:
            if narrowed:
                legend_digest = renderable_content_digest(shown)
            else:
                legend_digest = renderable_content_digest(
                    JumpLegendRenderable(jump_map, mode="collapsed")
                )
            digest: str | None = legend_digest
            if self._expanded and roster is not None:
                try:
                    roster_digest = renderable_content_digest(roster)
                except Exception:
                    roster_digest = None
                if roster_digest is not None:
                    digest = (
                        f"{digest}|{roster_digest}"
                        if digest is not None
                        else roster_digest
                    )
            if digest is not None:
                digest += f"|{mode}|{subtitle}|{self._pending_prefix}"
        except Exception:
            digest = None
        if digest is not None and digest == self._last_digest:
            return
        self._last_digest = digest
        self._apply_chrome(jump_map, subtitle)
        content.update(shown)

    def set_pending_prefix(self, prefix: str | None) -> None:
        """Narrow to ``prefix`` candidates, or restore the stored view."""
        if prefix == self._pending_prefix:
            return
        self._pending_prefix = prefix
        # Force repaint: the map object is unchanged, only the mode differs.
        self._last_digest = None
        self.show_jump_map(self._jump_map, roster=self._member_roster)

    def toggle_expanded(self) -> bool:
        """Flip collapsed/expanded state and repaint from the stored map."""
        self._expanded = not self._expanded
        # Force repaint even when only the subtitle arrow changes.
        self._last_digest = None
        self.show_jump_map(self._jump_map, roster=self._member_roster)
        return self._expanded


__all__ = ["AgentJumpPanel"]
