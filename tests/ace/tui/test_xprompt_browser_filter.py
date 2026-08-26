"""Browse-first slash-filter coverage for the Config XPrompts child.

The pane opens on the row list with the filter removed from layout. ``/``
reveals a live editor; Enter and Escape keep the applied query and return
focus to the list. Escape is layered: jump cancellation, then filter
dismissal, then Admin Center close.
"""

from __future__ import annotations

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.config_hub_session import ConfigHubEntry
from sase.ace.tui.modals.xprompt_browser_filter_input import BrowserFilterInput
from sase.ace.tui.modals.xprompt_browser_pane import XPromptBrowserPane

from tests.ace.tui.test_xprompt_browser_jump import (
    _highlighted_name,
    _three_item_prompts,
)
from tests.ace.tui.test_xprompt_browser_load_keymap import (
    _hint_text,
    _md_xprompt,
    _open_filter,
    _open_xprompts_tab,
    _patch_panes,
)


async def test_xprompts_open_browse_first_with_hidden_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)
        option_list = pane.query_one("#browser-list", OptionList)

        assert not filter_input.display
        assert option_list.has_focus
        assert _highlighted_name(pane) == "cfg"
        assert "/: filter" in _hint_text(pane)
        assert "Esc: close" in _hint_text(pane)


async def test_slash_reveals_filter_without_changing_selection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        option_list = pane.query_one("#browser-list", OptionList)
        await page.press("j")
        await page.wait_for(lambda _s: _highlighted_name(pane) == "note")

        filter_input = await _open_filter(page, pane)

        assert filter_input.display
        assert filter_input.has_focus
        assert not option_list.has_focus
        assert _highlighted_name(pane) == "note"
        assert filter_input.value == ""
        assert "enter/Esc: done" in _hint_text(pane)
        assert "Esc: close" not in _hint_text(pane)


async def test_live_filter_updates_rows_preview_bookmark_and_jump_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        filter_input = await _open_filter(page, pane)

        await page.press("n")
        await page.wait_for(lambda _s: filter_input.value == "n")

        assert _highlighted_name(pane) == "note"
        assert pane._bookmark.identity == "note"
        meta = str(pane.query_one("#browser-meta", Static).render())
        assert "Source: n.md" in meta
        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == []


async def test_enter_and_escape_keep_query_and_restore_list_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        option_list = pane.query_one("#browser-list", OptionList)
        filter_input = await _open_filter(page, pane)

        await page.press("n")
        await page.wait_for(lambda _s: filter_input.value == "n")
        await page.press("enter")
        await page.wait_for(
            lambda _s: not filter_input.display and option_list.has_focus
        )

        assert filter_input.value == "n"
        assert _highlighted_name(pane) == "note"
        await page.expect_modal("ConfigCenterModal")

        filter_input = await _open_filter(page, pane)
        assert filter_input.value == "n"
        await page.press("escape")
        await page.wait_for(
            lambda _s: not filter_input.display and option_list.has_focus
        )

        assert filter_input.value == "n"
        assert _highlighted_name(pane) == "note"
        await page.expect_modal("ConfigCenterModal")

        await page.press("escape")
        await page.wait_for(
            lambda _s: not isinstance(page.app.screen, ConfigCenterModal)
        )
        assert modal not in page.app.screen_stack


async def test_cached_reactivation_restores_open_filter_or_list(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        option_list = pane.query_one("#browser-list", OptionList)
        filter_input = await _open_filter(page, pane)
        await page.press("n")
        await page.wait_for(lambda _s: filter_input.value == "n")

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        await page.press("shift+tab")
        await page.wait_for(lambda _s: modal._active_tab == "config")
        await page.wait_for(lambda _s: filter_input.display and filter_input.has_focus)
        assert filter_input.value == "n"

        await page.press("escape")
        await page.wait_for(
            lambda _s: not filter_input.display and option_list.has_focus
        )

        await page.press("tab")
        await page.wait_for(lambda _s: modal._active_tab == "logs")
        await page.press("shift+tab")
        await page.wait_for(lambda _s: modal._active_tab == "config")
        await page.wait_for(lambda _s: option_list.has_focus)
        assert not filter_input.display
        assert filter_input.value == "n"


async def test_no_match_filter_clears_preview_and_stays_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prompts = {"note": _md_xprompt("note", "Body.", source_path="n.md")}
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, prompts)
        option_list = pane.query_one("#browser-list", OptionList)
        filter_input = await _open_filter(page, pane)

        await page.press("z", "z", "z")
        await page.wait_for(lambda _s: filter_input.value == "zzz")

        assert _highlighted_name(pane) is None
        assert str(pane.query_one("#browser-preview", Static).render()) == ""
        assert str(pane.query_one("#browser-meta", Static).render()) == ""

        await page.press("enter")
        await page.wait_for(
            lambda _s: not filter_input.display and option_list.has_focus
        )
        assert filter_input.value == "zzz"
        assert _highlighted_name(pane) is None


async def test_empty_catalog_filter_and_list_escape_are_safe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch, {})
    async with AcePage() as page:
        modal = ConfigCenterModal(
            initial_tab="config",
            config_entry=ConfigHubEntry(subtab="xprompts"),
        )
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#xprompts")))
        pane = modal.query_one("#xprompts", XPromptBrowserPane)
        option_list = pane.query_one("#browser-list", OptionList)
        await page.wait_for(lambda _s: option_list.has_focus)

        filter_input = await _open_filter(page, pane)
        await page.press("n")
        await page.wait_for(lambda _s: filter_input.value == "n")
        assert _highlighted_name(pane) is None

        await page.press("escape")
        await page.wait_for(
            lambda _s: not filter_input.display and option_list.has_focus
        )
        await page.expect_modal("ConfigCenterModal")

        await page.press("escape")
        await page.wait_for(
            lambda _s: not isinstance(page.app.screen, ConfigCenterModal)
        )
        assert modal not in page.app.screen_stack
