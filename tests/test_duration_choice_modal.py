"""Tests for the shared duration-choice modal."""

from textual.app import App, ComposeResult
from textual.widgets import Input, Label

from sase.ace.tui.modals.duration_choice_modal import (
    DURATION_CHOICE_CANCELLED,
    DurationChoice,
    DurationChoiceModal,
)


class _TestApp(App[None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _modal() -> DurationChoiceModal[int | None, object]:
    def parse_custom(raw: str) -> int | None:
        if raw == "none":
            return None
        if raw.isdigit():
            return int(raw)
        raise ValueError("Invalid duration")

    return DurationChoiceModal(
        title="Duration",
        choices=[
            DurationChoice(key="1", title="One", subtitle="First", value=1),
            DurationChoice(key="2", title="None", subtitle="No expiry", value=None),
        ],
        parse_custom=parse_custom,
        custom_placeholder="duration",
        cancel_result=DURATION_CHOICE_CANCELLED,
        id_prefix="test-duration",
    )


async def test_cancel_uses_sentinel_so_none_remains_a_result() -> None:
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_modal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert result is DURATION_CHOICE_CANCELLED


async def test_none_choice_is_returned_as_real_value() -> None:
    result: object = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(_modal(), callback=on_dismiss)
        await pilot.pause()
        await pilot.press("2")
        await pilot.pause()

    assert result is None


async def test_custom_validation_keeps_modal_open_with_error() -> None:
    dismissed: list[object] = []

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(_modal(), callback=lambda value: dismissed.append(value))
        await pilot.pause()
        await pilot.press("c")
        await pilot.pause()

        custom_input = pilot.app.screen.query_one("#test-duration-custom-input", Input)
        custom_input.value = "bad"
        await pilot.press("enter")
        await pilot.pause()

        error = pilot.app.screen.query_one("#test-duration-custom-error", Label)
        assert dismissed == []
        assert not error.has_class("hidden")
