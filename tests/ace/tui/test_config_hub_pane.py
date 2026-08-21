"""Lazy nested Config catalog coverage."""

from __future__ import annotations

import pytest
from textual.containers import Vertical
from textual.widgets import ContentSwitcher, Input, Static

from sase.ace.testing import AcePage, wait_for
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from tests.ace.tui._config_center_tabs_helpers import _HostApp


class _HubChild(Static):
    can_focus = True

    def __init__(self, subtab: str) -> None:
        super().__init__(f"hub {subtab}", id=subtab)
        self.subtab = subtab
        self.visibility: list[bool] = []
        self.focus_count = 0

    def on_center_tab_visibility_changed(self, active: bool) -> None:
        self.visibility.append(active)

    def focus_default(self) -> None:
        self.focus_count += 1
        self.focus()


class _ForwardingFilter(Input):
    def on_key(self, event: object) -> None:
        from sase.ace.tui.modals.config_hub_keys import handle_config_hub_bracket_key

        handle_config_hub_bracket_key(self, event)  # type: ignore[arg-type]


class _FilterChild(Vertical):
    def __init__(self, subtab: str) -> None:
        super().__init__(id=subtab)
        self.subtab = subtab

    def compose(self):  # type: ignore[no-untyped-def]
        yield _ForwardingFilter(id="hub-filter")

    def focus_default(self) -> None:
        self.query_one(Input).focus()


def _patch_hub_children(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[dict[str, list[_HubChild]], list[str]]:
    created: dict[str, list[_HubChild]] = {}
    calls: list[str] = []

    def create(_self: ConfigHubPane, subtab: str) -> _HubChild:
        calls.append(subtab)
        pane = _HubChild(subtab)
        created.setdefault(subtab, []).append(pane)
        return pane

    monkeypatch.setattr(ConfigHubPane, "_create_pane", create)
    return created, calls


async def test_opening_config_constructs_only_the_active_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_hub_children(monkeypatch)
    async with AcePage(initial_tab="agents") as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await page.wait_for(lambda _s: "xprompts" in hub._panes)

        assert calls == ["xprompts"]
        assert tuple(hub._panes) == ("xprompts",)
        assert created["xprompts"][0].focus_count >= 1
        assert hub.query_one("#config-hub-switcher", ContentSwitcher).current == (
            "xprompts"
        )
        assert hub.query_one("#config-hub-tabs", PanelTabStrip)._active_tab == (
            "xprompts"
        )


async def test_subtab_cycle_caches_children_and_does_not_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_hub_children(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        await hub._switch_to("snippets")
        await hub._switch_to("xprompts")

        assert calls == ["xprompts", "snippets"]
        assert hub._panes["xprompts"] is created["xprompts"][0]
        assert created["xprompts"][0].visibility[-3:] == [True, False, True]


async def test_failed_child_mount_leaves_previous_child_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_hub_children(monkeypatch)
    original = ConfigHubPane._create_pane

    def maybe_fail(self: ConfigHubPane, subtab: str) -> _HubChild:
        if subtab == "glossary":
            raise RuntimeError("boom")
        return original(self, subtab)

    monkeypatch.setattr(ConfigHubPane, "_create_pane", maybe_fail)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        opened = await hub._switch_to("glossary")

        assert opened is False
        assert hub._active_subtab == "xprompts"
        assert "glossary" not in hub._panes
        assert calls == ["xprompts"]
        assert created["xprompts"][0].visibility[-1] is True


async def test_direct_entry_opens_requested_child_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    state = AdminCenterSessionState()
    state.config_hub.active_subtab = "memory"
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            session_state=state,
            config_entry=ConfigHubEntry(subtab="glossary", term="Agent Hood"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "glossary" in hub._panes)

        assert calls == ["glossary"]
        assert hub._active_subtab == "glossary"
        assert state.config_hub.active_subtab == "glossary"
        assert hub._entry is not None
        assert hub._entry.term == "Agent Hood"


async def test_legacy_xprompts_resume_opens_config_hub(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="xprompts")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        assert calls == ["xprompts"]
        assert "xprompts" not in {spec.id for spec in modal._tab_specs}


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
        await wait_for(pilot, lambda: hub._active_subtab == "snippets")
        assert calls == ["xprompts", "snippets"]


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

        await hub._switch_to("glossary")
        assert hub.child_owns_tab_keys() is True
        assert modal.check_action("next_center_tab", ()) is False
        assert modal.check_action("prev_center_tab", ()) is False
