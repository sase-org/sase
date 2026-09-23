"""App-level Services panel behavior: order, highlight paths, clicks, focus."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from sase.ace.tui.actions.axe import AxeMixin
from sase.ace.tui.actions.axe_display import AxeDisplayMixin
from sase.ace.tui.actions.axe_display._loaders import AxeItemKey
from sase.ace.tui.actions.axe_display._panels import build_services_panel_index
from sase.ace.tui.actions.event_handlers import EventHandlersMixin
from sase.ace.tui.actions.navigation._basic import BasicNavigationMixin
from sase.ace.tui.actions.axe_config_actions._mixin import _PendingAxeSelection
from sase.ace.tui.models.fold_state import FoldStateManager
from sase.ace.tui.widgets.bgcmd_list import (
    AxeItem,
    BgCmdItem,
    BgCmdList,
    ChopItem,
    LumberjackItem,
    ServiceProcItem,
)


def _service_snapshot(*names: str) -> SimpleNamespace:
    return SimpleNamespace(
        procs=[SimpleNamespace(name=name) for name in names],
        host=SimpleNamespace(state="running"),
    )


class FakePanelsApp(AxeMixin, BasicNavigationMixin, AxeDisplayMixin):
    """Minimal app surface for Services panel unit tests."""

    def __init__(self) -> None:
        self.current_tab: Any = "services"
        self.current_idx = 0
        self.axe_running = True
        self._axe_cmds_hidden = False
        self._axe_lumberjack_names: list[str] = []
        self._axe_lumberjack_chop_names: dict[str, list[str]] = {}
        self._axe_lumberjack_idx = None
        self._bgcmd_slots: list[tuple[int, Any]] = []
        self._axe_items: list[AxeItem] = []
        self._axe_last_idx = 0
        self._axe_last_item_key: AxeItemKey | None = None
        self._axe_pending_selection: _PendingAxeSelection | None = None
        self._axe_current_view: Any = "axe"
        self._axe_chop_selection = None
        self._axe_service_selection = None
        self._axe_fold_manager = FoldStateManager()
        self._axe_lumberjack_statuses: dict[str, Any] = {}
        self._axe_lumberjack_metrics: dict[str, Any] = {}
        self._axe_lumberjack_log_tails: dict[str, str] = {}
        self._axe_bgcmd_details: dict[int, Any] = {}
        self._axe_chop_snapshots: dict[tuple[str, str], Any] = {}
        self._axe_lumberjack_snapshots: dict[str, Any] = {}
        self._axe_chop_run_offsets: dict[tuple[str, str], int] = {}
        self._service_status = None
        self._axe_panel_index = build_services_panel_index([])
        self._axe_painted_panel_key = "service_procs"

    def _refresh_axe_display(self) -> None:  # type: ignore[override]
        pass


class StubPanel:
    """Recording stand-in for a mounted ``BgCmdList`` panel."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, Any]] = []
        self.classes: set[str] = set()
        self.rendered_line_count = 0
        self._requested_width = 40
        self.styles = SimpleNamespace(height=None)
        self.titles: list[Any] = []
        self.focus_calls = 0

    def update_list(self, **kwargs: Any) -> None:
        self.calls.append(("update_list", kwargs.get("current_idx")))
        self.rendered_line_count = len(kwargs.get("items", []))

    def update_highlight(self, idx: int) -> None:
        self.calls.append(("update_highlight", idx))

    def clear_highlight(self) -> None:
        self.calls.append(("clear_highlight", None))

    def update_border_title(self, title: Any) -> None:
        self.calls.append(("update_border_title", None))
        self.titles.append(title)

    def add_class(self, name: str) -> None:
        self.calls.append(("add_class", name))
        self.classes.add(name)

    def remove_class(self, name: str) -> None:
        self.calls.append(("remove_class", name))
        self.classes.discard(name)

    def focus(self) -> None:
        self.focus_calls += 1


class FakeMountedApp(FakePanelsApp):
    """Fake with two stub panels mounted and queryable."""

    def __init__(self) -> None:
        super().__init__()
        self.panels = {
            "service_procs": StubPanel(),
            "scheduled_routines": StubPanel(),
        }
        self.focused: Any = None
        self._keymap_registry = SimpleNamespace(app=SimpleNamespace(add_axe_item="a"))

    def query_one(self, selector: str, *_args: Any, **_kwargs: Any) -> Any:
        if selector == "#service-procs-panel":
            return self.panels["service_procs"]
        if selector == "#scheduled-routines-panel":
            return self.panels["scheduled_routines"]
        if selector == "#bgcmd-list-container":
            return SimpleNamespace(size=SimpleNamespace(height=0, width=120))
        raise AssertionError(f"unexpected selector {selector!r}")


def _seed_items(app: FakePanelsApp) -> None:
    app._service_status = _service_snapshot("scheduler", "telegram")
    app._bgcmd_slots = [(1, SimpleNamespace(running=False))]
    app._axe_lumberjack_names = ["hooks"]
    app._axe_lumberjack_chop_names = {"hooks": ["fast"]}
    app._build_axe_items()


