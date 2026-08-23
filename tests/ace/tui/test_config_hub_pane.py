"""Lazy nested Config catalog coverage."""

from __future__ import annotations

import pytest
from textual.widgets import ContentSwitcher

from sase.ace.testing import AcePage, wait_for
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_center_session import AdminCenterSessionState
from sase.ace.tui.modals.config_hub_catalog import config_panel_tabs
from sase.ace.tui.modals.config_hub_pane import ConfigHubPane
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
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
        (98, "full"),
        (73, "compact"),
        (70, "micro"),
    ),
)
def test_numbered_config_strip_fits_each_layout_tier(width: int, tier: str) -> None:
    tabs = config_panel_tabs()
    compact_below, micro_below = (99, 73) if len(tabs) >= 7 else (86, 73)
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
        spec = hub._subtab_by_id["xprompts"]
        assert _caption_text(hub).plain == f"› {spec.description}"
        _assert_hub_caption(hub, "xprompts")


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
        before = _caption_text(hub).plain

        await pilot.press("0", "2")
        await pilot.pause()

        assert hub._active_subtab == "xprompts"
        assert "glossary" not in hub._panes
        assert calls == ["xprompts"]
        assert created["xprompts"][0].visibility[-1] is True
        assert _caption_text(hub).plain == before
        _assert_hub_caption(hub, "xprompts")


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
        _assert_hub_caption(hub, "glossary")


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
        modal = ConfigCenterModal(initial_tab="config")
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
