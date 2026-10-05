"""Services j/k stay inside the focused nav section."""

from __future__ import annotations

from typing import Any

from sase.ace.tui.actions.axe_display._panels import build_services_panel_index
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
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


def _sourced_items() -> tuple[list[AxeItem], dict[str, Any]]:
    items: list[AxeItem] = [
        ServiceProcItem(name="scheduler"),
        BgCmdItem(slot=1),
        LumberjackItem(name="hooks"),
        ChopItem(lumberjack_name="hooks", chop_name="refresh"),
        ChopItem(lumberjack_name="hooks", chop_name="rebase"),
        LumberjackItem(name="sentinels"),
        ChopItem(lumberjack_name="sentinels", chop_name="watch"),
        LumberjackItem(name="checks"),
        ChopItem(lumberjack_name="checks", chop_name="smoke"),
    ]
    origins: dict[str, Any] = {
        "hooks": {"source": "user"},
        "sentinels": {"source": "plugin"},
        "checks": {"source": "builtin"},
    }
    return items, origins


class FakeServiceJkApp(BasicNavigationMixin):
    """Minimal app surface for Services j/k section-cycling tests."""

    def __init__(
        self,
        items: list[AxeItem],
        current_idx: int = 0,
        routine_origins: dict[str, Any] | None = None,
    ) -> None:
        self.current_tab: Any = "services"
        self.current_idx = current_idx
        self._axe_items = items
        self._axe_panel_index = build_services_panel_index(items, routine_origins)
        self._entry_jump_index_stack: dict[str, list[Any]] = {}
        self.recorded_navigations = 0
        self.perf_begins: list[str] = []

    def _record_jk_navigation(self) -> None:
        self.recorded_navigations += 1

    def _jk_perf_begin(self, action: str) -> None:
        self.perf_begins.append(action)


def test_j_on_last_service_procs_row_wraps_inside_service_procs() -> None:
    app = FakeServiceJkApp(_items(), current_idx=2)
    app.action_next_patch()
    assert app.current_idx == 0
    assert app.perf_begins == ["next"]
    assert app.recorded_navigations == 1


def test_k_on_first_service_procs_row_wraps_inside_service_procs() -> None:
    app = FakeServiceJkApp(_items(), current_idx=0)
    app.action_prev_patch()
    assert app.current_idx == 2
    assert app.perf_begins == ["prev"]


def test_j_inside_routine_panel_wraps_inside_panel() -> None:
    app = FakeServiceJkApp(_items(), current_idx=6)
    app.action_next_patch()
    assert app.current_idx == 3


def test_k_inside_routine_panel_wraps_inside_panel() -> None:
    app = FakeServiceJkApp(_items(), current_idx=3)
    app.action_prev_patch()
    assert app.current_idx == 6


def test_jk_stay_inside_sibling_source_panels() -> None:
    items, origins = _sourced_items()
    # user_routines slice is [2, 3, 4]; plugin is [5, 6]; builtin is [7, 8].
    app = FakeServiceJkApp(items, current_idx=4, routine_origins=origins)
    app.action_next_patch()
    assert app.current_idx == 2
    app = FakeServiceJkApp(items, current_idx=2, routine_origins=origins)
    app.action_prev_patch()
    assert app.current_idx == 4
    # Plugin panel wraps inside itself, including its job row.
    app = FakeServiceJkApp(items, current_idx=6, routine_origins=origins)
    app.action_next_patch()
    assert app.current_idx == 5
    app = FakeServiceJkApp(items, current_idx=5, routine_origins=origins)
    app.action_prev_patch()
    assert app.current_idx == 6
    # Builtin panel wraps inside itself.
    app = FakeServiceJkApp(items, current_idx=8, routine_origins=origins)
    app.action_next_patch()
    assert app.current_idx == 7
    # Service procs panel still wraps inside itself.
    app = FakeServiceJkApp(items, current_idx=1, routine_origins=origins)
    app.action_next_patch()
    assert app.current_idx == 0


def test_one_item_panel_leaves_idx_unchanged() -> None:
    items: list[AxeItem] = [ServiceProcItem(name="scheduler")]
    app = FakeServiceJkApp(items, current_idx=0)
    app.action_next_patch()
    assert app.current_idx == 0
    app.action_prev_patch()
    assert app.current_idx == 0


def test_empty_items_is_noop() -> None:
    app = FakeServiceJkApp([], current_idx=0)
    app.action_next_patch()
    assert app.current_idx == 0
    app.action_prev_patch()
    assert app.current_idx == 0


def test_stale_cursor_snaps_to_service_procs_edge() -> None:
    app = FakeServiceJkApp(_items(), current_idx=99)
    app.action_next_patch()
    assert app.current_idx == 0
    app = FakeServiceJkApp(_items(), current_idx=99)
    app.action_prev_patch()
    assert app.current_idx == 2


def test_jk_do_not_push_entry_jump_stack() -> None:
    app = FakeServiceJkApp(_items(), current_idx=1)
    app.action_next_patch()
    app.action_prev_patch()
    assert app._entry_jump_index_stack.get("services", []) == []


def test_missing_panel_index_is_noop() -> None:
    app = FakeServiceJkApp(_items(), current_idx=1)
    del app._axe_panel_index
    app.action_next_patch()
    assert app.current_idx == 1
    app.action_prev_patch()
    assert app.current_idx == 1
