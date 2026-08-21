"""Apostrophe entry-jump coverage for the filter-first Config XPrompts child.

The XPrompts child is the one Config surface where the filter input --
not the row list -- always owns focus, so the jump reservation lives in
``BrowserFilterInput.on_key`` rather than the pane's own key handler. These
tests exercise that reservation end to end: hint painting skips disabled
group headers, a hint selects the right row and updates the preview, the
back stack round-trips, ``Esc`` cancels without closing the modal, an
already-typed filter keeps ``'`` as ordinary text, and a filter rebuild
clears a stale back stack even after jump mode has already exited.
"""

from __future__ import annotations

import pytest
from textual.widgets import OptionList, Static

from sase.ace.testing import AcePage
from sase.ace.tui.modals.config_center_modal import ConfigCenterModal
from sase.ace.tui.modals.xprompt_browser_filter_input import BrowserFilterInput
from sase.ace.tui.modals.xprompt_browser_pane import XPromptBrowserPane
from sase.xprompt.workflow_models import Workflow

from tests.ace.tui.test_xprompt_browser_load_keymap import (
    _hint_text,
    _md_xprompt,
    _open_xprompts_tab,
    _patch_panes,
)


def _option_plain(option_list: OptionList, index: int) -> str:
    option = option_list.get_option_at_index(index)
    return option.prompt.plain  # type: ignore[union-attr]


def _highlighted_name(pane: XPromptBrowserPane) -> str | None:
    item = pane._get_highlighted_item()
    return item.name if item is not None else None


def _three_item_prompts() -> dict[str, Workflow]:
    """A config-backed row plus two ``Other``-category rows across two groups.

    Group order (see ``group_browser_items``): ``User sase.yml`` sorts before
    the catch-all ``Other`` bucket, so the flat logical rows are
    ``cfg`` (0), ``note`` (1), ``zzz`` (2).
    """
    return {
        "cfg": _md_xprompt("cfg", "from config", source_path="config"),
        "note": _md_xprompt("note", "Body.", source_path="n.md"),
        "zzz": _md_xprompt("zzz", "Last body.", source_path="z.md"),
    }


async def test_apostrophe_enters_jump_mode_with_hints_skipping_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        option_list = pane.query_one("#browser-list", OptionList)

        await page.press("apostrophe")
        await page.wait_for(
            lambda _state: (
                pane.jump_mode_active
                and _option_plain(option_list, 1).startswith("[0] ")
                and _option_plain(option_list, 3).startswith("[1] ")
                and _option_plain(option_list, 4).startswith("[2] ")
                and "JUMP ' first" in _hint_text(pane)
            )
        )

        assert pane.jump_mode_active is True
        # Row order: header(User sase.yml), cfg[0], header(Other), note[1], zzz[2].
        assert _option_plain(option_list, 0).startswith("──")
        assert _option_plain(option_list, 1).startswith("[0] ")
        assert _option_plain(option_list, 2).startswith("──")
        assert _option_plain(option_list, 3).startswith("[1] ")
        assert _option_plain(option_list, 4).startswith("[2] ")
        assert "JUMP ' first" in _hint_text(pane)


async def test_jump_hint_selects_item_and_updates_preview(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        option_list = pane.query_one("#browser-list", OptionList)
        assert _highlighted_name(pane) == "cfg"

        await page.press("apostrophe")
        await page.press("1")
        await page.pause()

        assert pane.jump_mode_active is False
        assert pane.jump_back_stack == [0]
        assert _highlighted_name(pane) == "note"
        assert not _option_plain(option_list, 3).startswith("[")
        meta = str(pane.query_one("#browser-meta", Static).render())
        assert "Source: n.md" in meta


async def test_apostrophe_in_jump_mode_returns_to_previous_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())

        await page.press("apostrophe")
        await page.press("1")
        await page.pause()
        assert _highlighted_name(pane) == "note"

        await page.press("apostrophe")
        await page.pause()
        assert "JUMP ' back" in _hint_text(pane)

        await page.press("apostrophe")
        await page.pause()

        assert _highlighted_name(pane) == "cfg"
        assert pane.jump_back_stack == []


