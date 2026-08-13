"""Tests for the Agents-tab wait modal inputs and validation."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Input, OptionList

from sase.ace.tui.modals.wait_modal import (
    WaitAgentCandidate,
    WaitModal,
    WaitModalResult,
    _active_fragment,
    _candidate_option,
    _prefill_time_token,
    _replace_active_fragment,
    _validate_priority_token,
    _validate_runners_token,
    _validate_time_token,
)
from tests.ace.tui._wait_modal_helpers import (
    WaitModalTestApp as _TestApp,
    candidate as _candidate,
)


def _style_at(text: Text, position: int) -> str | None:
    for span in reversed(text.spans):
        if span.start <= position < span.end:
            return str(span.style)
    return str(text.style) if text.style else None


def test_active_fragment_uses_text_after_last_comma() -> None:
    assert _active_fragment("planner, cod") == "cod"
    assert _active_fragment("planner, ") == ""


def test_replace_active_fragment_appends_comma_for_multi_select() -> None:
    assert _replace_active_fragment("", "planner") == "planner, "
    assert _replace_active_fragment("planner, cod", "coder") == "planner, coder, "


def test_wait_candidate_colors_only_compact_tribe_portion() -> None:
    configured = WaitAgentCandidate(
        wait_name="planner",
        label="planner",
        status="RUNNING",
        role="root",
        tribe="@epic",
    )
    fallback = WaitAgentCandidate(
        wait_name="reviewer",
        label="reviewer",
        status="DONE",
        tribe="@unknown",
    )

    configured_text = _candidate_option(
        configured,
        0,
        tribe_colors={"epic": "#123456"},
    ).prompt
    fallback_text = _candidate_option(
        fallback,
        1,
        tribe_colors={"unknown": "#FFD75F"},
    ).prompt

    assert isinstance(configured_text, Text)
    assert isinstance(fallback_text, Text)
    assert (
        _style_at(
            configured_text,
            configured_text.plain.index("root"),
        )
        == "dim"
    )
    assert (
        _style_at(
            configured_text,
            configured_text.plain.index("@epic"),
        )
        == "dim #123456"
    )
    assert (
        _style_at(
            fallback_text,
            fallback_text.plain.index("@unknown"),
        )
        == "dim #FFD75F"
    )


def test_time_validation_states() -> None:
    empty = _validate_time_token("")
    assert empty.valid is True
    assert empty.token is None

    duration = _validate_time_token("1h30m")
    assert duration.valid is True
    assert duration.token == "1h30m"
    assert "waits 1h30m" in duration.message

    absolute = _validate_time_token("2359")
    assert absolute.valid is True
    assert absolute.token == "2359"
    assert absolute.message.startswith("until ")

    invalid = _validate_time_token("review")
    assert invalid.valid is False


def test_time_prefill_round_trips_duration_and_absolute() -> None:
    assert _prefill_time_token(300.0, None) == "5m"
    assert _prefill_time_token(90.0, None) == "1m30s"
    assert _prefill_time_token(None, "2030-04-15T09:00:00") == "300415/0900"


def test_runners_validation_accepts_zero_and_rejects_non_integers() -> None:
    default = _validate_runners_token("")
    assert default.valid is True
    assert default.value is None

    barrier = _validate_runners_token("0")
    assert barrier.valid is True
    assert barrier.value == 0
    assert "drain barrier" in barrier.message

    assert _validate_runners_token("-1").valid is False
    assert _validate_runners_token("1.5").valid is False


def test_priority_validation_accepts_zero_and_rejects_non_integers() -> None:
    default = _validate_priority_token("")
    assert default.valid is True
    assert default.value is None
    assert "default is 10" in default.message

    highest = _validate_priority_token("0")
    assert highest.valid is True
    assert highest.value == 0
    assert "lower values start first" in highest.message

    assert _validate_priority_token("-1").valid is False
    assert _validate_priority_token("1.5").valid is False


async def test_modal_filters_and_accepts_candidate_with_tab() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(candidates=[_candidate("planner"), _candidate("coder")])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        agents_input.value = "cod"
        await pilot.pause()

        option_list = modal.query_one("#agent-completion", OptionList)
        assert option_list.option_count == 1

        await pilot.press("tab")
        await pilot.pause()

        assert agents_input.value == "coder, "

        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(agents=["coder"], time_token=None, run_now=False)


async def test_modal_enter_with_time_only_returns_time_wait() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(candidates=[_candidate("planner")])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        time_input = modal.query_one("#time-input", Input)
        time_input.value = "5m"
        time_input.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(agents=[], time_token="5m", run_now=False)


async def test_modal_invalid_time_does_not_dismiss() -> None:
    dismiss_count = 0

    async with _TestApp().run_test() as pilot:

        def on_dismiss(_value: WaitModalResult | None) -> None:
            nonlocal dismiss_count
            dismiss_count += 1

        modal = WaitModal(candidates=[_candidate("planner")])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        time_input = modal.query_one("#time-input", Input)
        time_input.value = "review"
        time_input.focus()
        await pilot.pause()

        await pilot.press("enter")
        await pilot.pause()

        assert time_input.has_focus

    assert dismiss_count == 0


async def test_modal_returns_explicit_runner_threshold() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_wait_runners=0)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        runners_input = modal.query_one("#runners-input", Input)
        assert runners_input.value == "0"
        runners_input.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(agents=[], time_token=None, runners=0)


async def test_modal_prefills_and_returns_explicit_priority() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_wait_priority=20)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        assert priority_input.value == "20"
        priority_input.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(agents=[], time_token=None, priority=20)


async def test_modal_invalid_priority_does_not_dismiss() -> None:
    dismiss_count = 0

    async with _TestApp().run_test() as pilot:

        def on_dismiss(_value: WaitModalResult | None) -> None:
            nonlocal dismiss_count
            dismiss_count += 1

        modal = WaitModal()
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        priority_input.value = "-1"
        priority_input.focus()
        await pilot.press("enter")
        await pilot.pause()

        assert priority_input.has_focus

    assert dismiss_count == 0


async def test_modal_marks_cleared_priority_for_update() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_wait_priority=20)
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        priority_input.value = ""
        priority_input.focus()
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        update_priority=True,
        run_now=True,
    )


async def test_modal_focus_swaps_completion_list_but_time_leaves_it_unchanged() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(candidates=[_candidate("planner")])
        pilot.app.push_screen(modal)
        await pilot.pause()

        agent_list = modal.query_one("#agent-completion", OptionList)
        bead_list = modal.query_one("#bead-completion", OptionList)
        assert agent_list.display is True
        assert bead_list.display is False

        modal.query_one("#beads-input", Input).focus()
        await pilot.pause()
        assert agent_list.display is False
        assert bead_list.display is True

        modal.query_one("#time-input", Input).focus()
        await pilot.pause()
        assert agent_list.display is False
        assert bead_list.display is True


async def test_modal_tab_falls_through_to_focus_next_without_highlight() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        assert agents_input.has_focus

        await pilot.press("tab")
        await pilot.pause()

        assert not agents_input.has_focus


async def test_modal_ctrl_j_moves_from_agents_to_beads_input() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        beads_input = modal.query_one("#beads-input", Input)
        assert agents_input.has_focus

        await pilot.press("ctrl+j")
        await pilot.pause()

        assert beads_input.has_focus


async def test_modal_ctrl_j_wraps_from_priority_to_agents_input() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        priority_input = modal.query_one("#priority-input", Input)
        priority_input.focus()
        await pilot.pause()

        await pilot.press("ctrl+j")
        await pilot.pause()

        assert agents_input.has_focus


async def test_modal_ctrl_k_wraps_from_agents_to_priority_input() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        assert modal.query_one("#agents-input", Input).has_focus

        await pilot.press("ctrl+k")
        await pilot.pause()

        assert priority_input.has_focus


async def test_modal_ctrl_k_does_not_delete_focused_input_text() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal()
        pilot.app.push_screen(modal)
        await pilot.pause()

        agents_input = modal.query_one("#agents-input", Input)
        priority_input = modal.query_one("#priority-input", Input)
        agents_input.value = "planner"
        agents_input.cursor_position = 3
        await pilot.pause()

        await pilot.press("ctrl+k")
        await pilot.pause()

        assert priority_input.has_focus
        assert agents_input.value == "planner"


async def test_modal_ctrl_j_from_agent_completion_moves_to_beads_input() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(candidates=[_candidate("planner")])
        pilot.app.push_screen(modal)
        await pilot.pause()

        option_list = modal.query_one("#agent-completion", OptionList)
        beads_input = modal.query_one("#beads-input", Input)
        option_list.focus()
        await pilot.pause()

        await pilot.press("ctrl+j")
        await pilot.pause()

        assert beads_input.has_focus


async def test_modal_field_navigation_places_cursor_at_end() -> None:
    async with _TestApp().run_test() as pilot:
        modal = WaitModal(current_wait_priority=20)
        pilot.app.push_screen(modal)
        await pilot.pause()

        priority_input = modal.query_one("#priority-input", Input)
        assert priority_input.value == "20"

        await pilot.press("ctrl+k")
        await pilot.pause()

        assert priority_input.has_focus
        assert priority_input.cursor_position == len(priority_input.value)
