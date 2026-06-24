"""Tests for PromptTextArea vim cursor mode CSS classes."""

from sase.ace.testing import PromptPage

_VIM_CURSOR_CLASSES = {"-vim-normal", "-vim-insert", "-vim-visual"}


def _assert_cursor_class(page: PromptPage, expected: str) -> None:
    classes = set(page.ta.classes)
    assert expected in classes
    assert not ((_VIM_CURSOR_CLASSES - {expected}) & classes)


async def test_prompt_text_area_seeds_insert_cursor_class_on_mount() -> None:
    async with PromptPage("abc", mode="insert") as page:
        assert page.mode == "insert"
        _assert_cursor_class(page, "-vim-insert")


async def test_prompt_text_area_syncs_cursor_class_for_vim_modes() -> None:
    async with PromptPage("aaa\nbbb") as page:
        assert page.mode == "normal"
        _assert_cursor_class(page, "-vim-normal")

        page.ta._enter_insert_mode()
        _assert_cursor_class(page, "-vim-insert")

        page.ta._enter_normal_mode()
        _assert_cursor_class(page, "-vim-normal")

        page.ta._enter_visual_mode("charwise")
        assert page.mode == "visual"
        _assert_cursor_class(page, "-vim-visual")

        page.ta._switch_visual_kind("linewise")
        assert page.mode == "visual_line"
        _assert_cursor_class(page, "-vim-visual")
