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
            await page.press("4")
            await page.press("j")
            await page.expect_state("idx", 1)


async def test_remapped_navigation_key() -> None:
    """Remapping next_patch to 'B' makes 'B' navigate and 'j' not."""
    keymap_cfg = {"app": {"next_patch": "B"}}

    # 'B' should navigate
    with _patch_config(keymap_cfg):
        async with AcePage() as page:
            await page.press("4")
            await page.press("B")
            await page.expect_state("idx", 1)

    # 'j' should no longer navigate
    with _patch_config(keymap_cfg):
        async with AcePage() as page:
            await page.press("4")
            await page.press("j")
            await page.expect_state("idx", 0)


async def test_default_query_shortcuts_follow_the_context_matrix() -> None:
    with _patch_config():
        async with AcePage(initial_tab="changespecs") as page:  # legacy wire key
            edits: list[str] = []
            for subtab, subtab_key, top_level_subtab, expected_edit in (
                ("prs", None, "prs", True),
                ("commits", "1", "commits", True),
                ("bugs", "3", "bugs", False),
                ("plans", "5", "files", True),
            ):
                if subtab_key is not None:
                    await page.press(subtab_key)
                    await page.expect_state("artifacts_subtab", top_level_subtab)
                    if subtab == "plans":
                        await page.expect_state("files_subtab", "plans")
                edits.clear()
                page.app.action_edit_query = (  # type: ignore[method-assign]
                    lambda edits=edits, subtab=subtab: edits.append(subtab)
                )

                await page.press("slash")
                assert edits == ([subtab] if expected_edit else [])

                await page.press("comma", "slash")
                assert edits == ([subtab] if expected_edit else [])

        async with AcePage(initial_tab="axe") as page:
            edits: list[bool] = []
            page.app.action_edit_query = lambda: edits.append(True)  # type: ignore[method-assign]

            await page.press("slash")
            assert edits == [True]
            await page.press("comma", "slash")
            assert edits == [True]

        async with AcePage(initial_tab="agents") as page:
            searches: list[bool] = []
            edits: list[bool] = []
            page.app.action_search_forward = lambda: searches.append(True)  # type: ignore[method-assign]
            page.app.action_edit_query = lambda: edits.append(True)  # type: ignore[method-assign]

            await page.press("slash")
            assert searches == [True]
            assert edits == []

            await page.press("comma", "slash")
            assert edits == [True]


async def test_custom_app_and_leader_query_remaps_stay_independent() -> None:
    keymap_cfg = {
        "app": {"edit_query": "f5"},
        "modes": {"leader_mode": {"keys": {"edit_query": "f6"}}},
    }

    with _patch_config(keymap_cfg):
        async with AcePage(initial_tab="changespecs") as page:  # legacy wire key
            edits: list[bool] = []
            page.app.action_edit_query = lambda: edits.append(True)  # type: ignore[method-assign]

            await page.press("slash")
            assert edits == []
            await page.press("f5")
            assert edits == [True]
            await page.press("comma", "f6")
            assert edits == [True]

            await page.press("shift+tab")
            await page.expect_state("tab", "agents")
            searches: list[bool] = []
            edits: list[bool] = []
            page.app.action_search_forward = lambda: searches.append(True)  # type: ignore[method-assign]
            page.app.action_edit_query = lambda: edits.append(True)  # type: ignore[method-assign]

            await page.press("slash")
            assert searches == [True]
            await page.press("f5")
            assert edits == []
            await page.press("comma", "f6")
            assert edits == [True]


async def test_bare_question_mark_opens_help_and_leader_chord_is_retired() -> None:
    with _patch_config():
        async with AcePage(initial_tab="changespecs") as page:  # legacy wire key
            for index, tab in enumerate(
                ("changespecs", "agents", "axe")
            ):  # legacy wire key
                if index:
                    await page.press("shift+tab")
                    await page.expect_state("tab", tab)
                await page.press("question_mark")
                await page.expect_modal("HelpModal")
                await page.press("escape")
                await page.expect_no_modal()

                await page.press("comma", "question_mark")
                await page.expect_no_modal()


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

            page.app.action_start_agent_from_patch = _record_repeat_agent  # type: ignore[method-assign]
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
            page.app._start_agent_from_patch_quick = _record_quick_agent  # type: ignore[method-assign]

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


async def test_agents_prompt_input_ctrl_j_keeps_local_newline_priority() -> None:
    """The Agents metadata shortcut must not steal Ctrl+J from the editor."""
    with _patch_config():
        async with AcePage(initial_tab="agents") as page:
            await page.press("space")
            await page.pause()

            text_area = page.query_one_widget(".prompt-input", PromptTextArea)
            await page.press("a", "ctrl+j", "b")
            await page.pause()

            assert text_area.text == "a\nb"


async def test_agents_prompt_input_ctrl_k_keeps_local_history_priority() -> None:
    """The Agents previous-section shortcut must not steal prompt history."""
    with _patch_config():
        async with AcePage(initial_tab="agents") as page:
            await page.press("space")
            await page.pause()
            await page.press("h", "i", "ctrl+k")

            await page.expect_modal("PromptHistoryModal")
