"""App-level containment coverage for vim NORMAL/VISUAL printable keys."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import patch

import pytest

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.artifacts import CommitsPane
from sase.ace.tui.widgets.frontmatter_panel import FrontmatterPanel
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea
from sase.ace.tui.widgets.single_line_vim_text_area import SingleLineVimTextArea
from sase.ace.tui.widgets.vim_text_area import VimTextArea


_PRINTABLE_APP_KEYS = (
    "q",
    "Q",
    "space",
    "plus",
    "at",
    "exclamation_mark",
    "number_sign",
    "asterisk",
    "underscore",
    "apostrophe",
    "grave_accent",
    "m",
    "M",
    "H",
    "L",
    "U",
    "R",
    "z",
    "Z",
)


def _patch_config() -> Any:
    """Use the default ACE keymap without reading the user's config."""
    return patch("sase.config.load_merged_config", return_value={"ace": {}})


async def _mount_home_prompt(
    page: AcePage,
    initial_text: str,
    *,
    as_xprompt_markdown: bool = False,
) -> tuple[PromptInputBar, PromptTextArea]:
    page.app._show_prompt_input_bar_for_home(
        initial_text=initial_text,
        as_xprompt_markdown=as_xprompt_markdown,
    )
    await page.pause()
    bar = page.query_one_widget("#prompt-input-bar", PromptInputBar)
    text_area = bar.active_text_area()
    text_area.focus()
    await page.pause()
    await page.press("escape")
    assert text_area._vim_mode == "normal"
    return bar, text_area


@asynccontextmanager
async def _record_actions(page: AcePage) -> AsyncIterator[list[object]]:
    actions: list[object] = []

    async def record(action: object, *_args: object, **_kwargs: object) -> bool:
        actions.append(action)
        return True

    with patch.object(page.app, "run_action", record):
        yield actions


async def test_normal_space_moves_without_remount_or_cancelled_history() -> None:
    """NORMAL-mode Space stays in the prompt and behaves like ``l``."""
    with (
        _patch_config(),
        patch("sase.history.prompt.add_or_update_prompt") as save_history,
    ):
        async with AcePage() as page:
            bar, text_area = await _mount_home_prompt(page, "hello world")
            text_area.cursor_location = (0, 0)

            async with _record_actions(page) as actions:
                await page.press("space")

            assert page.query_one_widget("#prompt-input-bar", PromptInputBar) is bar
            assert text_area.text == "hello world"
            assert text_area.cursor_location == (0, 1)
            assert actions == []
            save_history.assert_not_called()


@pytest.mark.parametrize("key", _PRINTABLE_APP_KEYS)
async def test_normal_printable_keys_do_not_reach_app_actions(key: str) -> None:
    with _patch_config():
        async with AcePage() as page:
            _bar, _text_area = await _mount_home_prompt(page, "hello world")

            async with _record_actions(page) as actions:
                await page.press(key)

            assert actions == []


@pytest.mark.parametrize("key", _PRINTABLE_APP_KEYS)
async def test_visual_printable_keys_do_not_reach_app_actions(key: str) -> None:
    with _patch_config():
        async with AcePage() as page:
            _bar, text_area = await _mount_home_prompt(page, "hello world")
            await page.press("v")
            assert text_area._vim_mode == "visual"

            async with _record_actions(page) as actions:
                await page.press(key)

            assert actions == []


async def test_normal_non_printable_keys_still_reach_app_actions() -> None:
    with _patch_config():
        async with AcePage() as page:
            await _mount_home_prompt(page, "hello world")

            async with _record_actions(page) as actions:
                await page.press("ctrl+l", "ctrl+o")

            assert actions == ["dismiss_toasts", "jump_to_entry_fast"]


@pytest.mark.parametrize("vim_mode", ["insert", "normal"])
async def test_ctrl_space_leaves_focused_prompt_intact(vim_mode: str) -> None:
    with (
        _patch_config(),
        patch("sase.history.prompt.add_or_update_prompt") as save_history,
    ):
        async with AcePage() as page:
            bar, text_area = await _mount_home_prompt(page, "hello world")
            if vim_mode == "insert":
                await page.press("i")
            assert text_area._vim_mode == vim_mode

            await page.press("ctrl+@")

            assert page.query_one_widget("#prompt-input-bar", PromptInputBar) is bar
            assert text_area.text == "hello world"
            save_history.assert_not_called()


async def test_ctrl_space_leaves_frontmatter_focused_prompt_intact() -> None:
    with (
        _patch_config(),
        patch("sase.history.prompt.add_or_update_prompt") as save_history,
    ):
        async with AcePage() as page:
            prompt_markdown = (
                "---\nxprompts:\n  _rules: Follow the checklist\n---\nhello world"
            )
            bar, text_area = await _mount_home_prompt(
                page,
                prompt_markdown,
                as_xprompt_markdown=True,
            )
            bar.focus_frontmatter_panel()
            await page.pause()
            await page.pause()
            panel = page.query_one_widget("FrontmatterPanel", FrontmatterPanel)
            await page.wait_for(lambda _state: page.app.focused is panel)
            prompt_text = text_area.text

            await page.press("ctrl+@")

            assert page.query_one_widget("#prompt-input-bar", PromptInputBar) is bar
            assert text_area.text == prompt_text
            save_history.assert_not_called()


async def test_ctrl_space_action_is_gated_only_while_prompt_is_mounted() -> None:
    with _patch_config():
        async with AcePage() as page:
            assert page.app.check_action("start_agent_from_patch", ()) is not False

            await _mount_home_prompt(page, "hello world")

            assert page.app.check_action("start_agent_from_patch", ()) is False


async def test_other_main_screen_vim_hosts_contain_normal_space() -> None:
    with _patch_config():
        async with AcePage() as page:
            await page.press("1")
            await page.expect_state("artifacts_subtab", "commits")
            pane = page.query_one_widget("#artifacts-commits-pane", CommitsPane)
            pane.show_filters()
            await page.pause()
            filter_editor = pane.query_one(
                "#commit-filter-input", SingleLineVimTextArea
            )
            # The first Escape closes the completion menu; the second closes
            # the edit session and returns the persistent bar to NORMAL mode.
            await page.press("escape", "escape")
            assert filter_editor._vim_mode == "normal"
            filter_editor.focus()
            await page.wait_for(lambda _state: page.app.focused is filter_editor)

            async with _record_actions(page) as actions:
                await page.press("space")
            assert actions == []

            prompt_markdown = (
                "---\nxprompts:\n  _rules: Follow the checklist\n---\nhello world"
            )
            bar, _text_area = await _mount_home_prompt(
                page,
                prompt_markdown,
                as_xprompt_markdown=True,
            )
            bar.focus_frontmatter_panel()
            await page.pause()
            await page.pause()
            panel = page.query_one_widget("FrontmatterPanel", FrontmatterPanel)
            panel._begin_cell_edit("xprompts", item_name="_rules")
            panel._move_cell(1)
            panel._move_cell(1)
            panel._move_cell(1)
            content_editor = panel.query_one("#frontmatter-content", VimTextArea)
            await page.pause()
            content_editor.focus()
            await page.wait_for(lambda _state: page.app.focused is content_editor)
            await page.press("escape")
            assert content_editor._vim_mode == "normal"

            async with _record_actions(page) as actions:
                await page.press("space")

            assert actions == []
            assert page.query_one_widget("#prompt-input-bar", PromptInputBar) is bar
