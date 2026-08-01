"""Shared stable-target navigation for non-PR Artifacts entry lists."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol

from rich.text import Text


ArtifactEntryTarget = tuple[str, ...]


class ArtifactEntryNavigator(Protocol):
    """Small contract implemented by each non-PR Artifacts pane."""

    def entry_targets(self) -> tuple[ArtifactEntryTarget, ...]:
        """Return selectable entry identities in current visual order."""

    def selected_entry_target(self) -> ArtifactEntryTarget | None:
        """Return the currently selected stable identity, if any."""

    def select_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Select and focus a currently visible target."""

    def request_entry_target(self, target: ArtifactEntryTarget) -> bool:
        """Select a target now, or remember it for the next loaded row model."""

    def apply_entry_jump_hints(
        self,
        hints: Mapping[ArtifactEntryTarget, str],
    ) -> None:
        """Repaint selectable rows with transient adaptive jump hints."""

    def clear_entry_jump_hints(self) -> None:
        """Remove transient jump hints while preserving selection."""

    def apply_entry_marks(
        self,
        marks: set[ArtifactEntryTarget],
    ) -> None:
        """Repaint rows using the app-owned stable-target mark set."""

    def conditional_footer_entries(self) -> tuple[tuple[str, str], ...]:
        """Return action names and labels that depend on the selected row."""


def select_relative_entry(
    navigator: ArtifactEntryNavigator,
    *,
    offset: int | None = None,
    boundary: str | None = None,
) -> bool:
    """Resolve and select a target from the pane's current visual model.

    ``offset`` counts selectable targets and clamps at either boundary.  A
    missing selection starts at the first target for non-negative movement
    and the last target for negative movement.
    """
    targets = navigator.entry_targets()
    if not targets:
        return False
    if boundary == "first":
        target = targets[0]
    elif boundary == "last":
        target = targets[-1]
    elif offset is not None:
        current = navigator.selected_entry_target()
        try:
            current_index = targets.index(current) if current is not None else None
        except ValueError:
            current_index = None
        if current_index is None:
            current_index = 0 if offset >= 0 else len(targets) - 1
        target = targets[max(0, min(len(targets) - 1, current_index + offset))]
    else:
        return False
    return navigator.select_entry_target(target)


def prepend_jump_hint(prompt: Text, hint: str | None) -> Text:
    """Return a row prompt with the standard compact jump marker."""
    if hint is None:
        return prompt
    text = Text()
    text.append(f"[{hint}] ", style="bold #FFFF00")
    text.append_text(prompt.copy())
    return text


def prepend_mark_glyph(prompt: Text, marked: bool) -> Text:
    """Return a row prompt with the standard mark glyph when marked."""
    if not marked:
        return prompt
    text = Text()
    text.append("[✓] ", style="bold #00D700")
    text.append_text(prompt.copy())
    return text


__all__ = [
    "ArtifactEntryNavigator",
    "ArtifactEntryTarget",
    "prepend_jump_hint",
    "prepend_mark_glyph",
    "select_relative_entry",
]
