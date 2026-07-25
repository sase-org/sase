"""Tests for the Agents-tab wait modal."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.widgets import Input, OptionList, Static

from sase.ace.tui.modals.wait_modal import (
    WaitAgentCandidate,
    WaitModal,
    WaitModalResult,
    _active_fragment,
    _prefill_time_token,
    _replace_active_fragment,
    _validate_priority_token,
    _validate_runners_token,
    _validate_time_token,
)


class _TestApp(App[WaitModalResult | None]):
    """Minimal app harness for wait modal tests."""

    def compose(self) -> ComposeResult:
        yield from ()


def _candidate(
    wait_name: str,
    *,
    label: str | None = None,
    status: str = "RUNNING",
) -> WaitAgentCandidate:
    return WaitAgentCandidate(
        wait_name=wait_name,
        label=label or wait_name,
        status=status,
        model="claude / sonnet",
        start_time="12:03",
        duration="2m",
    )


def test_active_fragment_uses_text_after_last_comma() -> None:
    assert _active_fragment("planner, cod") == "cod"
    assert _active_fragment("planner, ") == ""


def test_replace_active_fragment_appends_comma_for_multi_select() -> None:
    assert _replace_active_fragment("", "planner") == "planner, "
    assert _replace_active_fragment("planner, cod", "coder") == "planner, coder, "


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


async def test_modal_displays_and_preserves_read_only_bead_waits() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_waiting_for_beads=["sase-87.2", "sase-87.3"])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        assert modal.query_one("#wait-beads-summary", Static).render().plain == (
            "sase-87.2, sase-87.3"
        )
        await pilot.press("enter")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        beads=["sase-87.2", "sase-87.3"],
    )


async def test_modal_run_now_cancels_bead_waits() -> None:
    result: WaitModalResult | None = None

    async with _TestApp().run_test() as pilot:

        def on_dismiss(value: WaitModalResult | None) -> None:
            nonlocal result
            result = value

        modal = WaitModal(current_waiting_for_beads=["sase-87.2"])
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()
        await pilot.press("ctrl+r")
        await pilot.pause()

    assert result == WaitModalResult(
        agents=[],
        time_token=None,
        beads=[],
        run_now=True,
    )
