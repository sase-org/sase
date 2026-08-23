"""Coverage for the Admin Center's optional ``consume_priority_tab()`` hand-off."""

from __future__ import annotations

import pytest

from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from tests.ace.tui._config_center_tabs_helpers import (
    _HostApp,
    _patch_stub_panes,
    _patch_tab_consuming_pane,
)


async def test_tab_switches_when_the_active_pane_does_not_consume_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _patch_tab_consuming_pane(monkeypatch)
    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal(initial_tab="procs")
        pilot.app.push_screen(modal)
        await pilot.pause()

        pane = created["procs"][0]
        pane.should_consume = False

        await pilot.press("tab")
        await pilot.pause()
        assert pane.consume_calls == 1
        assert modal._active_tab != "procs"


async def test_tab_is_swallowed_when_the_active_pane_consumes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _patch_tab_consuming_pane(monkeypatch)
    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal(initial_tab="procs")
        pilot.app.push_screen(modal)
        await pilot.pause()

        pane = created["procs"][0]
        pane.should_consume = True

        await pilot.press("tab")
        await pilot.pause()
        assert pane.consume_calls == 1
        assert modal._active_tab == "procs"


async def test_panes_without_the_hook_are_unaffected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created = _patch_stub_panes(monkeypatch)[0]
    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal(initial_tab="procs")
        pilot.app.push_screen(modal)
        await pilot.pause()
        assert not hasattr(created["procs"][0], "consume_priority_tab")

        await pilot.press("tab")
        await pilot.pause()
        assert modal._active_tab != "procs"
