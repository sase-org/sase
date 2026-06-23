"""Tests for the Auto-Approve quick-action menu modal."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from sase.ace.tui.modals.auto_approve_modal import (
    _OPTIONS,
    AutoApproveChoice,
    AutoApproveModal,
)


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


@pytest.mark.parametrize(
    ("key", "expected"),
    [("p", "plan"), ("t", "tale"), ("e", "epic"), ("d", "disable")],
)
async def test_auto_approve_modal_key_selects_choice(key: str, expected: str) -> None:
    result: object | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(
            AutoApproveModal("disable", "my-agent.3"), callback=on_dismiss
        )
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()

    assert result == expected


@pytest.mark.parametrize("current", ["plan", "tale", "epic", "disable"])
async def test_auto_approve_modal_marks_current_state(
    current: AutoApproveChoice,
) -> None:
    async with _TestApp().run_test() as pilot:
        modal = AutoApproveModal(current, "my-agent.3")
        pilot.app.push_screen(modal)
        await pilot.pause()

        for option in _OPTIONS:
            row = modal.query_one(f"#auto-approve-choice-{option.choice}", Static)
            assert row.has_class("selected") == (option.choice == current)


@pytest.mark.parametrize("key", ["escape", "q"])
async def test_auto_approve_modal_cancel_returns_none(key: str) -> None:
    result: object | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(AutoApproveModal("plan"), callback=on_dismiss)
        await pilot.pause()
        await pilot.press(key)
        await pilot.pause()

    assert result is None


async def test_auto_approve_modal_printable_char_does_not_leak() -> None:
    result: object | None = "sentinel"

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        pilot.app.push_screen(AutoApproveModal("plan"), callback=on_dismiss)
        await pilot.pause()

        # A stray printable character neither dismisses the menu nor leaks to
        # the app's custom-mode prefix handling.
        await pilot.press("z")
        await pilot.pause()
        assert result == "sentinel"

        # The menu still works afterward.
        await pilot.press("t")
        await pilot.pause()

    assert result == "tale"


def test_auto_approve_modal_row_markup_labels_and_marker() -> None:
    modal = AutoApproveModal("disable", "agent.1")

    tale_markup = modal._option_row_markup(_OPTIONS[1])
    assert "Tale" in tale_markup
    assert "approve & commit as a tale" in tale_markup
    assert "▸" not in tale_markup  # not the current state

    disable_markup = modal._option_row_markup(_OPTIONS[3])
    assert "Disable" in disable_markup
    assert "▸" in disable_markup  # current state carries the marker


def test_auto_approve_modal_options_mirror_directive_mnemonics() -> None:
    by_choice = {opt.choice: opt.key for opt in _OPTIONS}
    assert by_choice == {"plan": "p", "tale": "t", "epic": "e", "disable": "d"}
