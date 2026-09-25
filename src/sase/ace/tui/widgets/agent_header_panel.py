"""Sticky agent identity header panel for the Agents tab."""

from __future__ import annotations

from typing import Any

from rich.console import RenderableType
from rich.text import Text
from textual.app import ComposeResult
from textual.color import Color
from textual.containers import VerticalScroll
from textual.widgets import Static

from ..agent_header_settings import agent_header_settings_for
from ..keymaps import key_display_name
from .agent_header_preview import (
    PREVIEW_TAB_ROWS,
    XpromptPreviewFit,
    fit_xprompt_preview,
    pending_preview_rows,
    preview_card,
    preview_row_budget,
)
from .prompt_panel._identity_header import IdentityHeader

# Width used before the first layout, when the content widget has no size yet.
_FALLBACK_CONTENT_WIDTH = 76
# A node without an xprompt shows exactly the two chip rows inside the border.
_COMPACT_ROW_COUNT = 2


class AgentHeaderPanel(VerticalScroll):
    """Bordered sticky panel showing the selected node's identity header."""

    can_focus = False

    _identity: IdentityHeader | None = None
    _expanded: bool = False
    _last_kind: str | None = None
    _last_digest: str | None = None
    _column_rows: int = 0
    _last_preview_rows: int = 0
    _rendered_rows: int = 0

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

    @property
    def rendered_row_count(self) -> int:
        """Return the content row count from the last paint."""
        return self._rendered_rows

    def set_column_rows(self, rows: int) -> None:
        """Record the detail-column height and re-fit the preview."""
        try:
            rows = int(rows)
        except Exception:
            return
        if rows < 0:
            rows = 0
        if rows == self._column_rows:
            return
        self._column_rows = rows
        identity = self._identity
        if identity is not None:
            self.show_identity(identity)

    def on_resize(self, _event: Any = None) -> None:
        """Re-fit the preview when the panel width changes."""
        identity = self._identity
        if identity is None or self._expanded or identity.has_hints:
            return
        self.show_identity(identity)

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

    def _subtitle_for(self, expanded: bool, *, hidden_lines: int = 0) -> str:
        """Return the border subtitle hint for the expanded state."""
        key = self._toggle_key()
        if not key:
            base = "more" if not expanded else "less"
        else:
            arrow = "\u25b4" if expanded else "\u25be"
            word = "less" if expanded else "more"
            base = f"{arrow} {key} {word}"
        if hidden_lines > 0 and not expanded:
            return f"+{hidden_lines} lines · {base}"
        return base

    def _content_width(self) -> int:
        """Return the content width available for preview rows."""
        try:
            content = self.query_one("#agent-header-content", Static)
            width = int(getattr(content.size, "width", 0) or 0)
            if width > 0:
                return width
        except Exception:
            pass
        try:
            width = int(getattr(self.size, "width", 0) or 0)
            if width > 0:
                return max(width - 6, 1)
        except Exception:
            pass
        return _FALLBACK_CONTENT_WIDTH

    def _preview_budget(self) -> int:
        """Return how many preview rows the current column height allows."""
        settings = agent_header_settings_for(self)
        return preview_row_budget(self._column_rows, settings.collapsed_max_share)

    def _pending_hold_rows(self, budget: int) -> int:
        """Return the placeholder height held while the full paint is pending."""
        if budget <= 0:
            return 0
        return min(self._last_preview_rows, budget)

    def _collapsed_content(
        self, identity: IdentityHeader, width: int, budget: int
    ) -> tuple[RenderableType, XpromptPreviewFit | None, int]:
        """Return the collapsed renderable, its fit, and shown preview body rows.

        The preview is an ``XPROMPT`` card: the returned row count covers its
        body only, not the tab row above it.
        """
        collapsed = identity.compact.copy()
        if budget <= 0:
            return collapsed, None, 0
        if identity.xprompt_pending and identity.xprompt is None:
            hold = self._pending_hold_rows(budget)
            if hold <= 0:
                return collapsed, None, 0
            collapsed.append("\n")
            collapsed.append_text(preview_card(pending_preview_rows(hold), width=width))
            return collapsed, None, hold
        xprompt = identity.xprompt
        if xprompt is None or not xprompt.plain.strip():
            return collapsed, None, 0
        fit = fit_xprompt_preview(xprompt, width=width, max_rows=budget)
        if fit.rows <= 0:
            return collapsed, fit, 0
        collapsed.append("\n")
        collapsed.append_text(preview_card(fit.text, width=width))
        return collapsed, fit, fit.rows

    @staticmethod
    def _expanded_row_estimate(
        renderable: RenderableType, identity: IdentityHeader
    ) -> int:
        """Estimate expanded content rows for pin-reapply change detection."""
        plain: str | None = None
        if isinstance(renderable, Text):
            plain = renderable.plain
        else:
            getter = getattr(renderable, "plain", None)
            if isinstance(getter, str):
                plain = getter
        if plain is not None:
            return plain.count("\n") + 1
        rows = _COMPACT_ROW_COUNT + 2
        if identity.xprompt is not None:
            rows += identity.xprompt.plain.count("\n") + 1
        return rows

    def _apply_chrome(
        self, identity: IdentityHeader, shown_expanded: bool, subtitle: str
    ) -> None:
        """Update the border title, subtitle, and dimmed accent border."""
        title = Text(identity.kind_label, style=f"bold {identity.accent}")
        self.border_title = title
        self.border_subtitle = subtitle
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
            self._last_preview_rows = 0
            self._rendered_rows = 0
            content.update("")
            self.border_title = ""
            self.border_subtitle = ""
            return
        shown_expanded = bool(self._expanded or header.has_hints)
        width = self._content_width()
        budget = self._preview_budget()
        pending = bool(header.xprompt_pending and header.xprompt is None)
        if shown_expanded:
            shown: RenderableType = header.expanded_renderable()
            fit: XpromptPreviewFit | None = None
            preview_rows = 0
            hidden_lines = 0
            subtitle = self._subtitle_for(True)
            self._rendered_rows = self._expanded_row_estimate(shown, header)
        else:
            shown, fit, preview_rows = self._collapsed_content(header, width, budget)
            hidden_lines = fit.hidden_lines if fit is not None and fit.truncated else 0
            subtitle = self._subtitle_for(False, hidden_lines=hidden_lines)
            card_rows = PREVIEW_TAB_ROWS + preview_rows if preview_rows else 0
            self._rendered_rows = _COMPACT_ROW_COUNT + card_rows
        self._last_preview_rows = preview_rows
        try:
            digest = renderable_content_digest(shown)
            digest += (
                f"|{header.kind_label}|{subtitle}|{header.accent}|{shown_expanded}"
                f"|{width}|{budget}|{pending}|{preview_rows}|{hidden_lines}"
            )
        except Exception:
            digest = None
        if digest is not None and digest == self._last_digest:
            return
        self._last_digest = digest
        self._apply_chrome(header, shown_expanded, subtitle)
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