async def test_apostrophe_without_history_jumps_to_first_item(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)

        await page.press("ctrl+n")
        await page.pause()
        assert _highlighted_name(pane) == "note"
        assert pane.jump_back_stack == []
        assert filter_input.value == ""

        await page.press("apostrophe")
        await page.press("apostrophe")
        await page.pause()

        assert _highlighted_name(pane) == "cfg"
        assert pane.jump_back_stack == [1]


async def test_escape_cancels_jump_mode_without_closing_modal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        option_list = pane.query_one("#browser-list", OptionList)

        await page.press("apostrophe")
        await page.pause()
        assert pane.jump_mode_active is True

        await page.press("escape")
        await page.pause()

        await page.expect_modal("ConfigCenterModal")
        assert pane.jump_mode_active is False
        assert _highlighted_name(pane) == "cfg"
        assert not _option_plain(option_list, 1).startswith("[0]")
        assert "': jump" in _hint_text(pane)


async def test_apostrophe_with_typed_filter_is_ordinary_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)

        await page.press("n")
        await page.pause()
        assert filter_input.value == "n"

        await page.press("apostrophe")
        await page.pause()

        assert filter_input.value == "n'"
        assert pane.jump_mode_active is False


async def test_jump_mode_key_does_not_leak_into_filter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)

        await page.press("apostrophe")
        await page.pause()
        assert pane.jump_mode_active is True

        # "z" is not an allocated hint for a 3-item list ("0"/"1"/"2"), so it
        # is an invalid hint key -- consumed to exit jump mode, not typed.
        await page.press("z")
        await page.pause()

        assert pane.jump_mode_active is False
        assert filter_input.value == ""


async def test_filtering_after_a_jump_clears_the_stale_back_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with AcePage() as page:
        _, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        filter_input = pane.query_one("#browser-filter-input", BrowserFilterInput)

        await page.press("apostrophe")
        await page.press("1")
        await page.pause()
        assert pane.jump_back_stack == [0]

        # Narrowing the filter to just "zzz" changes the row identities, so
        # rule 5 (stale data) must drop the now-meaningless back stack even
        # though jump mode already exited when the hint was picked above.
        await page.press("z", "z", "z")
        await page.wait_for(lambda _s: filter_input.value == "zzz")

        assert pane.jump_back_stack == []
        assert _highlighted_name(pane) == "zzz"


async def test_zero_items_apostrophe_is_a_silent_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_panes(monkeypatch, {})
    async with AcePage() as page:
        modal = ConfigCenterModal(initial_tab="config")
        page.app.push_screen(modal)
        await page.expect_modal("ConfigCenterModal")
        await page.wait_for(lambda _s: bool(modal.query("#xprompts")))
        pane = modal.query_one("#xprompts", XPromptBrowserPane)

        await page.press("apostrophe")
        await page.pause()

        assert pane.jump_mode_active is False
        assert _highlighted_name(pane) is None


async def test_jump_works_when_the_row_list_owns_focus(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A click can focus the row list, so the pane must route jump keys too.

    ``OptionList`` passes unhandled keys straight through, so without the
    pane's own handler a digit hint would reach the Admin Center's numbered
    tab bindings and switch tabs instead of jumping.
    """
    async with AcePage() as page:
        modal, pane = await _open_xprompts_tab(page, monkeypatch, _three_item_prompts())
        option_list = pane.query_one("#browser-list", OptionList)
        option_list.focus()
        await page.wait_for(lambda _s: option_list.has_focus)

        await page.press("apostrophe")
        await page.pause()
        assert pane.jump_mode_active is True

        await page.press("2")
        await page.wait_for(lambda _s: not pane.jump_mode_active)

        assert modal._active_tab == "config"
        assert _highlighted_name(pane) == "zzz"
        assert pane.jump_back_stack == [0]
