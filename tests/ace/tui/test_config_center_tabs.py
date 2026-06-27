"""Tests for Admin Center tab ordering, hotkeys, and session memory."""

from __future__ import annotations

import pytest
from rich.text import Text
from textual.widgets import ContentSwitcher, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import (
    _ConfigCenterTabStrip,
    _TAB_COLORS,
    _TAB_DESCRIPTIONS,
    _TAB_LABELS,
    _TAB_ORDER,
    _TITLE_LABEL,
    _TITLE_TEXT,
    _TITLE_UNDERLINE,
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


def test_tab_descriptions_cover_tabs_and_use_accent_colors() -> None:
    assert tuple(tab for tab, _label in _TAB_LABELS) == _TAB_ORDER
    assert tuple(_TAB_DESCRIPTIONS) == _TAB_ORDER
    assert tuple(_TAB_COLORS) == _TAB_ORDER


def test_title_has_no_leading_icon_and_underline_matches() -> None:
    assert _TITLE_TEXT == "SASE Admin Center"
    assert _TITLE_TEXT == _TITLE_LABEL
    assert not _TITLE_TEXT.startswith("⎈")
    assert len(_TITLE_UNDERLINE) == len(_TITLE_TEXT)


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
        await page.wait_for(
            lambda _s: bool(modal.query("#config-center-tab-description"))
        )
        description = modal.query_one("#config-center-tab-description", Static)
        content = description.content
        assert isinstance(content, Text)
        assert content.plain == "› Edit layered SASE settings with live preview"
        assert str(content.style) == _TAB_COLORS["config"]

        await page.press("3")
        await page.wait_for(lambda _s: modal._active_tab == "projects")
        switcher = modal.query_one("#config-center-switcher", ContentSwitcher)
        assert switcher.current == "projects"
        content = description.content
        assert isinstance(content, Text)
        assert content.plain == "› Manage project lifecycle states and claims"
        assert str(content.style) == _TAB_COLORS["projects"]

        await page.press("4")
        await page.wait_for(lambda _s: modal._active_tab == "tasks")
        assert switcher.current == "tasks"
        content = description.content
        assert isinstance(content, Text)
        assert content.plain == "› Monitor background tasks and live output"
        assert str(content.style) == _TAB_COLORS["tasks"]

        await page.press("5")
        await page.wait_for(lambda _s: modal._active_tab == "updates")
        assert switcher.current == "updates"
        content = description.content
        assert isinstance(content, Text)
        assert content.plain == "› Update SASE core and installed plugins"
        assert str(content.style) == _TAB_COLORS["updates"]

        await page.press("7")
        await page.pause()
        assert modal._active_tab == "updates"
        assert switcher.current == "updates"
        content = description.content
        assert isinstance(content, Text)
        assert content.plain == "› Update SASE core and installed plugins"
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
