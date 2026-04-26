"""Pilot tests for the AgentTagModal prefill / removal UX."""

from __future__ import annotations

from textual.app import App, ComposeResult

from sase.ace.tui.modals.agent_tag_modal import (
    AgentTagModal,
    AgentTagModalResult,
    _TagInput,
)


class _TestApp(App[AgentTagModalResult | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_modal_prefill_then_ctrl_d_clears_in_one_keystroke() -> None:
    result: AgentTagModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTagModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTagModal(
            target_label="agent-x",
            current_tag="name_level",
            known_tags=("name_level",),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Prefill is in place; Ctrl+D clears immediately with no typing.
        tag_input = modal.query_one("#agent-tag-input", _TagInput)
        assert tag_input.value == "name_level"

        await pilot.press("ctrl+d")
        await pilot.pause()

    assert result == AgentTagModalResult(action="unset", tag=None)


async def test_modal_first_keystroke_replaces_prefill() -> None:
    async with _TestApp().run_test() as pilot:
        modal = AgentTagModal(
            target_label="agent-x",
            current_tag="name_level",
            known_tags=(),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        tag_input = modal.query_one("#agent-tag-input", _TagInput)
        assert tag_input.value == "name_level"

        # First printable keystroke replaces the selected text.
        await pilot.press("x")
        await pilot.pause()

        assert tag_input.value == "x"


async def test_modal_enter_on_prefill_emits_set_for_existing_tag() -> None:
    result: AgentTagModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTagModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTagModal(
            target_label="agent-x",
            current_tag="name_level",
            known_tags=(),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTagModalResult(action="set", tag="name_level")


async def test_modal_prefill_empty_for_bulk() -> None:
    async with _TestApp().run_test() as pilot:
        modal = AgentTagModal(
            target_label="2 marked agent(s)",
            current_tag=None,
            known_tags=(),
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        tag_input = modal.query_one("#agent-tag-input", _TagInput)
        assert tag_input.value == ""


async def test_modal_empty_enter_unsets_when_untagged() -> None:
    result: AgentTagModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTagModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTagModal(
            target_label="agent-x",
            current_tag=None,
            known_tags=(),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        tag_input = modal.query_one("#agent-tag-input", _TagInput)
        assert tag_input.value == ""

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTagModalResult(action="unset", tag=None)


async def test_modal_clear_then_enter_unsets_existing_tag() -> None:
    result: AgentTagModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTagModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTagModal(
            target_label="agent-x",
            current_tag="name_level",
            known_tags=("name_level",),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        tag_input = modal.query_one("#agent-tag-input", _TagInput)
        assert tag_input.value == "name_level"

        # Mount selects all; delete wipes the selection.
        await pilot.press("delete")
        await pilot.pause()
        assert tag_input.value == ""

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTagModalResult(action="unset", tag=None)


async def test_modal_whitespace_only_enter_unsets() -> None:
    result: AgentTagModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTagModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTagModal(
            target_label="agent-x",
            current_tag=None,
            known_tags=(),
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("space")
        await pilot.pause()

        tag_input = modal.query_one("#agent-tag-input", _TagInput)
        assert tag_input.value == " "

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTagModalResult(action="unset", tag=None)


async def test_modal_prefill_pinned_when_untagged_with_default() -> None:
    result: AgentTagModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(r: AgentTagModalResult | None) -> None:
            nonlocal result
            result = r

        modal = AgentTagModal(
            target_label="agent-x",
            current_tag=None,
            known_tags=(),
            default_tag="pinned",
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        tag_input = modal.query_one("#agent-tag-input", _TagInput)
        assert tag_input.value == "pinned"

        await pilot.press("enter")
        await pilot.pause()

    assert result == AgentTagModalResult(action="set", tag="pinned")
