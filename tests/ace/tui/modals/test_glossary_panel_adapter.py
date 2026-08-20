"""Standalone adapter close/focus behavior for the Glossary modal host."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import OptionList, Static

from sase.ace.testing import wait_for
from sase.ace.tui.modals.catalog_pane_contract import CatalogPaneHost
from sase.ace.tui.modals.glossary_panel import GlossaryPanel
from sase.ace.tui.modals.glossary_pane import GlossaryPane
from tests.ace.tui.modals.glossary_panel_test_helpers import (
    glossary_entry,
    install_fixed_load,
    project_ref,
    project_snapshot,
)


class _AdapterApp(App[None]):
    def __init__(self, panel: GlossaryPanel) -> None:
        super().__init__()
        self.panel = panel

    def compose(self) -> ComposeResult:
        yield Static("host")

    def on_mount(self) -> None:
        self.push_screen(self.panel)


async def test_adapter_dismisses_on_escape(monkeypatch: pytest.MonkeyPatch) -> None:
    ref = project_ref("sase", "sase")
    install_fixed_load(
        monkeypatch,
        (ref,),
        {"sase": project_snapshot(ref, (glossary_entry(0, "Alpha"),))},
    )
    panel = GlossaryPanel()
    app = _AdapterApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: isinstance(app.screen, GlossaryPanel))
        await wait_for(pilot, lambda: not panel._loading)
        assert isinstance(panel, CatalogPaneHost)
        await pilot.press("escape")
        await wait_for(pilot, lambda: not isinstance(app.screen, GlossaryPanel))


async def test_adapter_focus_default_focuses_term_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = project_ref("sase", "sase")
    install_fixed_load(
        monkeypatch,
        (ref,),
        {"sase": project_snapshot(ref, (glossary_entry(0, "Alpha"),))},
    )
    panel = GlossaryPanel()
    app = _AdapterApp(panel)
    async with app.run_test(size=(120, 40)) as pilot:
        await wait_for(pilot, lambda: not panel._loading)
        pane = panel.pane
        assert isinstance(pane, GlossaryPane)
        term_list = pane.query_one("#glossary-panel-terms", OptionList)
        panel.focus_default()
        assert app.focused is term_list
        app.set_focus(None)
        panel.focus_default()
        assert app.focused is term_list
