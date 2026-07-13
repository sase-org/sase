"""Tests for Admin Center tab ordering, hotkeys, and session memory."""

from __future__ import annotations

import pytest
from rich.text import Text
from textual.binding import Binding
from textual.widgets import ContentSwitcher, Static

from sase.ace.admin_center_tab import load_admin_center_tab, save_admin_center_tab
from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import (
    _PANEL_TABS,
    _TAB_COLORS,
    _TAB_DESCRIPTIONS,
    _TAB_LABELS,
    _TAB_ORDER,
    _TITLE_LABEL,
    _TITLE_TEXT,
    _TITLE_UNDERLINE,
    ConfigCenterModal,
)
from sase.ace.tui.widgets.panel_tab_strip import PanelTabStrip

from tests.ace.tui._plugins_browser_pane_helpers import (
    _catalog,
    _patch_catalog,
    _patch_other_panes,
)


def test_numbered_tab_strip_plain_text_and_click_ranges() -> None:
    strip = PanelTabStrip(_PANEL_TABS, "updates", show_numbers=True)
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


def test_tab_cycle_bindings_are_modal_priority() -> None:
    bindings = {
        binding.key: binding
        for binding in ConfigCenterModal.BINDINGS
        if isinstance(binding, Binding)
    }

    assert bindings["tab"].action == "next_center_tab"
    assert bindings["tab"].priority is True
    assert bindings["shift+tab"].action == "prev_center_tab"
    assert bindings["shift+tab"].priority is True


async def test_tab_hotkeys_wrap_without_switching_hidden_ace_tab(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage(initial_tab="agents") as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")

        await page.press("shift+tab")
        await page.wait_for(lambda _s: modal._active_tab == "xprompts")
        assert page.app.current_tab == "agents"

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "config")
        assert page.app.current_tab == "agents"


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
        assert (
            content.plain
            == "› Update SASE core and plugins with incoming commit previews"
        )
        assert str(content.style) == _TAB_COLORS["updates"]

        await page.press("7")
        await page.pause()
        assert modal._active_tab == "updates"
        assert switcher.current == "updates"
        content = description.content
        assert isinstance(content, Text)
        assert (
            content.plain
            == "› Update SASE core and plugins with incoming commit previews"
        )
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

        await page.press(str(_TAB_ORDER.index("updates") + 1))
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
        # The in-memory field is mirrored to disk off-thread.
        await page.wait_for(lambda _s: load_admin_center_tab(_TAB_ORDER) == "tasks")

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
        await page.wait_for(lambda _s: load_admin_center_tab(_TAB_ORDER) == "projects")

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


async def test_open_config_center_seeds_initial_tab_from_persisted_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persisted tab seeds the app field and the plain ``#`` reopen target."""
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())
    assert save_admin_center_tab("updates", _TAB_ORDER) is True

    async with AcePage() as page:
        assert page.app._admin_center_tab == "updates"

        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        assert modal._active_tab == "updates"


async def test_active_tab_persists_across_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Switching tabs then restarting the TUI reopens on the persisted tab."""
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)

        await page.press("4")
        await page.wait_for(lambda _s: modal._active_tab == "tasks")
        await page.wait_for(lambda _s: load_admin_center_tab(_TAB_ORDER) == "tasks")

        await page.press("escape")
        await page.expect_no_modal()

    # Fresh app/session reusing the same isolated SASE_HOME.
    async with AcePage() as page:
        assert page.app._admin_center_tab == "tasks"
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        reopened = page.app.screen
        assert isinstance(reopened, ConfigCenterModal)
        assert reopened._active_tab == "tasks"


async def test_fast_path_tab_persists_across_fresh_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A fast-path open (Logs) persists so a fresh ``#`` reopens on it."""
    _patch_other_panes(monkeypatch)
    _patch_catalog(monkeypatch, catalog=_catalog())

    async with AcePage() as page:
        page.app.action_open_log_panel()
        await page.expect_modal("ConfigCenterModal")
        modal = page.app.screen
        assert isinstance(modal, ConfigCenterModal)
        assert modal._active_tab == "logs"
        await page.wait_for(lambda _s: load_admin_center_tab(_TAB_ORDER) == "logs")

        await page.press("escape")
        await page.expect_no_modal()

    # Fresh app/session reusing the same isolated SASE_HOME.
    async with AcePage() as page:
        assert page.app._admin_center_tab == "logs"
        await page.press("number_sign")
        await page.expect_modal("ConfigCenterModal")
        reopened = page.app.screen
        assert isinstance(reopened, ConfigCenterModal)
        assert reopened._active_tab == "logs"
