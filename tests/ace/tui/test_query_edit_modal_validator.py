"""Pilot tests for the QueryEditModal validator + error rendering.

Phase-3 of the agents-tab structured-query feature: the agents-tab call
site passes a hint footer and a validator (``parse_agent_query``); a
failing parse keeps the modal open and renders the error inline so the
user can fix it without losing what they typed.
"""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, Label

from sase.ace.agent_query import AgentQueryParseError, parse_agent_query
from sase.ace.tui.modals.query_edit_modal import QueryEditModal


class _TestApp(App[str | None]):
    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


def _agent_query_validator(value: str) -> None:
    """Mirrors what the agents tab passes in production."""
    if value:
        parse_agent_query(value)


async def test_apply_with_invalid_query_keeps_modal_open_and_shows_error() -> None:
    """A failing validator renders the message inline; modal stays open."""
    dismissed: list[str | None] = []

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: str | None) -> None:
            dismissed.append(value)

        modal = QueryEditModal(
            current_query="bogus:value",
            title="Filter Agents",
            hint="status:foo  age>2h  attention:true",
            validator=_agent_query_validator,
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Sanity: the AgentQueryParseError this query raises has a clear msg.
        try:
            parse_agent_query("bogus:value")
        except AgentQueryParseError as e:
            expected_fragment = "bogus"
            assert expected_fragment in str(e)

        # Submit via Enter. Validator raises → modal must NOT dismiss.
        await pilot.press("enter")
        await pilot.pause()

        assert dismissed == [], "Modal should not dismiss when validator raises"
        # The error label is now visible with the parse error message.
        error = modal.query_one("#query-error", Label)
        assert error.display
        assert "bogus" in str(error.render())


async def test_apply_with_valid_query_dismisses_with_value() -> None:
    """A passing validator dismisses the modal with the typed value."""
    dismissed: list[str | None] = []

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: str | None) -> None:
            dismissed.append(value)

        modal = QueryEditModal(
            current_query="status:running",
            title="Filter Agents",
            hint="status:foo  age>2h  attention:true",
            validator=_agent_query_validator,
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

    assert dismissed == ["status:running"]


async def test_initial_error_renders_on_first_paint() -> None:
    """``initial_error`` shows up without requiring an Apply press."""
    async with _TestApp().run_test() as pilot:
        modal = QueryEditModal(
            current_query="bogus:value",
            title="Filter Agents",
            hint="status:foo",
            validator=_agent_query_validator,
            initial_error="Unknown property key: bogus",
        )
        pilot.app.push_screen(modal)
        await pilot.pause()

        error = modal.query_one("#query-error", Label)
        assert error.display
        assert "bogus" in str(error.render())


async def test_no_validator_dismisses_unconditionally() -> None:
    """Backward compat: callers without a validator still dismiss on Apply."""
    dismissed: list[str | None] = []

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: str | None) -> None:
            dismissed.append(value)

        modal = QueryEditModal(current_query="anything", title="Edit Query")
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        # Even garbage dismisses cleanly — no validator means the legacy
        # CLs-tab behavior is preserved.
        query_input = modal.query_one("#query-input", Input)
        query_input.value = "(((bad"
        await pilot.press("enter")
        await pilot.pause()

    assert dismissed == ["(((bad"]
