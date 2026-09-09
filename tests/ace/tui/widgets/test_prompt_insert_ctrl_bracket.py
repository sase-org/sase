"""Prompt INSERT-mode ``Ctrl+]`` regressions."""

from __future__ import annotations

from sase.ace.testing import PromptPage


async def test_prompt_insert_ctrl_right_square_bracket_enters_normal_mode() -> None:
    async with PromptPage("hi", cursor=(0, 0), mode="insert") as page:
        await page.press("ctrl+right_square_bracket")
        assert page.mode == "normal"


async def test_prompt_insert_ctrl_right_square_bracket_followed_by_normal_key() -> None:
    async with PromptPage("abc", cursor=(0, 0), mode="insert") as page:
        await page.press("ctrl+right_square_bracket", "x")
        assert page.mode == "normal"
        assert page.text == "bc"
