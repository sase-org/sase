"""Regression: Tab in the prompt input must not switch TUI tabs."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest
import pytest_asyncio
from textual import events

from sase.ace.testing import AcePage, AcePageGroup
from sase.ace.tui.widgets.agent_list import AgentList
from sase.ace.tui.widgets.prompt_input_bar import PromptInputBar
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea

pytestmark = pytest.mark.asyncio(loop_scope="module")


def _patch_config() -> Any:
    """Use the default ACE keymap without reading the user's config."""
    return patch("sase.config.load_merged_config", return_value={"ace": {}})


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def ace_group() -> AsyncIterator[AcePageGroup]:
    with _patch_config():
        async with AcePageGroup(initial_tab="agents") as group:
            yield group


@pytest_asyncio.fixture(loop_scope="module")
async def page(ace_group: AcePageGroup) -> AsyncIterator[AcePage]:
    async with ace_group.checkout() as checkout:
        yield checkout


async def _mount_home_prompt(
    page: AcePage,
    initial_text: str,
) -> tuple[PromptInputBar, PromptTextArea]:
    page.app._show_prompt_input_bar_for_home(initial_text=initial_text)
    await page.pause()
    bar = page.query_one_widget("#prompt-input-bar", PromptInputBar)
    text_area: PromptTextArea | None = None

    def active_text_area_mounted() -> bool:
        nonlocal text_area
        try:
            text_area = bar.active_text_area()
        except Exception:
            return False
        return True

    await page.wait_for(lambda _state: active_text_area_mounted())
    assert text_area is not None
    text_area.focus()
    await page.pause()
    await page.wait_for(lambda _state: page.app.focused is text_area)
    return bar, text_area


@pytest.mark.parametrize("vim_mode", ["insert", "normal"])
@pytest.mark.parametrize(
    "trigger",
    ["refresh_display", "refresh_titles"],
)
async def test_tab_after_background_refresh_stays_on_agents(
    page: AcePage,
    vim_mode: str,
    trigger: str,
) -> None:
    with _patch_config():
        assert page.app.current_tab == "agents"
        _bar, text_area = await _mount_home_prompt(page, "hello world")
        if vim_mode == "insert":
            if text_area._vim_mode != "insert":
                await page.press("i")
        else:
            await page.press("escape")
        assert text_area._vim_mode == vim_mode
        text_area.focus()
        await page.wait_for(lambda _state: page.app.focused is text_area)

        if trigger == "refresh_display":
            page.app._refresh_agents_display(list_changed=True)
        else:
            page.app._refresh_agent_panel_titles()
        page.app.post_message(events.Key("tab", None))
        await page.pause()

        assert page.app.current_tab == "agents"
        assert page.app.focused is text_area


async def test_tab_with_focus_on_list_still_stays_on_agents(page: AcePage) -> None:
    with _patch_config():
        assert page.app.current_tab == "agents"
        _bar, text_area = await _mount_home_prompt(page, "hello world")
        await page.wait_for(lambda _state: page.app.focused is text_area)

        lists = list(page.app.query(AgentList))
        assert lists
        page.app.screen.set_focus(lists[0])
        page.app.post_message(events.Key("tab", None))
        await page.pause()

        assert page.app.current_tab == "agents"
