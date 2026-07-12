"""End-to-end tests for remapped keybindings via the AcePage testing DSL."""

from unittest.mock import patch

from sase.ace.testing import AcePage
from sase.ace.tui.widgets.prompt_text_area import PromptTextArea


def _patch_config(overrides: dict | None = None):
    """Patch load_merged_config to return custom ace keymaps config."""
    cfg: dict = {"ace": {}}
    if overrides:
        cfg["ace"]["keymaps"] = overrides
    return patch("sase.config.load_merged_config", return_value=cfg)


async def test_default_keys_still_work() -> None:
    """With no config override, default 'j' key navigates down."""
    with _patch_config():
        async with AcePage() as page:
            await page.press("j")
            await page.expect_state("idx", 1)


async def test_remapped_navigation_key() -> None:
    """Remapping next_changespec to 'B' makes 'B' navigate and 'j' not."""
    keymap_cfg = {"app": {"next_changespec": "B"}}

    # 'B' should navigate
    with _patch_config(keymap_cfg):
        async with AcePage() as page:
            await page.press("B")
            await page.expect_state("idx", 1)

    # 'j' should no longer navigate
    with _patch_config(keymap_cfg):
        async with AcePage() as page:
            await page.press("j")
            await page.expect_state("idx", 0)


async def test_plus_dispatches_custom_agent_and_at_does_not() -> None:
    """Default ``+`` launches the custom-agent selector; ``@`` no longer does."""
    with _patch_config():
        async with AcePage() as page:
            custom_calls: list[bool] = []

            def _record_custom_agent() -> None:
                custom_calls.append(True)

            page.app.action_start_custom_agent = _record_custom_agent  # type: ignore[method-assign]

            await page.press("at")
            assert custom_calls == []

            await page.press("plus")
            assert custom_calls == [True]


async def test_leader_at_opens_panel_while_bare_at_restores() -> None:
    """The real key sequence preserves the restore versus panel split."""
    with _patch_config():
        async with AcePage() as page:
            restore_calls: list[bool] = []
            panel_calls: list[bool] = []

            async def _record_restore() -> None:
                restore_calls.append(True)

            async def _record_panel() -> None:
                panel_calls.append(True)

            page.app.action_restore_prompt_stash = _record_restore  # type: ignore[method-assign]
            page.app.action_open_prompt_stash = _record_panel  # type: ignore[method-assign]

            await page.press("at")
            await page.pause()
            assert restore_calls == [True]
            assert panel_calls == []

            await page.press("comma", "at")
            await page.pause()
            assert restore_calls == [True]
            assert panel_calls == [True]


async def test_ctrl_at_dispatches_repeat_agent_binding_not_home_space() -> None:
    """Ctrl+Space dispatches repeat-last while Space dispatches home mode."""
    with _patch_config():
        async with AcePage() as page:
            repeat_calls: list[bool] = []
            home_calls: list[bool] = []

            def _record_repeat_agent() -> None:
                repeat_calls.append(True)

            def _record_home_agent() -> None:
                home_calls.append(True)

            page.app.action_start_agent_from_changespec = _record_repeat_agent  # type: ignore[method-assign]
            page.app.action_start_agent_home = _record_home_agent  # type: ignore[method-assign]

            await page.press("space")
            assert home_calls == [True]
            assert repeat_calls == []

            await page.press("ctrl+@")
            assert repeat_calls == [True]
            assert home_calls == [True]


async def test_leader_space_dispatches_current_selection_and_h_dispatches_home() -> (
    None
):
    """Leader Space uses current selection while leader h remains a home alias."""
    with _patch_config():
        async with AcePage() as page:
            home_calls: list[bool] = []
            quick_calls: list[bool] = []

            def _record_agent_home() -> None:
                home_calls.append(True)

            def _record_quick_agent() -> None:
                quick_calls.append(True)

            page.app._show_prompt_input_bar_for_home = _record_agent_home  # type: ignore[method-assign]
            page.app._start_agent_from_changespec_quick = _record_quick_agent  # type: ignore[method-assign]

            await page.press("space")
            assert home_calls == [True]
            assert quick_calls == []

            await page.press("comma", "space")
            assert home_calls == [True]
            assert quick_calls == [True]

            await page.press("comma", "h")
            assert home_calls == [True, True]
            assert quick_calls == [True]


async def test_prompt_input_space_is_text_after_home_prompt_opens() -> None:
    """Space typed inside the prompt bar remains local text input."""
    with _patch_config():
        async with AcePage() as page:
            await page.press("space")
            await page.pause()

            text_area = page.query_one_widget(".prompt-input", PromptTextArea)
            await page.press("a", "space", "b")
            await page.pause()

            assert text_area.text == "a b"
