"""Lazy nested Config catalog coverage."""

from __future__ import annotations

import pytest
from textual.widgets import ContentSwitcher

from sase.ace.testing import AcePage, wait_for
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.config_hub_catalog import config_panel_tabs
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import CONFIG_SUBTAB_ORDER, ConfigHubEntry
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip
from tests.ace.tui._config_center_tabs_helpers import _HostApp
from tests.ace.tui._config_hub_pane_helpers import (
    _HubChild,
    _assert_hub_caption,
    _caption_text,
    _caption_widget,
    _patch_hub_children,
)


@pytest.mark.parametrize(
    ("width", "tier"),
    (
        (97, "full"),
        (73, "compact"),
        (70, "micro"),
    ),
)
def test_numbered_config_strip_fits_each_layout_tier(width: int, tier: str) -> None:
    tabs = config_panel_tabs()
    compact_below, micro_below = (98, 73) if len(tabs) >= 6 else (85, 73)
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
    ] == [f"{number:02d}" for number in range(1, 7)]


async def test_opening_config_constructs_only_the_active_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_hub_children(monkeypatch)
    async with AcePage(initial_tab="agents") as page:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="xprompts"),
        )
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
        spec = hub._subtab_by_id["xprompts"]
        assert _caption_text(hub).plain == f"› {spec.description}"
        _assert_hub_caption(hub, "xprompts")


async def test_subtab_cycle_caches_children_and_does_not_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_hub_children(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="xprompts"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)

        await hub._switch_to("snippets")
        _assert_hub_caption(hub, "snippets")
        await hub._switch_to("xprompts")

        assert calls == ["xprompts", "snippets"]
        assert hub._panes["xprompts"] is created["xprompts"][0]
        assert created["xprompts"][0].visibility[-3:] == [True, False, True]
        _assert_hub_caption(hub, "xprompts")


async def test_failed_child_mount_leaves_previous_child_visible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created, calls = _patch_hub_children(monkeypatch)
    original = ConfigHubPane._create_pane

    def maybe_fail(self: ConfigHubPane, subtab: str) -> _HubChild:
        if subtab == "launch":
            raise RuntimeError("boom")
        return original(self, subtab)

    monkeypatch.setattr(ConfigHubPane, "_create_pane", maybe_fail)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="xprompts"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "xprompts" in hub._panes)
        before = _caption_text(hub).plain

        await pilot.press("0", "3")
        await pilot.pause()

        assert hub._active_subtab == "xprompts"
        assert "launch" not in hub._panes
        assert calls == ["xprompts"]
        assert created["xprompts"][0].visibility[-1] is True
        assert _caption_text(hub).plain == before
        _assert_hub_caption(hub, "xprompts")


async def test_direct_entry_opens_requested_child_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    state = AdminCenterSessionState()
    state.config_hub.active_subtab = "xprompts"
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(
            initial_tab="config",
            session_state=state,
            config_entry=ConfigHubEntry(subtab="memory", note="glossary:agent-hood"),
        )
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "memory" in hub._panes)

        assert calls == ["memory"]
        assert hub._active_subtab == "memory"
        assert state.config_hub.active_subtab == "memory"
        assert hub._entry is not None
        assert hub._entry.note == "glossary:agent-hood"
        _assert_hub_caption(hub, "memory")


async def test_legacy_xprompts_resume_opens_config_hub_on_default_subtab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="xprompts")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "misc" in hub._panes)

        assert calls == ["misc"]
        assert "xprompts" not in {spec.id for spec in modal._tab_specs}


async def test_remembered_subtab_shows_matching_caption(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    state = AdminCenterSessionState()
    state.config_hub.active_subtab = "memory"
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config", session_state=state)
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "memory" in hub._panes)

        assert calls == ["memory"]
        assert hub._active_subtab == "memory"
        _assert_hub_caption(hub, "memory")


async def test_resize_switches_caption_variant_without_reloading_children(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    async with AcePage(initial_tab="agents", size=(120, 40)) as page:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="xprompts"),
        )
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await page.wait_for(lambda _s: "xprompts" in hub._panes)

        spec = hub._subtab_by_id["xprompts"]
        child = hub._panes["xprompts"]
        await page.wait_for(lambda _s: page.app.focused is child)
        assert _caption_text(hub).plain == f"› {spec.description}"
        before = list(calls)
        panes = dict(hub._panes)

        await page._pilot.resize_terminal(70, 32)  # noqa: SLF001
        await page.wait_for(
            lambda _s: _caption_text(hub).plain == f"› {spec.compact_description}"
        )
        assert calls == before
        assert hub._panes == panes
        assert page.app.focused is child
        assert page.app.focused is not _caption_widget(hub)

        await page._pilot.resize_terminal(120, 40)  # noqa: SLF001
        await page.wait_for(
            lambda _s: _caption_text(hub).plain == f"› {spec.description}"
        )
        assert calls == before
        assert hub._panes == panes
        assert page.app.focused is child
        assert page.app.focused is not _caption_widget(hub)


async def test_config_lands_on_the_first_catalog_subtab_with_a_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _created, calls = _patch_hub_children(monkeypatch)
    async with _HostApp().run_test() as pilot:
        modal = ConfigCenterModal(initial_tab="config")
        pilot.app.push_screen(modal)
        await wait_for(pilot, lambda: modal._active_tab == "config")
        hub = modal.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: CONFIG_SUBTAB_ORDER[0] in hub._panes)

        assert hub._active_subtab == CONFIG_SUBTAB_ORDER[0]
        assert calls == [CONFIG_SUBTAB_ORDER[0]]


async def test_config_subtab_visited_earlier_this_session_is_where_reopen_lands(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_hub_children(monkeypatch)
    state = AdminCenterSessionState()
    async with _HostApp().run_test() as pilot:
        first = ConfigCenterModal(initial_tab="config", session_state=state)
        pilot.app.push_screen(first)
        await wait_for(pilot, lambda: first._active_tab == "config")
        hub = first.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: CONFIG_SUBTAB_ORDER[0] in hub._panes)

        await hub._switch_to("memory")
        assert state.config_hub.active_subtab == "memory"

        first.action_close()
        await wait_for(pilot, lambda: len(pilot.app.screen_stack) == 1)

        second = ConfigCenterModal(initial_tab="config", session_state=state)
        pilot.app.push_screen(second)
        await wait_for(pilot, lambda: second._active_tab == "config")
        hub2 = second.query_one("#config", ConfigHubPane)
        await wait_for(pilot, lambda: "memory" in hub2._panes)

        assert hub2._active_subtab == "memory"
