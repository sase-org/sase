"""Tests for the saved-agent-group naming modal."""

from __future__ import annotations

from textual.app import App
from textual.widgets import Input

from sase.ace.tui.modals.save_agent_group_modal import (
    SaveAgentGroupModal,
    SaveAgentGroupResult,
)


class _TestApp(App[SaveAgentGroupResult | None]):
    pass


async def test_blank_enter_confirms_without_name() -> None:
    result: SaveAgentGroupResult | None = None
    modal = SaveAgentGroupModal(candidate_count=2)

    def on_dismiss(value: SaveAgentGroupResult | None) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        await pilot.press("enter")
        await pilot.pause()

    assert result == SaveAgentGroupResult(name=None)


async def test_nonblank_enter_returns_trimmed_name() -> None:
    result: SaveAgentGroupResult | None = None
    modal = SaveAgentGroupModal(candidate_count=2)

    def on_dismiss(value: SaveAgentGroupResult | None) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        modal.query_one(
            "#save-agent-group-name-input", Input
        ).value = "  Backend batch  "
        await pilot.press("enter")
        await pilot.pause()

    assert result == SaveAgentGroupResult(name="Backend batch")


async def test_escape_cancels_without_result() -> None:
    result: SaveAgentGroupResult | None = SaveAgentGroupResult(name="unchanged")
    modal = SaveAgentGroupModal(candidate_count=2)

    def on_dismiss(value: SaveAgentGroupResult | None) -> None:
        nonlocal result
        result = value

    async with _TestApp().run_test() as pilot:
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()

    assert result is None
