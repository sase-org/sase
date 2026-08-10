"""Fold state management for collapsible sections in the TUI."""

from __future__ import annotations

from collections.abc import Mapping
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .fold_scale import FoldScale


class FoldLevel(Enum):
    """Fold level for a collapsible section."""

    COLLAPSED = "collapsed"
    EXPANDED = "expanded"
    FULLY_EXPANDED = "fully_expanded"
    EXHAUSTIVE = "exhaustive"


def cycle_forward(level: FoldLevel) -> FoldLevel:
    """Cycle the legacy three-level Patch/axe fold ladder forward."""
    if level == FoldLevel.COLLAPSED:
        return FoldLevel.EXPANDED
    if level == FoldLevel.EXPANDED:
        return FoldLevel.FULLY_EXPANDED
    return FoldLevel.COLLAPSED


def cycle_deltas_fold_level(level: FoldLevel) -> FoldLevel:
    """Cycle DELTAS forward through summary, files, and line details."""
    return cycle_forward(level)


class SectionFoldStateManager:
    """Store per-section overrides for a shared panel fold level.

    Missing entries inherit the caller-provided panel level.  This keeps the
    registry independent of any one panel renderer while preserving the
    distinction between an explicit override and inherited state.
    """

    def __init__(self) -> None:
        self._overrides: dict[str, FoldLevel] = {}

    def get_override(self, section_id: str) -> FoldLevel | None:
        """Return the explicit override for ``section_id``, if one exists."""
        return self._overrides.get(section_id)

    def effective_level(
        self,
        section_id: str,
        panel_level: FoldLevel,
    ) -> FoldLevel:
        """Return the override for ``section_id`` or the shared panel level."""
        return self._overrides.get(section_id, panel_level)

    def set(self, section_id: str, level: FoldLevel) -> None:
        """Store an explicit fold level for ``section_id``."""
        self._overrides[section_id] = level

    def cycle(
        self,
        section_id: str,
        panel_level: FoldLevel,
        *,
        scale: FoldScale | None = None,
    ) -> FoldLevel:
        """Cycle one section forward from its current effective level."""
        current = self.effective_level(section_id, panel_level)
        if scale is None:
            level = cycle_forward(current)
        else:
            from .fold_scale import cycle_fold_level_forward

            level = cycle_fold_level_forward(current, scale)
        self.set(section_id, level)
        return level

    def toggle(
        self,
        section_id: str,
        panel_level: FoldLevel,
        *,
        scale: FoldScale | None = None,
    ) -> FoldLevel:
        """Toggle one section between its scale's first and last levels."""
        current = self.effective_level(section_id, panel_level)
        if scale is None:
            level = (
                FoldLevel.FULLY_EXPANDED
                if current == FoldLevel.COLLAPSED
                else FoldLevel.COLLAPSED
            )
        else:
            from .fold_scale import toggle_fold_level

            level = toggle_fold_level(current, scale)
        self.set(section_id, level)
        return level

    def clear(self) -> None:
        """Clear all overrides so every section inherits the panel level."""
        self._overrides.clear()

    def snapshot(self) -> dict[str, FoldLevel]:
        """Return a plain copy of the stored overrides."""
        return dict(self._overrides)


class FoldStateManager:
    """Manages fold state for workflow entries in the Agents tab.

    Each workflow is identified by its raw_suffix (timestamp string).
    Default fold state is COLLAPSED.
    """

    def __init__(self) -> None:
        self._states: dict[str, FoldLevel] = {}

    def get(self, key: str) -> FoldLevel:
        """Get the fold level for a workflow key.

        Args:
            key: Workflow raw_suffix (timestamp).

        Returns:
            Current fold level (defaults to COLLAPSED).
        """
        return self._states.get(key, FoldLevel.COLLAPSED)

    def has(self, key: str) -> bool:
        """Return ``True`` if a level has been explicitly stored for *key*."""
        return key in self._states

    def expand(self, key: str) -> bool:
        """Advance fold level one step: COLLAPSED -> EXPANDED -> FULLY_EXPANDED.

        Args:
            key: Workflow raw_suffix (timestamp).

        Returns:
            True if the level changed, False if already fully expanded.
        """
        current = self.get(key)
        if current == FoldLevel.COLLAPSED:
            self._states[key] = FoldLevel.EXPANDED
            return True
        if current == FoldLevel.EXPANDED:
            self._states[key] = FoldLevel.FULLY_EXPANDED
            return True
        return False

    def collapse(self, key: str) -> bool:
        """Retreat fold level one step: FULLY_EXPANDED -> EXPANDED -> COLLAPSED.

        Args:
            key: Workflow raw_suffix (timestamp).

        Returns:
            True if the level changed, False if already collapsed.
        """
        current = self.get(key)
        if current == FoldLevel.FULLY_EXPANDED:
            self._states[key] = FoldLevel.EXPANDED
            return True
        if current == FoldLevel.EXPANDED:
            self._states[key] = FoldLevel.COLLAPSED
            return True
        return False

    def expand_all(self, keys: list[str]) -> bool:
        """Expand all given workflow keys one level.

        Args:
            keys: List of workflow raw_suffix strings.

        Returns:
            True if any level changed.
        """
        changed = False
        for key in keys:
            if self.expand(key):
                changed = True
        return changed

    def collapse_all(self, keys: list[str]) -> bool:
        """Collapse all given workflow keys one level.

        If any are FULLY_EXPANDED, only collapse those (to EXPANDED).
        Otherwise, collapse all EXPANDED to COLLAPSED.

        Args:
            keys: List of workflow raw_suffix strings.

        Returns:
            True if any level changed.
        """
        # First pass: if any are fully expanded, only collapse those
        if self.has_any_fully_expanded(keys):
            changed = False
            for key in keys:
                if self.get(key) == FoldLevel.FULLY_EXPANDED:
                    self._states[key] = FoldLevel.EXPANDED
                    changed = True
            return changed

        # Second pass: collapse all expanded to collapsed
        changed = False
        for key in keys:
            if self.collapse(key):
                changed = True
        return changed

    def collapse_fully_all(self, keys: list[str]) -> bool:
        """Drive every open fold in *keys* directly to ``COLLAPSED``.

        Unlike :meth:`collapse_all`, this is a saturating bulk operation:
        ``FULLY_EXPANDED`` folds do not stop at the intermediate level.  The
        state mutations are completed together so callers can repaint once.
        """
        changed = False
        for key in keys:
            if self.get(key) == FoldLevel.COLLAPSED:
                continue
            self._states[key] = FoldLevel.COLLAPSED
            changed = True
        return changed

    def restore_levels(self, levels: Mapping[str, FoldLevel]) -> bool:
        """Write each exact remembered level, returning whether any changed.

        Unlike :meth:`expand`, which steps one level at a time and cannot
        reach ``EXHAUSTIVE``, a restore must land on the remembered level
        exactly.
        """
        changed = False
        for key, level in levels.items():
            if self._states.get(key) == level:
                continue
            self._states[key] = level
            changed = True
        return changed

    def has_any_fully_expanded(self, keys: list[str]) -> bool:
        """Check if any of the given keys are fully expanded.

        Args:
            keys: List of workflow raw_suffix strings.

        Returns:
            True if any key is at FULLY_EXPANDED level.
        """
        return any(self.get(key) == FoldLevel.FULLY_EXPANDED for key in keys)

    def snapshot(self) -> dict[str, FoldLevel]:
        """Return a plain copy of the stored fold levels."""
        return dict(self._states)
