"""Host-owned Artifacts pane description brief widget."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.message import Message
from textual.widgets import Static

from ...artifacts_description import ArtifactsDescriptionMode
from .shell import build_pane_brief


class ArtifactsPaneBrief(Static):
    """Render the active Artifacts pane's resolved description."""

    class Clicked(Message):
        """Posted when the brief is clicked."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__("", **kwargs)
        self._icon = ""
        self._accent = "#666666"
        self._summary = ""
        self._body = ""
        self._mode: ArtifactsDescriptionMode = "off"
        self._disclosure_key: str | None = None
        self._unconfigured_hint: str | None = None
        self._renderable = self._build_renderable()
        self.display = False

    def render(self) -> Text:
        """Return the cached renderable without requiring an app mount."""
        return self._renderable

    def set_state(
        self,
        *,
        icon: str,
        accent: str,
        summary: str,
        body: str,
        mode: ArtifactsDescriptionMode,
        disclosure_key: str | None,
        unconfigured_hint: str | None = None,
    ) -> None:
        """Repaint the brief from already-resolved pane description values."""

        self._icon = icon
        self._accent = accent
        self._summary = summary
        self._body = body
        self._mode = mode
        self._disclosure_key = disclosure_key
        self._unconfigured_hint = unconfigured_hint
        self.display = mode != "off"
        self._rerender()

    def on_resize(self) -> None:
        """Recompute wrapping when the brief's width changes."""
        self._rerender()

    def _rerender(self) -> None:
        self._renderable = self._build_renderable()
        if self.is_attached:
            self.refresh(layout=True)

    def _build_renderable(self) -> Text:
        width = self.size.width or 80
        return build_pane_brief(
            icon=self._icon,
            accent=self._accent,
            summary=self._summary,
            body=self._body,
            mode=self._mode,
            width=width,
            disclosure_key=self._disclosure_key,
            unconfigured_hint=self._unconfigured_hint,
        )

    def on_click(self) -> None:
        """Request one forward description-mode cycle."""
        self.post_message(self.Clicked())


__all__ = ["ArtifactsPaneBrief"]
