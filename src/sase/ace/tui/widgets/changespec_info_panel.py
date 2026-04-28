"""ChangeSpec info panel showing count and refresh countdown."""

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.ace.tui.keymaps import KeymapRegistry, key_display_name, load_keymap_registry
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

# Per-mode badge color, mirroring the Agents info panel palette.
_GROUPING_MODE_STYLES: dict[str, str] = {
    "by project": "bold #5FAFFF",
    "by date": "bold #87D7FF",
    "by status": "bold #FFAF87",
}


class ChangeSpecInfoPanel(Static):
    """Panel showing ChangeSpec position and auto-refresh countdown."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._current_position: int = 0  # 1-based position
        self._total_count: int = 0
        self._seconds_remaining: int = 0
        self._refresh_interval: int = 0
        self._marked_count: int = 0
        self._hidden_reverted: int = 0  # Reverted/archived hidden from list
        self._hidden_submitted: int = 0  # Submitted hidden from list
        self._fold_commits: FoldLevel = FoldLevel.COLLAPSED
        self._fold_hooks: FoldLevel = FoldLevel.COLLAPSED
        self._fold_mentors: FoldLevel = FoldLevel.COLLAPSED
        self._fold_timestamps: FoldLevel = FoldLevel.COLLAPSED
        # Empty string means "flat" — the badge stays hidden so the dense
        # CL top bar is not cluttered when the user has not opted in to
        # grouping.  Non-empty values turn the badge on.
        self._grouping_label: str = ""
        self._registry: KeymapRegistry = load_keymap_registry({})

    def set_keymap_registry(self, registry: KeymapRegistry) -> None:
        """Override the keymap registry and refresh display."""
        self._registry = registry
        self._refresh_content()

    def update_grouping_mode(self, label: str) -> None:
        """Update the active CL grouping-strategy label.

        Args:
            label: Human-readable label.  Empty string (or ``"flat"``)
                hides the badge so the FLAT default doesn't clutter the
                top bar.
        """
        normalized = "" if label.lower() in ("", "flat") else label
        if self._grouping_label != normalized:
            self._grouping_label = normalized
            self._refresh_content()

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

    def update_hidden_counts(self, reverted: int, submitted: int) -> None:
        """Update the hidden ChangeSpec counts.

        Args:
            reverted: Number of reverted/archived CLs hidden from the list.
            submitted: Number of submitted CLs hidden from the list.
        """
        if self._hidden_reverted != reverted or self._hidden_submitted != submitted:
            self._hidden_reverted = reverted
            self._hidden_submitted = submitted
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
        timestamps: FoldLevel = FoldLevel.COLLAPSED,
    ) -> None:
        """Update the fold state indicators.

        Args:
            commits: Fold level for the commits section.
            hooks: Fold level for the hooks section.
            mentors: Fold level for the mentors section.
            timestamps: Fold level for the timestamps section.
        """
        if (
            self._fold_commits != commits
            or self._fold_hooks != hooks
            or self._fold_mentors != mentors
            or self._fold_timestamps != timestamps
        ):
            self._fold_commits = commits
            self._fold_hooks = hooks
            self._fold_mentors = mentors
            self._fold_timestamps = timestamps
            self._refresh_content()

    def _build_content(self) -> Text:
        """Build the panel content as a Text object."""
        text = Text()
        text.append("ChangeSpec: ", style="bold")
        text.append(f"{self._current_position}/{self._total_count}", style="#00D7AF")

        if self._marked_count > 0:
            text.append("   ", style="")
            text.append(f"[{self._marked_count} marked]", style="bold #00D700")

        # Hidden count badges (shown when items are hidden from the list)
        if self._hidden_reverted > 0 or self._hidden_submitted > 0:
            text.append("   ", style="")
            if self._hidden_reverted > 0:
                text.append(f"+{self._hidden_reverted}", style="dim #808080")
                text.append("X", style="bold #808080")
            if self._hidden_reverted > 0 and self._hidden_submitted > 0:
                text.append(" ", style="")
            if self._hidden_submitted > 0:
                text.append(f"+{self._hidden_submitted}", style="dim #00AF00")
                text.append("S", style="bold #00AF00")

        # Fold indicators (only shown when any section is non-collapsed)
        has_fold = not (
            self._fold_commits == FoldLevel.COLLAPSED
            and self._fold_hooks == FoldLevel.COLLAPSED
            and self._fold_mentors == FoldLevel.COLLAPSED
            and self._fold_timestamps == FoldLevel.COLLAPSED
        )
        if has_fold:
            text.append("   ", style="")
            for label, level in [
                ("c", self._fold_commits),
                ("h", self._fold_hooks),
                ("m", self._fold_mentors),
                ("t", self._fold_timestamps),
            ]:
                text.append(label, style=_LABEL_STYLE)
                text.append(_FOLD_CHARS[level], style=_FOLD_STYLES[level])

        if self._grouping_label:
            text.append("   ", style="")
            text.append("[", style="dim")
            text.append("group: ", style="dim")
            text.append(
                self._grouping_label,
                style=_GROUPING_MODE_STYLES.get(self._grouping_label, "dim"),
            )
            key = key_display_name(self._registry.app.cycle_grouping_mode)
            text.append(f" ({key})", style="dim")
            text.append("]", style="dim")

        if self._refresh_interval > 0:
            text.append("   (auto-refresh in ", style="dim")
            text.append(f"{self._seconds_remaining}s", style="#87AFFF")
            text.append(")", style="dim")

        return text

    def _refresh_content(self) -> None:
        """Refresh the panel display."""
        self.update(self._build_content())
