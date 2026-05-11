"""Phase 4: chop-row selection routes to the chop-detail view."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.actions.axe_display import AxeDisplayMixin
from sase.ace.tui.actions.axe_display._loaders import AxeItemKey
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets.bgcmd_list import AxeItem, ChopItem, LumberjackItem


class _Fake(AxeMixin, BasicNavigationMixin, AxeDisplayMixin):
    """Minimal app surface that exercises chop-row selection routing."""

    def __init__(self) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 0
        self.notifications: list[tuple[str, str]] = []
        self.refresh_count = 0
        self._axe_cmds_hidden = False
        self._axe_lumberjack_names: list[str] = ["hooks"]
        self._axe_lumberjack_chop_names: dict[str, list[str]] = {"hooks": ["fast"]}
        self._bgcmd_slots: list[tuple[int, Any]] = []
        self._axe_items: list[AxeItem] = [
            LumberjackItem(name="hooks"),
            ChopItem(lumberjack_name="hooks", chop_name="fast"),
        ]
        self._axe_last_idx = 0
        self._axe_last_item_key: AxeItemKey | None = None
        self._axe_current_view: Any = "axe"
        self._axe_chop_selection: tuple[str, str] | None = None
        self._axe_lumberjack_idx: int | None = None
        self._axe_fold_manager = FoldStateManager()

    def _refresh_axe_display(self) -> None:  # type: ignore[override]
        self.refresh_count += 1

    def notify(  # type: ignore[override]
        self, message: str, *, severity: str = "information", **_: Any
    ) -> None:
        self.notifications.append((message, severity))


def test_chop_row_selection_sets_chop_selection_field() -> None:
    """Selecting a chop row sets ``_axe_chop_selection`` and pins parent idx."""
    app = _Fake()
    app.current_idx = 1  # ChopItem(hooks, fast)
    app._derive_axe_view_from_selection()

    assert app._axe_current_view == "axe"
    assert app._axe_chop_selection == ("hooks", "fast")
    assert app._axe_lumberjack_idx == 0


def test_lumberjack_row_selection_clears_chop_selection() -> None:
    """Moving back to a lumberjack row clears any sticky chop identity."""
    app = _Fake()
    app.current_idx = 1  # chop
    app._derive_axe_view_from_selection()
    assert app._axe_chop_selection is not None

    app.current_idx = 0  # lumberjack
    app._derive_axe_view_from_selection()

    assert app._axe_chop_selection is None
    assert app._axe_current_view == "axe"
    assert app._axe_lumberjack_idx == 0


def test_clear_output_on_chop_row_warns_and_leaves_history_intact() -> None:
    """``X`` on a chop row is a no-op against on-disk history (safer default).

    The bead's Phase 4 product direction is to keep chop run history
    immutable from the TUI; the affordance should surface a warning
    instead of silently mutating the parent lumberjack's log.
    """
    app = _Fake()
    app.current_idx = 1  # ChopItem(hooks, fast)

    called: list[str] = []

    with (
        patch(
            "sase.ace.tui.actions.axe.clear_lumberjack_output_log",
            lambda name: called.append(name),
        ),
        patch(
            "sase.ace.tui.actions.axe.clear_slot_output",
            lambda slot: called.append(f"slot:{slot}"),
        ),
    ):
        app.action_clear_axe_output()

    assert called == [], "chop rows must not mutate lumberjack/bgcmd logs"
    assert app.notifications, "user must be told why nothing happened"
    message, severity = app.notifications[-1]
    assert "immutable" in message.lower()
    assert severity == "warning"
