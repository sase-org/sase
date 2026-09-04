"""Tests for model picker jump navigation."""

from textual.widgets import Input, OptionList

from sase.ace.tui.modals.model_picker_modal import CUSTOM_SENTINEL, ModelPickerModal
from sase.ace.tui.modals.model_picker_rows import ModelPickerRow
from tests._model_picker_modal_helpers import ModelPickerTestApp


def _highlighted_id(option_list: OptionList) -> str | None:
    highlighted = option_list.highlighted
    if highlighted is None:
        return None
    option = option_list.get_option_at_index(highlighted)
    return str(option.id) if option.id is not None else None


async def test_model_picker_jump_hints_follow_filtered_visible_order() -> None:
    """Jump hints should be assigned in visible selectable-row order."""
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "gemini"
        await pilot.pause()

        modal.action_jump_to_entry()

        visible_ids = modal._jump_target_keys()
        # Providers render in entry-point order, with Antigravity's newest
        # Gemini slugs leading the filtered list.
        assert visible_ids[:3] == [
            "__default__",
            "gemini-3.8-flash-high",
            "gemini-3.8-flash-medium",
        ]
        hints = modal.jump_hints_by_key()
        assert hints[visible_ids[0]] == "0"
        assert hints[visible_ids[1]] == "1"
        assert hints[visible_ids[2]] == "2"


async def test_model_picker_jump_apostrophe_without_history_highlights_first() -> None:
    """Apostrophe in jump mode targets the first visible selectable row."""
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index(CUSTOM_SENTINEL)

        modal.action_jump_to_entry()
        handled = modal.handle_jump_key("apostrophe")

        assert handled is True
        assert _highlighted_id(option_list) == "__default__"
        assert modal.jump_back_stack == [
            modal._jump_target_keys().index(CUSTOM_SENTINEL)
        ]
        assert modal.jump_mode_active is False


async def test_model_picker_jump_apostrophe_back_highlights_previous() -> None:
    """Apostrophe in jump mode returns to the row on top of the back stack."""
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        modal._jump_state().back_stack.append(modal._jump_target_keys().index("o3"))
        option_list.highlighted = option_list.get_option_index(CUSTOM_SENTINEL)

        modal.action_jump_to_entry()
        handled = modal.handle_jump_key("apostrophe")

        assert handled is True
        assert _highlighted_id(option_list) == "o3"
        # A back jump pops its target instead of pushing the row it left.
        assert modal.jump_back_stack == []
        assert modal.jump_mode_active is False


async def test_model_picker_jump_accepts_uppercase_hint() -> None:
    """Uppercase hint characters should dispatch to their exact target."""
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        rows = [
            ModelPickerRow(
                kind="model",
                label=f"    synthetic-{index}",
                option_id=f"synthetic-{index}",
                provider="synthetic",
                model_id=f"synthetic-{index}",
            )
            for index in range(37)
        ]
        option_list = modal.query_one("#model-picker-list", OptionList)
        modal._visible_rows = rows
        option_list.clear_options()
        option_list.add_options(modal._render_options())
        option_list.highlighted = option_list.get_option_index("synthetic-0")

        modal.action_jump_to_entry()
        assert modal.jump_hints_by_key()["synthetic-36"] == "A"
        handled = modal.handle_jump_key("A")

        assert handled is True
        assert _highlighted_id(option_list) == "synthetic-36"
        assert modal.jump_mode_active is False


async def test_model_picker_two_character_hint_accepts_uppercase_second_char() -> None:
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        rows = [
            ModelPickerRow(
                kind="model",
                label=f"    synthetic-{index}",
                option_id=f"synthetic-{index}",
                provider="synthetic",
                model_id=f"synthetic-{index}",
            )
            for index in range(63)
        ]
        option_list = modal.query_one("#model-picker-list", OptionList)
        modal._visible_rows = rows
        option_list.clear_options()
        option_list.add_options(modal._render_options())
        option_list.highlighted = option_list.get_option_index("synthetic-0")

        modal.action_jump_to_entry()
        assert modal.jump_hints_by_key()["synthetic-61"] == "0Z"

        assert modal.handle_jump_key("0") is True
        assert modal.jump_mode_active is True
        assert modal._jump_state().pending_prefix == "0"
        assert _highlighted_id(option_list) == "synthetic-0"

        assert modal.handle_jump_key("Z") is True
        assert modal.jump_mode_active is False
        assert modal._jump_state().pending_prefix == ""
        assert _highlighted_id(option_list) == "synthetic-61"


async def test_model_picker_filter_change_clears_jump_hints() -> None:
    """Refiltering should leave no stale hint markers on hidden rows."""
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_jump_to_entry()
        assert modal.jump_mode_active is True

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        assert modal.jump_mode_active is False
        assert modal._jump_state().pending_prefix == ""
        assert modal.jump_hints_by_key() == {}
        assert all(
            not str(option.prompt).startswith("[")
            for option in option_list.options
            if option.id != "__empty__"
        )
