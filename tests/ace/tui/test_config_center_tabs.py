"""Tests for Admin Center tab ordering, hotkeys, and session memory."""

from __future__ import annotations

import pytest
from textual.widgets import ContentSwitcher

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import (
    _ConfigCenterTabStrip,
    _TAB_LABELS,
    ConfigCenterModal,
)

from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)


def test_numbered_tab_strip_plain_text_and_click_ranges() -> None:
    strip = _ConfigCenterTabStrip("updates")
    text = strip._build_content()
    plain = text.plain

    expected_cells = [
        "1 Config",
        "2 Logs",
        "3 Projects",
        "4 Tasks",
        "5 Updates",
        "6 XPrompts",
    ]
    assert [plain.index(cell) for cell in expected_cells] == sorted(
        plain.index(cell) for cell in expected_cells
    )

    for index, (tab, label) in enumerate(_TAB_LABELS, start=1):
        start, end = strip._tab_ranges[tab]
        assert plain[start:end].strip() == f"{index} {label}"


async def test_digit_hotkeys_jump_tabs_and_swallow_out_of_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    calls: list[str] = []

    async with AcePage() as page:
        monkeypatch.setattr(
            page.app,
            "action_load_saved_query_7",
            lambda: calls.append("7"),
        )
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")

        await page.press("3")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert switcher.current == "projects"

        await page.press("4")
        await page.wait_for(lambda _s: modal._active_tab == "tasks")
        assert switcher.current == "tasks"

        await page.press("5")
        await page.wait_for(lambda _s: modal._active_tab == "updates")
        assert switcher.current == "updates"

        await page.press("7")
        await page.pause()
        assert modal._active_tab == "updates"
        assert switcher.current == "updates"
        assert calls == []


async def test_hash_digit_composition_opens_numbered_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("5")
        await page.wait_for(lambda _s: modal._active_tab == "updates")


async def test_admin_center_remembers_active_tab_across_escape_and_q(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        first = page.app.screen
        assert isinstance(first, ConfigCenterModal)

        await page.press("4")
        await page.wait_for(lambda _s: first._active_tab == "tasks")
        assert page.app._admin_center_tab == "tasks"

        await page.press("escape")
        await page.expect_no_modal()

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        second = page.app.screen
        assert isinstance(second, ConfigCenterModal)
        assert second._active_tab == "tasks"

        await page.press("3")
        await page.wait_for(lambda _s: second._active_tab == "projects")
        assert page.app._admin_center_tab == "projects"

        await page.press("q")
        await page.expect_no_modal()

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        third = page.app.screen
        assert isinstance(third, ConfigCenterModal)
        assert third._active_tab == "projects"


async def test_fast_path_open_updates_plain_hash_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        page.app.action_open_log_panel()
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        assert modal._active_tab == "logs"
        await page.wait_for(lambda _s: page.app._admin_center_tab == "logs")

        await page.press("escape")
        await page.expect_no_modal()

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        reopened = page.app.screen
        assert isinstance(reopened, ConfigCenterModal)
        assert reopened._active_tab == "logs"
