"""ChangeSpec info panel showing count and refresh countdown."""

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.models.fold_state import FoldLevel

# Fold indicator characters per level
_FOLD_CHARS: dict[FoldLevel, str] = {
    FoldLevel.COLLAPSED: "▸",
    FoldLevel.EXPANDED: "▾",
    FoldLevel.FULLY_EXPANDED: "▼",
}

# Fold indicator styles per level
_FOLD_STYLES: dict[FoldLevel, str] = {
    FoldLevel.COLLAPSED: "#5f5f5f",
    FoldLevel.EXPANDED: "#00D7AF",
    FoldLevel.FULLY_EXPANDED: "bold #87FFD7",
}

# Label style (dimmed letter before each indicator)
_LABEL_STYLE = "dim #808080"


class ChangeSpecInfoPanel(Static):
    """Panel showing ChangeSpec position and auto-refresh countdown."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_position: int = 0  # 1-based position
        self._total_count: int = 0
        self._seconds_remaining: int = 0
        self._refresh_interval: int = 0
        self._marked_count: int = 0
        self._fold_commits: FoldLevel = FoldLevel.COLLAPSED
        self._fold_hooks: FoldLevel = FoldLevel.COLLAPSED
        self._fold_mentors: FoldLevel = FoldLevel.COLLAPSED

    def update_position(self, position: int, total: int, marked_count: int = 0) -> None:
        """Update the current position and total count.

        Args:
            position: 1-based position (e.g., 2 means viewing #2)
            total: Total number of filtered changespecs
            marked_count: Number of marked ChangeSpecs
        """
        self._current_position = position
        self._total_count = total
        self._marked_count = marked_count
        self._refresh_content()

    def update_countdown(self, remaining: int, interval: int) -> None:
        """Update the countdown timer.

        Args:
            remaining: Seconds remaining until refresh
            interval: Total refresh interval in seconds
        """
        self._seconds_remaining = remaining
        self._refresh_interval = interval
        self._refresh_content()

    def update_fold_states(
        self,
        commits: FoldLevel,
        hooks: FoldLevel,
        mentors: FoldLevel,
    ) -> None:
        """Update the fold state indicators.

        Args:
            commits: Fold level for the commits section.
            hooks: Fold level for the hooks section.
            mentors: Fold level for the mentors section.
        """
        if (
            self._fold_commits != commits
            or self._fold_hooks != hooks
            or self._fold_mentors != mentors
        ):
            self._fold_commits = commits
            self._fold_hooks = hooks
            self._fold_mentors = mentors
            self._refresh_content()

    def _build_content(self) -> Text:
        """Build the panel content as a Text object."""
        text = Text()
        text.append("ChangeSpec: ", style="bold")
        text.append(f"{self._current_position}/{self._total_count}", style="#00D7AF")

        if self._marked_count > 0:
            text.append("   ", style="")
            text.append(f"[{self._marked_count} marked]", style="bold #00D700")

        # Fold indicators (only shown when any section is non-collapsed)
        has_fold = not (
            self._fold_commits == FoldLevel.COLLAPSED
            and self._fold_hooks == FoldLevel.COLLAPSED
            and self._fold_mentors == FoldLevel.COLLAPSED
        )
        if has_fold:
            text.append("   ", style="")
            for label, level in [
                ("c", self._fold_commits),
                ("h", self._fold_hooks),
                ("m", self._fold_mentors),
            ]:
                text.append(label, style=_LABEL_STYLE)
                text.append(_FOLD_CHARS[level], style=_FOLD_STYLES[level])

        if self._refresh_interval > 0:
            text.append("   (auto-refresh in ", style="dim")
            text.append(f"{self._seconds_remaining}s", style="#87AFFF")
            text.append(")", style="dim")

        return text

    def _refresh_content(self) -> None:
        """Refresh the panel display."""
        self.update(self._build_content())
