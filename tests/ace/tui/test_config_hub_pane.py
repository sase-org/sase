"""Lazy nested Config catalog coverage."""

from __future__ import annotations

import pytest
from textual.containers import Vertical
from textual.widgets import ContentSwitcher, Input, Static

from sase.ace.testing import AcePage, wait_for
from sase.ace.tui.keymaps import load_keymap_registry
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.config_hub_catalog import config_panel_tabs
from sase.ace.tui.modals.config_hub_pane import (
    ConfigHubPane,
    config_hub_strip_thresholds,
)
from sase.ace.tui.modals.config_hub_session import (
    ConfigHubEntry,
    validated_config_subtab,
)
from sase.ace.tui.modals.models_panel import LaunchPane, ModelsPanelResult
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from sase.feature_flags import override_flags
from tests._models_panel_helpers import make_alias_view, patch_alias_views
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


class _BusyHubChild(_HubChild):
    can_focus = True

    def __init__(self, subtab: str) -> None:
        super().__init__(subtab)
        self.deactivate_checks = 0
        self.close_checks = 0

    def can_deactivate(self) -> bool:
        self.deactivate_checks += 1
        return False

    def can_close(self) -> bool:
        self.close_checks += 1
        return False


class _DigitHubChild(_HubChild):
    BINDINGS = [("1", "record_digit(1)", "Record digit")]

    def __init__(self, subtab: str) -> None:
        super().__init__(subtab)
        self.digits: list[int] = []

    def action_record_digit(self, number: int) -> None:
        self.digits.append(number)


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


@pytest.mark.parametrize(
    ("width", "tier"),
    (
        (98, "full"),
        (73, "compact"),
        (70, "micro"),
    ),
)
def test_numbered_config_strip_fits_each_layout_tier(width: int, tier: str) -> None:
    tabs = config_panel_tabs()
    compact_below, micro_below = config_hub_strip_thresholds(len(tabs))
    strip = PanelTabStrip(
        tabs,
        "flags",
        show_numbers=True,
        uppercase_active=True,
        compact_below=compact_below,
        compact_separator=" │ ",
        micro_below=micro_below,
        micro_separator="│",
    )
    strip._tier = tier  # type: ignore[assignment]

    rendered = strip._build_content()

    assert strip._line_width == len(rendered.plain)
    assert strip._line_width <= width
    assert [
        rendered.plain[start:end].split(maxsplit=1)[0]
        for start, end in strip._tab_ranges.values()
    ] == [f"{number:02d}" for number in range(1, 8)]


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

        await pilot.press("0", "2")
        await pilot.pause()

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


async def test_launch_direct_entry_opens_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    state = AdminCenterSessionState()
    state.config_hub.active_subtab = "memory"

    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            session_state=state,
            config_entry=ConfigHubEntry(subtab="launch"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "launch" in hub._panes)

        assert calls == ["launch"]
        assert hub._active_subtab == "launch"
        assert state.config_hub.active_subtab == "launch"


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
        await wait_for(pilot, lambda: hub._active_subtab == "flags")
        assert calls == ["xprompts", "flags"]


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

        await pilot.press("0", "1")
        await wait_for(pilot, lambda: hub._active_subtab == "flags")
        assert modal._active_tab == "config"
        assert hub._pending_subtab_select is False

        await pilot.press("0", "4")
        await wait_for(pilot, lambda: hub._active_subtab == "memory")
        await pilot.press("0", "7")
        await wait_for(pilot, lambda: hub._active_subtab == "xprompts")

        assert calls == ["xprompts", "flags", "memory"]
        assert modal._session_state.config_hub.active_subtab == "xprompts"


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

        await pilot.press("f4", "6")
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
        await wait_for(pilot, lambda: hub._active_subtab == "flags")
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

        await pilot.press("0", "5")
        await pilot.pause()
        assert hub._active_subtab == "xprompts"
        assert tuple(hub._panes) == ("xprompts",)
        assert busy is not None
        assert busy.deactivate_checks == 1


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


