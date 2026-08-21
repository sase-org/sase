"""Admin Center regressions for Glossary/Memory prefixed links vs Snippets digits."""

from __future__ import annotations

import pytest

from sase.ace.testing import wait_for
from sase.ace.tui.modals.config_center_modal import CenterTab, ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.glossary_pane import GlossaryPane
from sase.ace.tui.modals.memory_pane import MemoryPane
from sase.ace.tui.modals.snippets_panel import SnippetsPane
from sase.memory.notes import MemoryNote
from tests.ace.tui._config_center_tabs_helpers import _HostApp, _StubPane
from tests.ace.tui.modals.glossary_panel_test_helpers import (
    glossary_entry,
    install_fixed_load as install_glossary_load,
    project_ref as glossary_project_ref,
    project_snapshot as glossary_project_snapshot,
)
from tests.ace.tui.modals.memory_panel_test_helpers import (
    install_fixed_load as install_memory_load,
    memory_note,
    scope_ref,
    scope_snapshot,
)
from tests.ace.tui.modals.snippets_panel_test_helpers import (
    install_fixed_load as install_snippets_load,
    project_ref as snippets_project_ref,
    project_snapshot as snippets_project_snapshot,
    snippet_entry,
)


def _linked_notes() -> tuple[MemoryNote, ...]:
    return (
        memory_note("always", note_type="short", description="Always loaded."),
        memory_note("hub", description="Hub."),
        memory_note("both", parent="sase/memory/hub.md", description="Has a child."),
        memory_note("grand", parent="sase/memory/both.md", description="Grandchild."),
        memory_note("child", parent="sase/memory/hub.md", description="Leaf child."),
        memory_note("zeta", description="Root with no children."),
    )


def _keep_real_config_stub_other_tabs(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[CenterTab, _StubPane]:
    original = ConfigCenterModal._create_pane
    created: dict[CenterTab, _StubPane] = {}

    def create(self: ConfigCenterModal, tab: CenterTab) -> object:
        if tab == "config":
            return original(self, tab)
        pane = _StubPane(tab)
        created[tab] = pane
        return pane

    monkeypatch.setattr(ConfigCenterModal, "_create_pane", create)
    return created


async def test_embedded_glossary_bare_digit_selects_admin_tab_prefixed_follows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = glossary_project_ref("sase", "sase")
    entries = (
        glossary_entry(0, "Alpha", definition="Alpha mentions Beta and Gamma."),
        glossary_entry(1, "Beta"),
        glossary_entry(2, "Gamma"),
    )
    snapshot = glossary_project_snapshot(ref, entries, scanning=True)
    install_glossary_load(monkeypatch, (ref,), {"sase": snapshot})
    _keep_real_config_stub_other_tabs(monkeypatch)

    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="glossary", term="Alpha"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "glossary" in hub._panes)
        pane = hub.query_one("#glossary", GlossaryPane)
        await wait_for(
            pilot, lambda: not pane._loading and pane._current_term == "Alpha"
        )

        await pilot.press("2")
        await wait_for(pilot, lambda: modal._active_tab == "logs")
        assert pane._current_term == "Alpha"
        assert pane._trail == []

        await pilot.press("1")
        await wait_for(pilot, lambda: modal._active_tab == "config")
        assert hub._active_subtab == "glossary"

        await pilot.press("0", "3")
        await wait_for(pilot, lambda: hub._active_subtab == "launch")
        assert modal._active_tab == "config"
        assert pane._current_term == "Alpha"
        assert pane._trail == []

        await pilot.press("0", "2")
        await wait_for(pilot, lambda: hub._active_subtab == "glossary")

        await pilot.press(".", "1")
        await wait_for(pilot, lambda: pane._current_term == "Beta")
        assert modal._active_tab == "config"
        assert hub._active_subtab == "glossary"
        assert pane._trail == ["Alpha"]


async def test_embedded_memory_bare_digit_selects_admin_tab_prefixed_follows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = scope_ref("sase", "sase")
    install_memory_load(
        monkeypatch, (ref,), {"sase": scope_snapshot(ref, _linked_notes())}
    )
    _keep_real_config_stub_other_tabs(monkeypatch)

    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="memory", note="sase/memory/hub.md"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "memory" in hub._panes)
        pane = hub.query_one("#memory", MemoryPane)
        await wait_for(
            pilot,
            lambda: not pane._loading and pane._current_note == "sase/memory/hub.md",
        )

        await pilot.press("2")
        await wait_for(pilot, lambda: modal._active_tab == "logs")
        assert pane._current_note == "sase/memory/hub.md"
        assert pane._trail == []

        await pilot.press("1")
        await wait_for(pilot, lambda: modal._active_tab == "config")
        assert hub._active_subtab == "memory"

        await pilot.press("0", "3")
        await wait_for(pilot, lambda: hub._active_subtab == "launch")
        assert modal._active_tab == "config"
        assert pane._current_note == "sase/memory/hub.md"
        assert pane._trail == []

        await pilot.press("0", "4")
        await wait_for(pilot, lambda: hub._active_subtab == "memory")

        await pilot.press(".", "1")
        await wait_for(pilot, lambda: pane._current_note == "sase/memory/both.md")
        assert modal._active_tab == "config"
        assert hub._active_subtab == "memory"
        assert pane._trail == ["sase/memory/hub.md"]


async def test_embedded_snippets_bare_digit_still_follows_locally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ref = snippets_project_ref("sase", "sase")
    entries = (
        snippet_entry("alpha", outbound=("beta", "gamma"), inbound=("delta",)),
        snippet_entry("beta"),
        snippet_entry("gamma"),
        snippet_entry("delta"),
    )
    install_snippets_load(
        monkeypatch, (ref,), {"sase": snippets_project_snapshot(ref, entries)}
    )
    _keep_real_config_stub_other_tabs(monkeypatch)

    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="snippets", trigger="alpha"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "snippets" in hub._panes)
        pane = hub.query_one("#snippets", SnippetsPane)
        await wait_for(
            pilot, lambda: not pane._loading and pane._current_trigger == "alpha"
        )

        await pilot.press("2")
        await wait_for(pilot, lambda: pane._current_trigger == "gamma")
        assert modal._active_tab == "config"
        assert hub._active_subtab == "snippets"
        assert pane._trail == ["alpha"]
