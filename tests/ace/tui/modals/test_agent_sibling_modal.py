"""Tests for the agent sibling chooser modal."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import OptionList

from sase.ace.tui.modals.agent_sibling_modal import (
    AgentSiblingChoice,
    AgentSiblingModal,
    _agent_sibling_option_text,
    _agent_sibling_selector_keys,
)


class _TestApp(App[object | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _choices(count: int = 3) -> list[AgentSiblingChoice]:
    return [
        AgentSiblingChoice(
            global_idx=index + 10,
            agent_name=f"foo.agent{index}",
            display_name="demo",
            status="RUNNING" if index == 0 else "DONE",
            panel_label="#review" if index == 1 else "(untagged)",
            time_hint="4m",
        )
        for index in range(count)
    ]


async def test_agent_sibling_modal_enter_selects_highlighted_row() -> None:
    choices = _choices()
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentSiblingModal("foo.*", choices)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        option_list = modal.query_one("#agent-sibling-list", OptionList)
        option_list.highlighted = 1
        await pilot.press("enter")
        await pilot.pause()

    assert result == choices[1].global_idx


async def test_agent_sibling_modal_letter_quick_selects_row() -> None:
    choices = _choices()
    result: object | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: object | None) -> None:
            nonlocal result
            result = value

        modal = AgentSiblingModal("foo.*", choices)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("b")
        await pilot.pause()

    assert result == choices[1].global_idx


async def test_agent_sibling_modal_j_k_move_highlight() -> None:
    async with _TestApp().run_test() as pilot:
        modal = AgentSiblingModal("foo.*", _choices())
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-sibling-list", OptionList)
        assert option_list.highlighted == 0

        await pilot.press("j")
        await pilot.pause()
        assert option_list.highlighted == 1

        await pilot.press("k")
        await pilot.pause()
        assert option_list.highlighted == 0


async def test_agent_sibling_modal_escape_and_q_cancel() -> None:
    for key in ("escape", "q"):
        result: object | None = "sentinel"
        async with _TestApp().run_test() as pilot:

            def on_dismiss(value: object | None) -> None:
                nonlocal result
                result = value

            modal = AgentSiblingModal("foo.*", _choices(1))
            pilot.app.push_screen(modal, callback=on_dismiss)
            await pilot.pause()

            await pilot.press(key)
            await pilot.pause()

        assert result is None


def test_agent_sibling_modal_selector_keys_skip_navigation_keys() -> None:
    keys = _agent_sibling_selector_keys(26)

    assert "j" not in keys
    assert "k" not in keys
    assert "q" not in keys
    assert keys[:3] == ["a", "b", "c"]


def test_agent_sibling_modal_option_text_includes_row_metadata() -> None:
    plain = _agent_sibling_option_text("a", _choices(2)[1]).plain

    assert "a" in plain
    assert "foo.agent1" in plain
    assert "DONE" in plain
    assert "#review" in plain
    assert "4m" in plain
