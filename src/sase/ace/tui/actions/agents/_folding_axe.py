"""Fold state helpers for the AXE tab."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ...models.fold_state import FoldStateManager


class AxeFoldingMixin:
    """Manage lumberjack and chop folds on the AXE tab."""

    current_idx: int

    def _focused_axe_lumberjack_name(self) -> str | None:
        """Return the lumberjack name for the focused AXE row, if any.

        Chops resolve to their parent lumberjack so ``l``/``h`` on a chop
        operates on the enclosing fold.
        """
        from ...widgets.bgcmd_list import ChopItem, LumberjackItem

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        if not axe_items or not (0 <= self.current_idx < len(axe_items)):
            return None
        item = axe_items[self.current_idx]
        if isinstance(item, LumberjackItem):
            return item.name
        if isinstance(item, ChopItem):
            return item.lumberjack_name
        return None

    def _navigate_to_axe_lumberjack(self, name: str) -> None:
        """Move the AXE cursor to the row for ``name`` if it is visible."""
        from ...widgets.bgcmd_list import LumberjackItem

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        for idx, item in enumerate(axe_items):
            if isinstance(item, LumberjackItem) and item.name == name:
                self.current_idx = idx
                return

    def _expand_axe_fold(self) -> None:
        """Expand the fold for the focused lumberjack (or chop's parent)."""
        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        name = self._focused_axe_lumberjack_name()
        if name is None:
            return
        if axe_fold_manager.expand(f"lumberjack:{name}"):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _collapse_axe_fold(self) -> None:
        """Collapse the fold for the focused lumberjack.

        If on a chop child, navigate to its parent lumberjack first so the
        cursor doesn't end up on a row that just disappeared.
        """
        from ...widgets.bgcmd_list import ChopItem

        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        name = self._focused_axe_lumberjack_name()
        if name is None:
            return

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        if axe_items and 0 <= self.current_idx < len(axe_items):
            if isinstance(axe_items[self.current_idx], ChopItem):
                self._navigate_to_axe_lumberjack(name)

        if axe_fold_manager.collapse(f"lumberjack:{name}"):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _expand_all_axe_folds(self) -> None:
        """Expand every lumberjack fold one level (``L`` on AXE)."""
        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        names: list[str] = list(self._axe_lumberjack_names)  # type: ignore[attr-defined]
        if not names:
            return
        keys = [f"lumberjack:{name}" for name in names]
        if axe_fold_manager.expand_all(keys):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]

    def _collapse_all_axe_folds(self) -> None:
        """Collapse every lumberjack fold one level (``H`` on AXE).

        If the cursor is on a chop child, snap to its parent lumberjack
        first so the cursor stays on a still-visible row.
        """
        from ...widgets.bgcmd_list import ChopItem

        axe_fold_manager: FoldStateManager = self._axe_fold_manager  # type: ignore[attr-defined]
        names: list[str] = list(self._axe_lumberjack_names)  # type: ignore[attr-defined]
        if not names:
            return

        axe_items: list[object] = self._axe_items  # type: ignore[attr-defined]
        if axe_items and 0 <= self.current_idx < len(axe_items):
            selected = axe_items[self.current_idx]
            if isinstance(selected, ChopItem):
                self._navigate_to_axe_lumberjack(selected.lumberjack_name)

        keys = [f"lumberjack:{name}" for name in names]
        if axe_fold_manager.collapse_all(keys):
            self._build_axe_items()  # type: ignore[attr-defined]
            self._refresh_axe_display()  # type: ignore[attr-defined]


__all__ = ["AxeFoldingMixin"]
