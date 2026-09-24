"""J/K panel jumps on the Services tab."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.axe_display._panel_navigation import (
    AxePanelNavigationMixin,
)
from sase.ace.tui.actions.axe_display._panels import build_services_panel_index
from sase.ace.tui.actions.navigation._entry_jump_generic import (
    EntryJumpGenericHistoryMixin,
)
from sase.ace.tui.widgets.bgcmd_list import (
    AxeItem,
    BgCmdItem,
    ChopItem,
    LumberjackItem,
    ServiceProcItem,
)


def _items() -> list[AxeItem]:
    return [
        ServiceProcItem(name="scheduler"),
        ServiceProcItem(name="telegram"),
        BgCmdItem(slot=1),
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="refresh"),
        ChopItem(lumberjack_name="hooks", chop_name="rebase"),
        LumberjackItem(name="mentors"),
    ]


class FakeServiceJumpApp(AxePanelNavigationMixin, EntryJumpGenericHistoryMixin):
    """Minimal app surface for Services J/K panel-jump tests."""

    def __init__(self, items: list[AxeItem], current_idx: int = 0) -> None:
        self.current_tab: Any = "services"
        self.current_idx = current_idx
        self._axe_items = items
        self._axe_panel_index = build_services_panel_index(items)
        self._entry_jump_index_stack: dict[str, list[Any]] = {}
        self.recorded_navigations = 0
        self.perf_begins: list[str] = []

    def _record_jk_navigation(self) -> None:
        self.recorded_navigations += 1

    def _jk_perf_begin(self, action: str) -> None:
        self.perf_begins.append(action)

    def call_after_refresh(self, callback: Any, *args: Any) -> Any:
        return None


def test_j_from_service_procs_lands_on_first_routine_node() -> None:
    app = FakeServiceJumpApp(_items(), current_idx=0)
    app.action_focus_next_service_panel()
    assert app.current_idx == 3
    assert app.perf_begins == ["next_service_panel"]
    assert app.recorded_navigations == 1


def test_k_from_service_procs_lands_on_last_rendered_routine_node() -> None:
    app = FakeServiceJumpApp(_items(), current_idx=1)
    app.action_focus_prev_service_panel()
    assert app.current_idx == 6
    assert app.perf_begins == ["prev_service_panel"]


def test_k_counts_collapsed_routine_as_single_row() -> None:
    items: list[AxeItem] = [
        ServiceProcItem(name="scheduler"),
        LumberjackItem(name="hooks"),
    ]
    app = FakeServiceJumpApp(items, current_idx=0)
    app.action_focus_prev_service_panel()
    assert app.current_idx == 1


def test_j_from_routines_wraps_to_first_service_proc() -> None:
    app = FakeServiceJumpApp(_items(), current_idx=5)
    app.action_focus_next_service_panel()
    assert app.current_idx == 0


def test_k_from_routines_lands_on_last_service_or_oneshot_node() -> None:
    app = FakeServiceJumpApp(_items(), current_idx=4)
    app.action_focus_prev_service_panel()
    assert app.current_idx == 2


def test_noop_when_other_panel_empty_pushes_no_origin() -> None:
    items: list[AxeItem] = [ServiceProcItem(name="scheduler")]
    app = FakeServiceJumpApp(items, current_idx=0)
    app.action_focus_next_service_panel()
    assert app.current_idx == 0
    assert app._entry_jump_index_stack.get("services", []) == []
    app.action_focus_prev_service_panel()
    assert app.current_idx == 0
    assert app._entry_jump_index_stack.get("services", []) == []


def test_noop_off_services_tab() -> None:
    app = FakeServiceJumpApp(_items(), current_idx=0)
    app.current_tab = "agents"
    app.action_focus_next_service_panel()
    assert app.current_idx == 0
    assert app._entry_jump_index_stack.get("agents", []) == []


def test_jump_pushes_origin_and_back_jump_restores_it() -> None:
    app = FakeServiceJumpApp(_items(), current_idx=1)
    app.action_focus_next_service_panel()
    assert app.current_idx == 3
    assert app._entry_jump_index_stack.get("services") == [1]
    anchor = app._pop_entry_jump_index()
    assert anchor == 1
    assert app._restore_entry_jump_anchor(anchor) is True
    assert app.current_idx == 1
