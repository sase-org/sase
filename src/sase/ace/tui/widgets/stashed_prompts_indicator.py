"""Persistent stashed-prompts indicator widget for sase's TUI."""

from typing import Any

from rich.text import Text

from .top_bar_group import TopBarGroup, filled_count_chip

_STASH_ACCENT = "#00D7AF"


class StashedPromptsIndicator(TopBarGroup):
    """Top-bar badge showing how many prompt drafts are stashed.

    Renders as ``prompts: N`` with a filled teal count chip. Mirrors
    :class:`ProcIndicator`: visible only when at least one prompt is
    stashed, hidden (empty) otherwise so it never adds clutter when the
    stash is empty. The teal accent reads as "set aside for later"
    (git-stash for prompts) and is visually distinct from the task (cyan)
    and notification (orange/gold) badges. Clicking opens the prompt stash
    picker.
    """

    GROUP_LABEL = "prompts"
    CLICK_ACTION = "open_prompt_stash"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._count = 0
        self._pinned_count = 0
        self._set_body(self._build_content(0))
        self.tooltip = self._build_tooltip(0)

    @property
    def count(self) -> int:
        """Number of stashed prompts the badge currently reflects."""
        return self._count

    @property
    def pinned_count(self) -> int:
        """Number of pinned stashed prompts cached for prompt hints."""
        return self._pinned_count

    def set_count(self, count: int, *, pinned_count: int | None = None) -> None:
        """Update the displayed stashed-prompt count.

        Args:
            count: Number of restorable stashed prompts on disk. Negative
                values are clamped to zero.
        """
        count = max(0, count)
        pinned_count = self._pinned_count if pinned_count is None else pinned_count
        pinned_count = min(max(0, pinned_count), count)
        if self._count == count and self._pinned_count == pinned_count:
            return
        self._count = count
        self._pinned_count = pinned_count
        self._set_body(self._build_content(count))
        tooltip = self._build_tooltip(count)
        if self.tooltip != tooltip:
            self.tooltip = tooltip

    @staticmethod
    def _build_content(count: int) -> Text:
        """Build the badge body; empty (hidden) when nothing is stashed."""
        return filled_count_chip(count, _STASH_ACCENT)

    @staticmethod
    def _build_tooltip(count: int) -> str:
        """Build the hover tooltip describing the stash size."""
        if count <= 0:
            return "No stashed prompts\nClick to open the prompt stash"
        if count == 1:
            return "1 stashed prompt\nClick to open the prompt stash"
        return f"{count} stashed prompts\nClick to open the prompt stash"
