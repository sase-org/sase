"""Tests for model picker modal selection and filtering."""

from textual.widgets import Input, OptionList

from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    DEFAULT_SENTINEL,
    ModelPickerModal,
)
from tests._model_picker_modal_helpers import ModelPickerTestApp


async def test_model_picker_returns_none_for_default() -> None:
    """Selecting 'Follow-up default' returns None."""
    result: str | None = "sentinel"

    async with ModelPickerTestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # First option is "Follow-up default" — select it
        await pilot.press("enter")
        await pilot.pause()

        assert result is None


async def test_model_picker_distinct_default_returns_sentinel() -> None:
    """With distinct_default, selecting the default returns DEFAULT_SENTINEL."""
    result: str | None = "sentinel"

    async with ModelPickerTestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal(distinct_default=True)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # First option is "Follow-up default" — select it
        await pilot.press("enter")
        await pilot.pause()

        assert result == DEFAULT_SENTINEL


async def test_model_picker_distinct_default_escape_still_returns_none() -> None:
    """Escape still cancels (None) even when distinct_default is enabled."""
    result: str | None = "sentinel"

    async with ModelPickerTestApp().run_test() as pilot:

        def on_dismiss(r: str | None) -> None:
            nonlocal result
            result = r

        modal = ModelPickerModal(distinct_default=True)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("escape")
        await pilot.pause()

        assert result is None


async def test_model_picker_escape_cancels() -> None:
    """Escape returns None (cancel)."""
    result: str | None = "sentinel"

    async with ModelPickerTestApp().run_test() as pilot:

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

    async with ModelPickerTestApp().run_test() as pilot:

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

    async with ModelPickerTestApp().run_test() as pilot:

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
    async with ModelPickerTestApp().run_test() as pilot:
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
    async with ModelPickerTestApp().run_test() as pilot:
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
        assert "gpt-5.6-sol" in ids
        assert "gpt-5.5" in ids
        assert "__header_agy__" not in ids


async def test_model_picker_filters_by_model_substring() -> None:
    """Model substring filters should keep matching models and their header."""
    async with ModelPickerTestApp().run_test() as pilot:
        modal = ModelPickerModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        filter_input = modal.query_one("#model-picker-filter", Input)
        filter_input.value = "gemini-3.6"
        await pilot.pause()

        option_list = modal.query_one("#model-picker-list", OptionList)
        ids = {option.id for option in option_list.options}
        assert "__header_agy__" in ids
        assert "gemini-3.6-flash-high" in ids
        assert "gemini-3.5-flash-high" not in ids


async def test_model_picker_filters_by_alias() -> None:
    """Short aliases from provider metadata should be searchable."""
    async with ModelPickerTestApp().run_test() as pilot:
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
    async with ModelPickerTestApp().run_test() as pilot:
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
    async with ModelPickerTestApp().run_test() as pilot:
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
        # A "gemini" filter matches the Antigravity (agy) Gemini slugs.
        assert "gemini" in str(option.id).lower()


async def test_model_picker_escape_clears_filter_before_cancel() -> None:
    """Escape clears an active filter before the modal cancel path."""
    result: str | None = "sentinel"

    async with ModelPickerTestApp().run_test() as pilot:

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
    async with ModelPickerTestApp().run_test() as pilot:
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
