"""Tests for the model picker modal."""

from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList

from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    ModelPickerModal,
    _ModelPickerRow,
    _build_model_options,
)


class _TestApp(App[str | None]):
    """Minimal app for async model picker tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _highlighted_id(option_list: OptionList) -> str | None:
    highlighted = option_list.highlighted
    if highlighted is None:
        return None
    option = option_list.get_option_at_index(highlighted)
    return str(option.id) if option.id is not None else None


def test_build_model_options_has_default() -> None:
    """The option list should start with 'Same as planner'."""
    options = _build_model_options()
    assert options[0] is not None
    assert options[0].id == "__default__"


def test_build_model_options_has_custom() -> None:
    """The option list should end with 'Custom...'."""
    options = _build_model_options()
    # Last non-None item
    non_none = [o for o in options if o is not None]
    assert non_none[-1].id == CUSTOM_SENTINEL


def test_build_model_options_has_known_models() -> None:
    """The option list should include known models from registry."""
    options = _build_model_options()
    ids = {o.id for o in options if o is not None}
    assert "opus" in ids
    assert "sonnet" in ids
    assert "o3" in ids
    assert "gpt-5.5" in ids
    assert "gemini-2.5-pro" in ids


def test_build_model_options_has_separators() -> None:
    """The option list should include None separators."""
    options = _build_model_options()
    assert None in options


async def test_model_picker_returns_none_for_default() -> None:
    """Selecting 'Same as planner' returns None."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # First option is "Same as planner" — select it
        await pilot.press("enter")
        await pilot.pause()

        assert result is None


async def test_model_picker_escape_cancels() -> None:
    """Escape returns None (cancel)."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert result is None


async def test_model_picker_returns_model_string() -> None:
    """Selecting a model returns its name string."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        # Navigate down past default + separator + header to first model (opus)
        # Default (0) -> separator -> CLAUDE header (disabled) -> opus
        option_list.highlighted = option_list.get_option_index("opus")
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert result == "opus"


async def test_model_picker_returns_custom_sentinel() -> None:
    """Selecting 'Custom...' returns the custom sentinel."""
    result: str | None = "not_set"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index(CUSTOM_SENTINEL)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert result == CUSTOM_SENTINEL


async def test_model_picker_vim_navigation() -> None:
    """j/k keys should navigate the option list."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        initial = option_list.highlighted

        # j moves down
        await pilot.press("j")
        await pilot.pause()
        after_j = option_list.highlighted
        assert after_j != initial

        # k moves back up
        await pilot.press("k")
        await pilot.pause()
        after_k = option_list.highlighted
        assert after_k == initial


async def test_model_picker_filters_by_provider() -> None:
    """Provider filters should show that provider's full model group."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__header_codex__" in ids
        assert "o3" in ids
        assert "gpt-5.5" in ids
        assert "__header_gemini__" not in ids


async def test_model_picker_filters_by_model_substring() -> None:
    """Model substring filters should keep matching models and their header."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "2.5-pro"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__header_gemini__" in ids
        assert "gemini-2.5-pro" in ids
        assert "gemini-3-flash-preview" not in ids


async def test_model_picker_filters_by_alias() -> None:
    """Short aliases from provider metadata should be searchable."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "sonnet45"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__header_opencode__" in ids
        assert "anthropic/claude-sonnet-4-5" in ids


async def test_model_picker_no_results_keeps_escape_hatches() -> None:
    """No-results rendering should keep default/custom paths available."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "definitely-no-such-model"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        labels = [str(option.prompt) for option in option_list.options]
        assert "__default__" in ids
        assert CUSTOM_SENTINEL in ids
        assert "__empty__" in ids
        assert "  No matching models" in labels


async def test_model_picker_selection_remains_valid_after_filter_change() -> None:
    """Filtering away the highlighted model should move selection to a visible row."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index("o3")
        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "gemini"
        await pilot.pause()

        highlighted = option_list.highlighted
        assert highlighted is not None
        option = option_list.get_option_at_index(highlighted)
        assert option.id != "o3"
        assert str(option.id).startswith("gemini-")


async def test_model_picker_escape_clears_filter_before_cancel() -> None:
    """Escape clears an active filter before the modal cancel path."""
    result: str | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert filter_input.value == ""
        assert result == "sentinel"


async def test_model_picker_without_default_filters_correctly() -> None:
    """Temporary override callers should still omit the default option."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal(include_default_option=False)
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__default__" not in ids
        assert CUSTOM_SENTINEL in ids
        assert "o3" in ids


async def test_model_picker_jump_hints_follow_filtered_visible_order() -> None:
    """Jump hints should be assigned in visible selectable-row order."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "gemini"
        await pilot.pause()

        modal.action_jump_to_entry()

        visible_ids = modal._visible_selectable_option_ids()
        assert visible_ids[:3] == [
            "__default__",
            "gemini-2.5-pro",
            "gemini-2.5-flash",
        ]
        assert modal._model_jump_hint_to_id["1"] == visible_ids[0]
        assert modal._model_jump_hint_to_id["2"] == visible_ids[1]
        assert modal._model_jump_id_to_hint[visible_ids[2]] == "3"


async def test_model_picker_jump_apostrophe_without_history_highlights_first() -> None:
    """Apostrophe in jump mode targets the first visible selectable row."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        option_list.highlighted = option_list.get_option_index(CUSTOM_SENTINEL)

        modal.action_jump_to_entry()
        handled = modal._handle_model_jump_key("apostrophe")

        assert handled is True
        assert _highlighted_id(option_list) == "__default__"
        assert modal._model_jump_last_id == CUSTOM_SENTINEL
        assert modal._model_jump_mode_active is False


async def test_model_picker_jump_apostrophe_back_highlights_previous() -> None:
    """Apostrophe in jump mode returns to the saved previous row."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        modal._model_jump_last_id = "o3"
        option_list.highlighted = option_list.get_option_index(CUSTOM_SENTINEL)

        modal.action_jump_to_entry()
        handled = modal._handle_model_jump_key("apostrophe")

        assert handled is True
        assert _highlighted_id(option_list) == "o3"
        assert modal._model_jump_last_id == CUSTOM_SENTINEL
        assert modal._model_jump_mode_active is False


async def test_model_picker_jump_accepts_uppercase_hint() -> None:
    """Uppercase hint characters should dispatch to their exact target."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        rows = [
            _ModelPickerRow(
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
        assert modal._model_jump_hint_to_id["A"] == "synthetic-36"
        handled = modal._handle_model_jump_key("A")

        assert handled is True
        assert _highlighted_id(option_list) == "synthetic-36"
        assert modal._model_jump_mode_active is False


async def test_model_picker_filter_change_clears_jump_hints() -> None:
    """Refiltering should leave no stale hint markers on hidden rows."""
    async with _TestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        modal.action_jump_to_entry()
        assert modal._model_jump_mode_active is True

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "codex"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        assert modal._model_jump_mode_active is False
        assert modal._model_jump_hint_to_id == {}
        assert all(
            not str(option.prompt).startswith("[")
            for option in option_list.options
            if option.id != "__empty__"
        )
