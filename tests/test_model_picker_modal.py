"""Tests for the model picker modal."""

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.model_picker_modal import (
    CUSTOM_SENTINEL,
    ModelPickerModal,
    _build_model_options,
)


class _TestApp(App[str | None]):
    """Minimal app for async model picker tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


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