async def test_launch_result_refreshes_app_indicators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    calls: list[bool] = []

    async with _HostApp().run_test() as pilot:

        def refresh_launch_indicators(
            *, provider_routing_changed: bool = False
        ) -> None:
            calls.append(provider_routing_changed)

        pilot.app._refresh_launch_indicators = refresh_launch_indicators  # type: ignore[attr-defined]
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)

        hub.on_launch_changed(
            ModelsPanelResult(changed=True, provider_routing_changed=True)
        )
        hub.on_launch_changed(ModelsPanelResult(changed=False))

    assert calls == [True]


async def test_embedded_launch_change_then_close_refreshes_indicators_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    calls: list[bool] = []
    close_calls: list[bool] = []

    async with _HostApp().run_test() as pilot:

        def refresh_launch_indicators(
            *, provider_routing_changed: bool = False
        ) -> None:
            calls.append(provider_routing_changed)

        pilot.app._refresh_launch_indicators = refresh_launch_indicators  # type: ignore[attr-defined]
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="launch"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "launch" in hub._panes)
        monkeypatch.setattr(
            hub,
            "_close_admin_center",
            lambda: close_calls.append(True),
        )
        launch = hub._panes["launch"]
        assert isinstance(launch, LaunchPane)
        await wait_for(pilot, lambda: "large" in launch._row_by_id)

        launch._mark_changed(provider_routing_changed=True)
        launch.action_close()
        await pilot.pause()

    assert calls == [True]
    assert close_calls == [True]


async def test_embedded_launch_unchanged_close_does_not_refresh_indicators(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_alias_views(monkeypatch, [make_alias_view("large", "role")])
    calls: list[bool] = []
    close_calls: list[bool] = []

    async with _HostApp().run_test() as pilot:
        pilot.app._refresh_launch_indicators = (  # type: ignore[attr-defined]
            lambda *, provider_routing_changed=False: calls.append(
                provider_routing_changed
            )
        )
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="launch"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "launch" in hub._panes)
        monkeypatch.setattr(
            hub,
            "_close_admin_center",
            lambda: close_calls.append(True),
        )
        launch = hub._panes["launch"]
        assert isinstance(launch, LaunchPane)
        await wait_for(pilot, lambda: "large" in launch._row_by_id)

        launch.action_close()
        await pilot.pause()

    assert calls == []
    assert close_calls == [True]


def test_config_hub_strip_thresholds_grow_for_seven_labels() -> None:
    compact_six, micro_six = config_hub_strip_thresholds(6)
    compact_seven, micro_seven = config_hub_strip_thresholds(7)
    assert compact_six == 86
    assert micro_six == 73
    assert compact_seven == 99
    assert micro_seven == 73


async def test_flags_resume_falls_back_when_rollout_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    state = AdminCenterSessionState()
    state.config_hub.active_subtab = "flags"
    with override_flags(admin_center_flags=False):
        async with _HostApp().run_test() as pilot:
            modal = ConfigCenterModal(initial_tab="config", session_state=state)
            pilot.app.push_screen(modal)
            await wait_for(pilot, lambda: modal._active_tab == "config")
            hub = modal.query_one("#config", ConfigHubPane)
            await wait_for(pilot, lambda: "xprompts" in hub._panes)

            assert calls == ["xprompts"]
            assert hub._active_subtab == "xprompts"
            assert "flags" not in hub._subtab_order
            assert validated_config_subtab("flags") is None


async def test_flags_off_prefix_keeps_six_child_numbering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    with override_flags(admin_center_flags=False):
        async with _HostApp().run_test() as pilot:
            modal = ConfigCenterModal(initial_tab="config")
            pilot.app.push_screen(modal)
            await wait_for(pilot, lambda: modal._active_tab == "config")
            hub = modal.query_one("#config", ConfigHubPane)
            await wait_for(pilot, lambda: "xprompts" in hub._panes)

            await pilot.press("0", "1")
            await wait_for(pilot, lambda: hub._active_subtab == "glossary")
            await pilot.press("0", "6")
            await wait_for(pilot, lambda: hub._active_subtab == "xprompts")
            await pilot.press("0", "7")
            await pilot.pause()
            assert hub._active_subtab == "xprompts"
