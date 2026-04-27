"""AXE tab selection follows item identity across list rebuilds."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.actions.axe_display import AxeDisplayMixin
from sase.ace.tui.actions.axe_display._loaders import AxeItemKey
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets.bgcmd_list import AxeItem


class FakeAxeSelectionApp(AxeMixin, BasicNavigationMixin, AxeDisplayMixin):
    """Minimal app surface for AXE item rebuild and tab-restore tests."""

    def __init__(self) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 0
        self._axe_cmds_hidden = False
        self._axe_lumberjack_names: list[str] = []
        self._bgcmd_slots: list[tuple[int, Any]] = []
        self._axe_items: list[AxeItem] = []
        self._axe_last_idx = 0
        self._axe_last_item_key: AxeItemKey | None = None
        self._axe_current_view: Any = "axe"
        self._axe_fold_manager = FoldStateManager()
        self._axe_fold_manager.expand("axe")
        self.refresh_count = 0

    def _refresh_axe_display(self) -> None:  # type: ignore[override]
        self.refresh_count += 1


def test_rebuild_preserves_selected_bgcmd_slot_when_lumberjack_inserted() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    app.current_idx = 2

    app._axe_lumberjack_names = ["checks", "hooks"]
    app._build_axe_items()

    assert app.current_idx == 3
    assert app._axe_last_idx == 3
    assert app._axe_last_item_key == ("bgcmd", 7)


def test_saved_axe_tab_selection_restores_by_bgcmd_slot_key() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    app.current_idx = 2
    app._save_current_tab_position()

    app.current_tab = "agents"
    app.current_idx = 0
    app._axe_lumberjack_names = ["checks", "hooks"]
    app._build_axe_items()

    assert app._axe_last_idx == 2
    assert app._get_clamped_axe_idx() == 3


def test_rebuild_preserves_selected_lumberjack_name_when_lumberjack_inserted() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    app.current_idx = 1

    app._axe_lumberjack_names = ["checks", "hooks"]
    app._build_axe_items()

    assert app.current_idx == 2
    assert app._axe_last_idx == 2
    assert app._axe_last_item_key == ("lumberjack", "hooks")


def test_rebuild_falls_back_when_selected_item_disappears() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    app.current_idx = 2

    app._bgcmd_slots = []
    app._build_axe_items()

    assert app.current_idx == 0
    assert app._axe_last_idx == 0
    assert app._axe_last_item_key == ("axe", None)


def test_switch_to_axe_view_moves_highlight_to_matching_row() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["checks", "hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()

    app._switch_to_axe_view(7)

    assert app.current_idx == 3
    assert app._axe_last_idx == 3
    assert app._axe_last_item_key == ("bgcmd", 7)
    assert app.refresh_count == 1
