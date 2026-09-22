"""Sticky agent identity header panel for the Agents tab."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.color import Color
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..keymaps import key_display_name
from .prompt_panel._identity_header import IdentityHeader


class AgentHeaderPanel(VerticalScroll):
    """Bordered sticky panel showing the selected node's identity header."""

    can_focus = False

    _identity: IdentityHeader | None = None
    _expanded: bool = False
    _last_kind: str | None = None
    _last_digest: str | None = None

    def compose(self) -> ComposeResult:
        """Compose the inner content static."""
        yield Static(id="agent-header-content")

    @property
    def has_identity(self) -> bool:
        """Return whether a header identity is currently stored."""
        return self._identity is not None

    @property
    def is_expanded(self) -> bool:
        """Return whether the panel shows the expanded field list."""
        return self._expanded

    def _toggle_key(self) -> str:
        """Return the live display name for the header toggle key."""
        try:
            registry = getattr(getattr(self, "app", None), "_keymap_registry", None)
            if registry is not None:
                raw = getattr(getattr(registry, "app", None), "toggle_agent_header", "")
                if raw:
                    return key_display_name(str(raw))
        except Exception:
            pass
        return "d"

    def _subtitle_for(self, expanded: bool) -> str:
        """Return the border subtitle hint for the expanded state."""
        key = self._toggle_key()
        if not key:
            return "more" if not expanded else "less"
        arrow = "\u25b4" if expanded else "\u25be"
        word = "less" if expanded else "more"
        return f"{arrow} {key} {word}"

    def _apply_chrome(self, identity: IdentityHeader, shown_expanded: bool) -> None:
        """Update the border title, subtitle, and dimmed accent border."""
        title = Text(identity.kind_label, style=f"bold {identity.accent}")
        subtitle_text = self._subtitle_for(shown_expanded)
        self.border_title = title
        self.border_subtitle = subtitle_text
        if self._last_kind != identity.kind_label:
            self._last_kind = identity.kind_label
            try:
                dimmed = Color.parse(identity.accent).with_alpha(0.5)
                self.styles.border = ("round", dimmed)
            except Exception:
                try:
                    self.styles.border = ("round", identity.accent)
                except Exception:
                    pass

    def show_identity(self, header: IdentityHeader | None) -> None:
        """Render ``header`` (or clear when ``None``)."""
        from ..util.renderable_digest import renderable_content_digest

        self._identity = header
        try:
            content = self.query_one("#agent-header-content", Static)
        except Exception:
            return
        if header is None:
            self._last_digest = None
            self._last_kind = None
            content.update("")
            self.border_title = ""
            self.border_subtitle = ""
            return
        shown_expanded = bool(self._expanded or header.has_hints)
        shown = header.expanded if shown_expanded else header.compact
        subtitle = self._subtitle_for(shown_expanded)
        try:
            digest = renderable_content_digest(shown)
            digest += (
                f"|{header.kind_label}|{subtitle}|{header.accent}|{shown_expanded}"
            )
        except Exception:
            digest = None
        if digest is not None and digest == self._last_digest:
            return
        self._last_digest = digest
        self._apply_chrome(header, shown_expanded)
        content.update(shown)

    def toggle_expanded(self) -> bool:
        """Flip collapsed/expanded state and repaint from stored identity."""
        self._expanded = not self._expanded
        identity = self._identity
        if identity is None:
            return self._expanded
        # Force repaint even when only the subtitle arrow changes.
        self._last_digest = None
        self.show_identity(identity)
        return self._expanded


__all__ = ["AgentHeaderPanel"]
