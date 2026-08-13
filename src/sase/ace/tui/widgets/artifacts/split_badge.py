"""Clickable split-mode badge for the Artifacts header."""

from __future__ import annotations

from typing import Any

from textual.message import Message
from textual.widgets import Static

from ...artifacts_split import (
    DEFAULT_ARTIFACTS_SPLIT_MODE,
    ArtifactsSplitMode,
    build_artifacts_split_badge,
)


class ArtifactsSplitBadge(Static):
    """Show the shared Artifacts split mode and cycle it on click."""

    class Clicked(Message):
        """Posted when the badge is clicked."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(
            build_artifacts_split_badge(DEFAULT_ARTIFACTS_SPLIT_MODE, "#666666"),
            **kwargs,
        )

    def set_state(self, mode: ArtifactsSplitMode, accent: str) -> None:
        """Render *mode* using the active Artifacts pane's accent."""

        self.update(build_artifacts_split_badge(mode, accent))

    def on_click(self) -> None:
        """Request one forward split-mode cycle."""

        self.post_message(self.Clicked())


__all__ = ["ArtifactsSplitBadge"]
