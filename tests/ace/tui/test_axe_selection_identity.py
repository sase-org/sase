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

    # Off-tab rebuild now follows the saved identity to its new row so
    # ``action_next_tab`` lands on the right entry without relying on a
    # second key-based lookup pass.  Plan §4.4 of tui_selection_drift.
    assert app._axe_last_idx == 3
    assert app._axe_last_item_key == ("bgcmd", 7)
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

    # Plan §4.1 nearest-neighbor fallback: when the saved identity is
    # gone, clamp to the prior visual row in the new list (here row 2
    # clamps to row 1 — the last surviving row).  Old behaviour
    # snapped to row 0 ("parent AXE" fallback) which violated the
    # unified invariant.
    assert app.current_idx == 1
    assert app._axe_last_idx == 1
    assert app._axe_last_item_key == ("lumberjack", "hooks")


def test_off_tab_rebuild_does_not_mutate_current_idx() -> None:
    """Plan §4.4: an off-tab AXE rebuild leaves ``current_idx`` alone.

    ``current_idx`` belongs to the active tab. When the axe daemon
    pushes a status update while the user is on Agents/ChangeSpecs,
    ``_build_axe_items`` must update only the AXE-tab saved fields
    (``_axe_last_idx`` / ``_axe_last_item_key``) and leave the
    cross-tab ``current_idx`` untouched.
    """
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    app.current_idx = 2  # bgcmd-7 row
    app._save_current_tab_position()

    app.current_tab = "agents"
    app.current_idx = 12  # arbitrary value owned by the agents tab

    app._axe_lumberjack_names = ["checks", "hooks"]
    app._build_axe_items()

    # current_idx untouched (still owned by agents tab)
    assert app.current_idx == 12
    # saved AXE row follows the identity to its new position
    assert app._axe_last_item_key == ("bgcmd", 7)
    assert app._axe_last_idx == 3


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
