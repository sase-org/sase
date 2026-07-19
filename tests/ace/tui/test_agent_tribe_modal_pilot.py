"""Pilot tests for the AgentTribeModal tribe / removal UX."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.modals.agent_tribe_modal import (
    AgentTribeModal,
    AgentTribeModalResult,
    _TribeInput,
)


class _TestApp(App[AgentTribeModalResult | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_modal_agent_with_tribe_ctrl_d_clears_in_one_keystroke() -> None:
    result: AgentTribeModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTribeModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe="name_level",
            known_tribes=("name_level",),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # The current tribe is context, not editable input; Ctrl+D still clears.
        tribe_input = modal.query_one("#agent-tribe-input", _TribeInput)
        assert tribe_input.value == ""

        await pilot.press("ctrl+d")
        await pilot.pause()

    assert result == AgentTribeModalResult(action="unset", tribe=None)


async def test_modal_first_keystroke_enters_tribe_for_agent_with_tribe() -> None:
    async with _TestApp().run_test() as pilot:
        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe="name_level",
            known_tribes=(),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        tribe_input = modal.query_one("#agent-tribe-input", _TribeInput)
        assert tribe_input.value == ""

        await pilot.press("x")
        await pilot.pause()

        assert tribe_input.value == "x"


async def test_modal_enter_on_agent_with_tribe_empty_input_unsets() -> None:
    result: AgentTribeModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTribeModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe="name_level",
            known_tribes=(),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTribeModalResult(action="unset", tribe=None)


async def test_modal_input_empty_for_bulk() -> None:
    async with _TestApp().run_test() as pilot:
        modal = AgentTribeModal(
            target_label="2 marked agent(s)",
            current_tribe=None,
            known_tribes=(),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        tribe_input = modal.query_one("#agent-tribe-input", _TribeInput)
        assert tribe_input.value == ""


async def test_modal_empty_enter_unsets_when_without_tribe() -> None:
    result: AgentTribeModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTribeModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe=None,
            known_tribes=(),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        tribe_input = modal.query_one("#agent-tribe-input", _TribeInput)
        assert tribe_input.value == ""

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTribeModalResult(action="unset", tribe=None)


async def test_modal_clear_then_enter_unsets_default_tribe_prefill() -> None:
    result: AgentTribeModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTribeModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe=None,
            known_tribes=(),
            default_tribe="pinned",
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        tribe_input = modal.query_one("#agent-tribe-input", _TribeInput)
        assert tribe_input.value == "pinned"

        # Mount selects all; delete wipes the selection.
        await pilot.press("delete")
        await pilot.pause()
        assert tribe_input.value == ""

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTribeModalResult(action="unset", tribe=None)


async def test_modal_whitespace_only_enter_unsets() -> None:
    result: AgentTribeModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTribeModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe=None,
            known_tribes=(),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("space")
        await pilot.pause()

        tribe_input = modal.query_one("#agent-tribe-input", _TribeInput)
        assert tribe_input.value == " "

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTribeModalResult(action="unset", tribe=None)


async def test_modal_prefill_pinned_when_without_tribe_with_default() -> None:
    result: AgentTribeModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTribeModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe=None,
            known_tribes=(),
            default_tribe="pinned",
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        tribe_input = modal.query_one("#agent-tribe-input", _TribeInput)
        assert tribe_input.value == "pinned"

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTribeModalResult(action="set", tribe="pinned")
