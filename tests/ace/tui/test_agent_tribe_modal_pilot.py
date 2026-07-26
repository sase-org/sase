"""Pilot tests for the AgentTribeModal tribe / removal UX."""

from __future__ import annotations

from typing import Any

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Label

import sase.ace.tui.models.tribe_display as tribe_display
from sase.ace.tui.modals.agent_tribe_modal import (
    AgentTribeModal,
    AgentTribeModalResult,
    _TribeInput,
)


class _TestApp(App[AgentTribeModalResult | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _style_at(text: Any, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    base_style = getattr(text, "style", None)
    return str(base_style) if base_style else None


async def test_modal_current_tribe_uses_configured_identity_color(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        tribe_display,
        "load_merged_config",
        lambda: {"ace": {"tribes": {"epic": {"color": "#123456"}}}},
    )
    monkeypatch.setattr(
        tribe_display,
        "current_config_token",
        lambda: ("agent-tribe-modal-color",),
    )
    tribe_display._tribe_displays_for_token.cache_clear()

    async with _TestApp().run_test() as pilot:
        modal = AgentTribeModal(
            target_label="agent-x",
            current_tribe="epic",
            known_tribes=("epic",),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        rendered = modal.query_one("#agent-tribe-current", Label).render()

    assert rendered.plain == "Current: @epic"
    assert _style_at(rendered, rendered.plain.index("@epic")) == ("rgb(18,52,86) bold")


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
