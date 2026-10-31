"""Wait modal ``turn=<agent>`` authoring and follow-toggle behavior."""

from __future__ import annotations

from textual.widgets import Input

from sase.ace.tui.modals.wait_modal import WaitModal, WaitModalResult
from sase.ace.tui.modals.wait_modal_values import (
    parse_agents_field,
    parse_agents_field_lenient,
    parse_agents_value,
)
from sase.wait_spec import WaitSpecError
from tests.ace.tui._wait_modal_helpers import WaitModalTestApp as _TestApp
from tests.ace.tui._wait_modal_helpers import candidate as _candidate


def test_parse_agents_field_accepts_turn_entries() -> None:
    session, turns = parse_agents_field("planner, turn=16h")
    assert session == ["planner"]
    assert turns == ["16h"]
    assert parse_agents_value("planner, turn=16h") == ["planner", "16h"]


def test_parse_agents_field_rejects_bead_and_hood() -> None:
    try:
        parse_agents_field("planner, bead=sase-1")
    except WaitSpecError as exc:
        assert "bead=" in str(exc)
    else:
        raise AssertionError("expected WaitSpecError")


def test_parse_agents_field_lenient_skips_unknown_keys() -> None:
    session, turns = parse_agents_field_lenient("planner, turn=, hood=x, turn=16h")
    assert session == ["planner"]
    assert turns == ["16h"]


async def test_modal_prefills_and_applies_turn_entries() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(
            current_waiting_for=["planner", "16h"],
            current_turn_target_agents=["16h"],
        )
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        assert agents_input.value == "planner, turn=16h"
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=["planner", "16h"],
        time_token=None,
        run_now=False,
        follow_mode="off",
        epic_follow_agents=(),
        turn_agents=["16h"],
    )


async def test_modal_turn_only_disables_follow_toggle() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(
            current_waiting_for=["16h"],
            current_turn_target_agents=["16h"],
        )
        pilot.app.push_screen(modal)
        await pilot.pause()
        reason = modal._follow_disabled_reason()
        assert reason is not None
        assert "turn targets" in reason


async def test_modal_invalid_keyed_entry_does_not_dismiss() -> None:
    dismiss_count = 0

    async with _TestApp().run_test() as pilot:

        def on_dismiss(_value: WaitModalResult | None) -> None:
            nonlocal dismiss_count
            dismiss_count += 1

        modal = WaitModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        agents_input.value = "planner, bead=sase-1"
        agents_input.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert agents_input.has_focus

    assert dismiss_count == 0


async def test_modal_turn_prefix_completion_preserves_turn_key() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(candidates=[_candidate("planner"), _candidate("coder")])
        pilot.app.push_screen(modal)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        agents_input.value = "turn=cod"
        agents_input.cursor_position = len(agents_input.value)
        modal._refresh_completion()
        accepted = modal._accept_candidate_index(0)
        assert accepted is True
        assert agents_input.value.startswith("turn=")
        assert "coder" in agents_input.value