def test_build_orders_service_oneshots_routines() -> None:
    app = FakePanelsApp()
    _seed_items(app)
    assert [type(item).__name__ for item in app._axe_items] == [
        "ServiceProcItem",
        "ServiceProcItem",
        "BgCmdItem",
        "LumberjackItem",
        "ChopItem",
    ]


def test_build_order_without_service_status() -> None:
    app = FakePanelsApp()
    app._service_status = None
    app._bgcmd_slots = [(1, object())]
    app._axe_lumberjack_names = ["hooks"]
    app._axe_lumberjack_chop_names = {"hooks": ["fast"]}
    app._build_axe_items()
    # Routines always live in their own panel; the missing status no
    # longer changes the shape.
    assert [type(item).__name__ for item in app._axe_items] == [
        "BgCmdItem",
        "LumberjackItem",
        "ChopItem",
    ]


def test_hidden_oneshots_leave_panel_but_badge_title() -> None:
    app = FakeMountedApp()
    _seed_items(app)
    app._axe_cmds_hidden = True
    app._build_axe_items()
    assert all(not isinstance(i, BgCmdItem) for i in app._axe_items)
    titles = app._build_axe_panel_titles("service_procs")
    assert "+1 hidden" in titles["service_procs"].plain


def test_same_panel_highlight_never_rebuilds() -> None:
    app = FakeMountedApp()
    _seed_items(app)
    app.current_idx = 0
    app._axe_painted_panel_key = "service_procs"
    app._refresh_axe_panel_highlights()
    procs_calls = app.panels["service_procs"].calls
    assert ("update_highlight", 0) in procs_calls
    assert not [c for c in procs_calls if c[0] == "update_list"]
    assert app.panels["scheduled_routines"].calls == []
    assert app._axe_painted_panel_key == "service_procs"


def test_focus_crossing_swaps_highlight_chrome_and_titles() -> None:
    app = FakeMountedApp()
    _seed_items(app)
    app.current_idx = 0
    app._axe_painted_panel_key = "service_procs"
    app.panels["service_procs"].classes.add("-focused-panel")
    # j into the first routine row (global 3, local 0).
    app.current_idx = 3
    app._refresh_axe_panel_highlights()
    procs = app.panels["service_procs"]
    routines = app.panels["scheduled_routines"]
    assert ("clear_highlight", None) in procs.calls
    assert "-focused-panel" not in procs.classes
    assert ("update_highlight", 0) in routines.calls
    assert "-focused-panel" in routines.classes
    assert len(procs.titles) == 1 and len(routines.titles) == 1
    assert not [c for c in procs.calls if c[0] == "update_list"]
    assert not [c for c in routines.calls if c[0] == "update_list"]
    assert app._axe_painted_panel_key == "scheduled_routines"


def test_click_in_unfocused_panel_selects_global_row() -> None:
    app = FakeMountedApp()
    _seed_items(app)

    def _click(panel_key: str, local: int) -> None:
        EventHandlersMixin.on_bg_cmd_list_selection_changed(
            app, SimpleNamespace(index=local, panel_key=panel_key)
        )

    _click("scheduled_routines", 1)  # the chop row, global 4
    assert app.current_idx == 4
    _click("service_procs", 2)  # the oneshot row, global 2
    assert app.current_idx == 2


def test_panel_highlight_path_reads_no_disk() -> None:
    app = FakeMountedApp()
    _seed_items(app)
    app.current_idx = 0

    def _boom(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("panel highlight must not read from disk")

    with (
        patch(
            "sase.ace.tui.actions.axe_display._refresh_targeted.read_lumberjack_status",
            _boom,
        ),
        patch("sase.ace.tui.bgcmd.read_bgcmd_slots", side_effect=_boom),
        patch("sase.ace.tui.actions.axe_display._data.read_chop_run_index", _boom),
        patch("sase.axe.state.read_lumberjack_status", _boom),
    ):
        app._refresh_axe_panel_highlights()
        app.current_idx = 3
        app._refresh_axe_panel_highlights()
        app._build_axe_panel_titles("scheduled_routines")


def test_focus_follows_only_bgcmd_owned_focus() -> None:
    app = FakeMountedApp()
    _seed_items(app)
    app.current_idx = 0
    # Focus elsewhere: background refreshes must not steal it.
    app.focused = object()
    app._focus_axe_focused_panel()
    assert app.panels["service_procs"].focus_calls == 0
    # A BgCmdList owns focus: follow into the focused panel.
    app.focused = BgCmdList()
    app._focus_axe_focused_panel()
    assert app.panels["service_procs"].focus_calls == 1
    # Forced paths skip the ownership check.
    app.focused = object()
    app._focus_axe_focused_panel(force=True)
    assert app.panels["service_procs"].focus_calls == 2


def test_focus_blocked_by_hint_bar() -> None:
    app = FakeMountedApp()
    _seed_items(app)
    app.current_idx = 0
    app.focused = BgCmdList()
    app._hint_input_bar_active = lambda: True  # type: ignore[attr-defined]
    app._focus_axe_focused_panel()
    assert app.panels["service_procs"].focus_calls == 0
