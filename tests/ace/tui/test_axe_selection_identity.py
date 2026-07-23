"""AXE tab selection follows item identity across list rebuilds."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.actions.axe_display import AxeDisplayMixin
from sase.ace.tui.actions.axe_display._loaders import AxeItemKey
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.actions.axe_display._loaders import _axe_item_key
from sase.ace.tui.actions.axe_config_actions._mixin import _PendingAxeSelection
from sase.ace.tui.widgets.bgcmd_list import AxeItem, ChopItem


class FakeAxeSelectionApp(AxeMixin, BasicNavigationMixin, AxeDisplayMixin):
    """Minimal app surface for AXE item rebuild and tab-restore tests."""

    def __init__(self) -> None:
        self.current_tab: Any = "axe"
        self.current_idx = 0
        self._axe_cmds_hidden = False
        self._axe_lumberjack_names: list[str] = []
        self._axe_lumberjack_chop_names: dict[str, list[str]] = {}
        self._bgcmd_slots: list[tuple[int, Any]] = []
        self._axe_items: list[AxeItem] = []
        self._axe_last_idx = 0
        self._axe_last_item_key: AxeItemKey | None = None
        self._axe_pending_selection: _PendingAxeSelection | None = None
        self._axe_current_view: Any = "axe"
        self._axe_fold_manager = FoldStateManager()
        self.refresh_count = 0

    def _refresh_axe_display(self) -> None:  # type: ignore[override]
        self.refresh_count += 1


def test_rebuild_preserves_selected_bgcmd_slot_when_lumberjack_inserted() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    # Layout: [LJ(hooks), Bgcmd(7)] — bgcmd at idx 1.
    app.current_idx = 1

    app._axe_lumberjack_names = ["checks", "hooks"]
    app._build_axe_items()

    # Layout: [LJ(checks), LJ(hooks), Bgcmd(7)] — bgcmd at idx 2.
    assert app.current_idx == 2
    assert app._axe_last_idx == 2
    assert app._axe_last_item_key == ("bgcmd", 7)


def test_saved_axe_tab_selection_restores_by_bgcmd_slot_key() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    app.current_idx = 1
    app._save_current_tab_position()

    app.current_tab = "agents"
    app.current_idx = 0
    app._axe_lumberjack_names = ["checks", "hooks"]
    app._build_axe_items()

    # Off-tab rebuild now follows the saved identity to its new row so
    # ``action_next_tab`` lands on the right entry without relying on a
    # second key-based lookup pass.  Plan §4.4 of tui_selection_drift.
    assert app._axe_last_idx == 2
    assert app._axe_last_item_key == ("bgcmd", 7)
    assert app._get_clamped_axe_idx() == 2


def test_rebuild_preserves_selected_lumberjack_name_when_lumberjack_inserted() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    # Layout: [LJ(hooks), Bgcmd(7)] — LJ(hooks) at idx 0.
    app.current_idx = 0

    app._axe_lumberjack_names = ["checks", "hooks"]
    app._build_axe_items()

    # Layout: [LJ(checks), LJ(hooks), Bgcmd(7)] — LJ(hooks) at idx 1.
    assert app.current_idx == 1
    assert app._axe_last_idx == 1
    assert app._axe_last_item_key == ("lumberjack", "hooks")


def test_rebuild_falls_back_when_selected_item_disappears() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()
    # Layout: [LJ(hooks), Bgcmd(7)] — bgcmd at idx 1.
    app.current_idx = 1

    app._bgcmd_slots = []
    app._build_axe_items()

    # Layout collapses to [LJ(hooks)]. The saved-key fall-back clamps to
    # the prior visual row's nearest survivor — row 0, the lumberjack.
    assert app.current_idx == 0
    assert app._axe_last_idx == 0
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
    app.current_idx = 1  # bgcmd-7 row
    app._save_current_tab_position()

    app.current_tab = "agents"
    app.current_idx = 12  # arbitrary value owned by the agents tab

    app._axe_lumberjack_names = ["checks", "hooks"]
    app._build_axe_items()

    # current_idx untouched (still owned by agents tab)
    assert app.current_idx == 12
    # saved AXE row follows the identity to its new position
    assert app._axe_last_item_key == ("bgcmd", 7)
    assert app._axe_last_idx == 2


def test_chop_item_identity_key() -> None:
    """Phase 2: chop rows use a 3-tuple identity key so selection
    survives lumberjack re-orderings and chop additions/removals.

    The key shape is exercised here so Phase 3 (which actually emits
    chop rows in ``_build_axe_items``) inherits a stable contract.
    """
    item = ChopItem(lumberjack_name="hooks", chop_name="fast")
    assert _axe_item_key(item) == ("chop", "hooks", "fast")


def test_switch_to_axe_view_moves_highlight_to_matching_row() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["checks", "hooks"]
    app._bgcmd_slots = [(7, object())]
    app._build_axe_items()

    app._switch_to_axe_view(7)

    # Layout: [LJ(checks), LJ(hooks), Bgcmd(7)] — bgcmd at idx 2.
    assert app.current_idx == 2
    assert app._axe_last_idx == 2
    assert app._axe_last_item_key == ("bgcmd", 7)
    assert app.refresh_count == 1


def test_pending_write_selection_expands_parent_and_selects_target() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._axe_lumberjack_chop_names = {"hooks": ["old"]}
    app._build_axe_items()
    app.current_idx = 0
    app._axe_fold_manager.collapse("lumberjack:hooks")
    app._axe_pending_selection = _PendingAxeSelection(
        target_key=("chop", "hooks", "new"),
        guard_key=("lumberjack", "hooks"),
    )
    app._axe_lumberjack_chop_names = {"hooks": ["old", "new"]}

    app._build_axe_items()

    assert app._axe_last_item_key == ("chop", "hooks", "new")
    assert app.current_idx == 2
    assert app._axe_pending_selection is None


def test_pending_write_selection_is_dropped_after_newer_navigation() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["checks", "hooks"]
    app._axe_lumberjack_chop_names = {"hooks": ["new"]}
    app._build_axe_items()
    app.current_idx = 1  # hooks
    app._axe_pending_selection = _PendingAxeSelection(
        target_key=("chop", "hooks", "new"),
        guard_key=("lumberjack", "hooks"),
    )
    app.current_idx = 0  # newer navigation to checks

    app._build_axe_items()

    assert app._axe_last_item_key == ("lumberjack", "checks")
    assert app._axe_pending_selection is None


def test_pending_write_selection_is_dropped_off_tab() -> None:
    app = FakeAxeSelectionApp()
    app._axe_lumberjack_names = ["hooks"]
    app._build_axe_items()
    app._axe_pending_selection = _PendingAxeSelection(
        target_key=("lumberjack", "new"),
        guard_key=("lumberjack", "hooks"),
    )
    app.current_tab = "agents"
    app.current_idx = 17

    app._build_axe_items()

    assert app.current_idx == 17
    assert app._axe_pending_selection is None
