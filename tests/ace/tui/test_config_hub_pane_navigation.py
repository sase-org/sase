"""Config hub keyboard routing and tab ownership coverage."""

from __future__ import annotations

import pytest
from textual.widgets import Input, Static

from sase.ace.testing import wait_for
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from tests.ace.tui._config_center_tabs_helpers import _HostApp
from tests.ace.tui._config_hub_pane_helpers import (
    _BusyHubChild,
    _DigitHubChild,
    _FilterChild,
    _HubChild,
    _assert_hub_caption,
    _caption_text,
    _patch_hub_children,
)


async def test_home_digits_stop_at_six(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.ace.tui._config_center_tabs_helpers import _patch_stub_panes

    _patch_stub_panes(monkeypatch)
    async with _HostApp().run_test(size=(120, 40)) as pilot:
        modal = ConfigCenterModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        await pilot.press("7")
        await pilot.pause()
        assert modal._active_tab is None

        await pilot.press("6")
        await wait_for(pilot, lambda: modal._active_tab == "updates")

        landing = modal.query_one("#admin-center-home-hint", Static)
        assert "1-6" in str(landing.render().plain)
        assert list(modal.query("#xprompts")) == []


async def test_filter_brackets_cycle_config_subtabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def create(_self: ConfigHubPane, subtab: str) -> _FilterChild:
        calls.append(subtab)
        return _FilterChild(subtab)

    monkeypatch.setattr(ConfigHubPane, "_create_pane", create)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)
        await wait_for(pilot, lambda: isinstance(pilot.app.focused, Input))

        await pilot.press("right_square_bracket")
        await wait_for(pilot, lambda: hub._active_subtab == "misc")
        assert calls == ["xprompts", "misc"]
        _assert_hub_caption(hub, "misc")


async def test_config_number_prefix_selects_alphabetic_subtabs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        await pilot.press("0", "2")
        await wait_for(pilot, lambda: hub._active_subtab == "flags")
        assert modal._active_tab == "config"
        assert hub._pending_subtab_select is False
        _assert_hub_caption(hub, "flags")

        await pilot.press("0", "4")
        await wait_for(pilot, lambda: hub._active_subtab == "memory")
        _assert_hub_caption(hub, "memory")
        await pilot.press("0", "6")
        await wait_for(pilot, lambda: hub._active_subtab == "xprompts")

        assert calls == ["xprompts", "flags", "memory"]
        assert modal._session_state.config_hub.active_subtab == "xprompts"
        _assert_hub_caption(hub, "xprompts")


async def test_config_prefix_repeats_out_of_range_and_non_digit_cancel(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        await pilot.press("0", "0", "3")
        await wait_for(pilot, lambda: hub._active_subtab == "launch")
        assert hub._pending_subtab_select is False

        await pilot.press("0", "8")
        await pilot.pause()
        assert hub._active_subtab == "launch"
        assert hub._pending_subtab_select is False

        await pilot.press("0", "q")
        await wait_for(pilot, lambda: len(pilot.app.screen_stack) == 1)
        assert hub._pending_subtab_select is False
        assert not isinstance(pilot.app.screen, ConfigCenterModal)


async def test_configured_config_prefix_selects_subtab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    registry = load_keymap_registry({"keymaps": {"config": {"select_subtab": "f4"}}})

    async with _HostApp().run_test() as pilot:
        pilot.app._keymap_registry = registry  # type: ignore[attr-defined]
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        await pilot.press("f4", "5")
        await wait_for(pilot, lambda: hub._active_subtab == "snippets")

        assert hub._pending_subtab_select is False


async def test_bare_child_digit_stays_local_until_config_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created: dict[str, _DigitHubChild] = {}

    def create(_self: ConfigHubPane, subtab: str) -> _DigitHubChild:
        child = _DigitHubChild(subtab)
        created[subtab] = child
        return child

    monkeypatch.setattr(ConfigHubPane, "_create_pane", create)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        await pilot.press("1")
        await pilot.pause()
        assert modal._active_tab == "config"
        assert hub._active_subtab == "xprompts"
        assert created["xprompts"].digits == [1]

        await pilot.press("0", "1")
        await wait_for(pilot, lambda: hub._active_subtab == "misc")
        assert created["xprompts"].digits == [1]


async def test_config_filter_keeps_prefix_digits_as_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def create(_self: ConfigHubPane, subtab: str) -> _FilterChild:
        return _FilterChild(subtab)

    monkeypatch.setattr(ConfigHubPane, "_create_pane", create)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)
        await wait_for(pilot, lambda: isinstance(pilot.app.focused, Input))

        input_widget = hub.query_one("#hub-filter", Input)
        await pilot.press("0", "1")

        assert input_widget.value == "01"
        assert hub._active_subtab == "xprompts"
        assert hub._pending_subtab_select is False
        _assert_hub_caption(hub, "xprompts")


async def test_relationship_children_own_tab_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        assert modal.check_action("next_center_tab", ()) is not False

        await hub._switch_to("memory")
        assert hub.child_owns_tab_keys() is True
        assert modal.check_action("next_center_tab", ()) is False
        assert modal.check_action("prev_center_tab", ()) is False


async def test_busy_child_blocks_config_subtab_switch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    busy: _BusyHubChild | None = None

    def create(_self: ConfigHubPane, subtab: str) -> _HubChild:
        nonlocal busy
        if subtab == "xprompts":
            busy = _BusyHubChild(subtab)
            return busy
        return _HubChild(subtab)

    monkeypatch.setattr(ConfigHubPane, "_create_pane", create)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)
        before = _caption_text(hub).plain

        await pilot.press("0", "5")
        await pilot.pause()
        assert hub._active_subtab == "xprompts"
        assert tuple(hub._panes) == ("xprompts",)
        assert busy is not None
        assert busy.deactivate_checks == 1
        assert _caption_text(hub).plain == before
        _assert_hub_caption(hub, "xprompts")


async def test_busy_config_child_blocks_top_level_switch_and_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    busy: _BusyHubChild | None = None

    def create(_self: ConfigHubPane, subtab: str) -> _BusyHubChild:
        nonlocal busy
        busy = _BusyHubChild(subtab)
        return busy

    monkeypatch.setattr(ConfigHubPane, "_create_pane", create)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        await wait_for(pilot, lambda: busy is not None)

        assert await modal._switch_to("logs") is False
        assert modal._active_tab == "config"
        assert "logs" not in modal._panes
        assert busy is not None
        assert busy.deactivate_checks == 1

        modal.action_close()
        await pilot.pause()
        assert modal.is_mounted
        assert modal._active_tab == "config"
        assert busy.close_checks == 1
