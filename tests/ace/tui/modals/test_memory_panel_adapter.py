"""Thin MemoryPanel modal adapter: close, focus, and constructor seeds."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static
from textual.worker import WorkerState

from sase.ace.testing import wait_for
from sase.ace.tui.modals.catalog_pane_host import CatalogPaneHost
from sase.ace.tui.modals.memory_pane import MemoryPane
from sase.ace.tui.modals.memory_panel import MemoryPanel
from sase.ace.tui.modals.memory_panel_load import MemoryPanelInitialLoad
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load,
    memory_note,
    scope_ref,
    scope_snapshot,
)


class _AdapterApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, panel: MemoryPanel) -> None:
        super().__init__()
        self.panel = panel

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.panel)


async def test_adapter_dismisses_on_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    )
    panel = MemoryPanel()
    app = _AdapterApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, MemoryPanel))
        await wait_for(pilot, lambda: not panel.pane._loading)
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, MemoryPanel))


async def test_adapter_forwards_focus_default(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    )
    panel = MemoryPanel()
    app = _AdapterApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel.pane._loading)
        filter_input = panel.pane._filter_input()
        filter_input.display = True
        filter_input.focus()
        await wait_for(pilot, lambda: filter_input.has_focus)
        panel.on_center_tab_visibility_changed(False)
        panel.focus_default()
        assert filter_input.has_focus
        panel.on_center_tab_visibility_changed(True)
        await wait_for(pilot, lambda: panel.pane._note_list().has_focus)


async def test_dismissed_adapter_ignores_late_load_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_fixed_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, (memory_note("alpha"),))}
    )
    panel = MemoryPanel()
    app = _AdapterApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel.pane._loading)
        original = panel.pane._current_note
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, MemoryPanel))
        await wait_for(pilot, lambda: panel.pane._closed)
        late = MemoryPanelInitialLoad(
            ring=(ref,),
            scope_index=0,
            snapshot=scope_snapshot(ref, (memory_note("other"),)),
        )
        event = SimpleNamespace(
            state=WorkerState.SUCCESS,
            worker=SimpleNamespace(result=late),
        )
        panel.pane._on_initial_load_state_changed(event)  # type: ignore[arg-type]
        assert panel.pane._current_note == original
        assert panel.pane._loading is False


def test_adapter_implements_host_contract_and_keeps_constructor_seeds() -> None:
    panel = MemoryPanel(
        launch_workspace="/ws/sase",
        initial_note="sase/memory/sase_beads.md",
    )
    assert isinstance(panel, CatalogPaneHost)
    assert isinstance(panel.pane, MemoryPane)
    assert callable(panel.close_catalog_pane)
    assert panel._launch_workspace == "/ws/sase"
    assert panel._initial_note == "sase/memory/sase_beads.md"
