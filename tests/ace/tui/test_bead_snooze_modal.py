"""Contracts for the Beads-pane snooze picker and its mutation action."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Input, Label

from sase.ace.tui.actions.artifacts_beads import ArtifactsBeadsActionsMixin
from sase.ace.tui.modals.bead_snooze_modal import (
    CANCEL_BEAD_SNOOZE,
    BeadSnoozeChoice,
    BeadSnoozeModal,
    BeadSnoozeRequest,
    _next_morning,
    _bead_snooze_modal_title,
)
from sase.ace.tui.widgets.artifacts.beads_list import BeadRow
from sase.bead.model import Issue, IssueType, SnoozeRecord, Status
from sase.core.time import get_timezone


def _task(
    *,
    status: Status = Status.READY,
    issue_type: IssueType = IssueType.TASK,
    snooze: SnoozeRecord | None = None,
) -> Issue:
    return Issue(
        "alpha-a1",
        "Deferrable work",
        issue_type=issue_type,
        status=status,
        snooze=snooze,
    )


def _snooze_record(until: str = "2099-01-01T09:00:00-05:00") -> SnoozeRecord:
    return SnoozeRecord(
        until=until,
        snoozed_at="2026-08-01T09:00:00-04:00",
        snoozed_by="owner@example.com",
        reason="waiting on upstream",
    )


def _modal(issue: Issue) -> BeadSnoozeModal:
    """Return a modal whose dismissal is captured instead of performed."""
    modal = BeadSnoozeModal(issue)
    modal.dismiss = MagicMock()  # type: ignore[method-assign,assignment]
    # Presets read the reason field on the way out; an unmounted modal has no
    # widgets, so the tests that care about the reason mount for real.
    modal._annotation = None
    return modal


def test_presets_resolve_to_future_wake_times() -> None:
    modal = _modal(_task())
    now = datetime.now(get_timezone())

    modal.action_preset_1()

    (request,), _ = modal.dismiss.call_args
    assert isinstance(request, BeadSnoozeRequest)
    wake = datetime.fromisoformat(request.until)
    assert timedelta(hours=3, minutes=59) < wake - now < timedelta(hours=4, minutes=1)
    assert request.plus_ones is None
    assert request.reason == ""


@pytest.mark.parametrize(
    ("preset", "lower", "upper"),
    [
        (3, timedelta(days=2, hours=23), timedelta(days=3, hours=1)),
        (4, timedelta(days=6, hours=23), timedelta(days=7, hours=1)),
    ],
)
def test_day_presets_span_their_advertised_range(
    preset: int, lower: timedelta, upper: timedelta
) -> None:
    modal = _modal(_task())
    now = datetime.now(get_timezone())

    getattr(modal, f"action_preset_{preset}")()

    (request,), _ = modal.dismiss.call_args
    assert lower < datetime.fromisoformat(request.until) - now < upper


def test_tomorrow_morning_preset_wakes_at_nine_the_next_day() -> None:
    modal = _modal(_task())

    modal.action_preset_2()

    (request,), _ = modal.dismiss.call_args
    wake = datetime.fromisoformat(request.until)
    assert (wake.hour, wake.minute) == (9, 0)
    assert wake.date() == (datetime.now(get_timezone()).date() + timedelta(days=1))


def test__next_morning_always_skips_to_the_following_day() -> None:
    tz = get_timezone()
    assert _next_morning(datetime(2026, 4, 21, 6, 0, tzinfo=tz)) == datetime(
        2026, 4, 22, 9, 0, tzinfo=tz
    )
    assert _next_morning(datetime(2026, 4, 21, 22, 0, tzinfo=tz)) == datetime(
        2026, 4, 22, 9, 0, tzinfo=tz
    )


def test_cancel_choice_exists_only_in_resnooze_mode() -> None:
    fresh = _modal(_task())
    fresh.action_choose("x")
    fresh.dismiss.assert_not_called()

    resnoozing = _modal(_task(status=Status.SNOOZED, snooze=_snooze_record()))
    resnoozing.action_choose("x")
    resnoozing.dismiss.assert_called_once_with(CANCEL_BEAD_SNOOZE)


def test_title_names_the_wake_time_a_resnooze_replaces() -> None:
    assert _bead_snooze_modal_title(_task()) == "Snooze alpha-a1"
    title = _bead_snooze_modal_title(
        _task(status=Status.SNOOZED, snooze=_snooze_record())
    )
    assert title.startswith("Re-snooze alpha-a1 · until ")


class _Host(App[None]):
    """Minimal host app for mounting the modal in tests."""

    ENABLE_COMMAND_PALETTE = False

    def compose(self) -> ComposeResult:
        yield from ()


async def test_custom_field_accepts_the_shared_duration_and_reason() -> None:
    result: BeadSnoozeChoice | None = None

    async with _Host().run_test() as pilot:

        def on_dismiss(value: BeadSnoozeChoice | None) -> None:
            nonlocal result
            result = value

        modal = BeadSnoozeModal(_task())
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#bead-snooze-annotation-input", Input).value = "blocked"
        await pilot.press("c")
        await pilot.pause()
        modal.query_one("#bead-snooze-custom-input", Input).value = "3d +2"
        await pilot.press("enter")
        await pilot.pause()

    assert isinstance(result, BeadSnoozeRequest)
    assert result.plus_ones == 2
    assert result.reason == "blocked"


async def test_reason_field_rides_along_with_a_preset() -> None:
    result: BeadSnoozeChoice | None = None

    async with _Host().run_test() as pilot:

        def on_dismiss(value: BeadSnoozeChoice | None) -> None:
            nonlocal result
            result = value

        modal = BeadSnoozeModal(_task())
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        modal.query_one("#bead-snooze-annotation-input", Input).value = "  later  "
        await pilot.press("1")
        await pilot.pause()

    assert isinstance(result, BeadSnoozeRequest)
    assert result.reason == "later"


async def test_escape_leaves_the_reason_field_without_cancelling() -> None:
    """Blurring the reason keeps the typed text and re-arms the preset keys."""
    result: BeadSnoozeChoice | None = None

    async with _Host().run_test() as pilot:

        def on_dismiss(value: BeadSnoozeChoice | None) -> None:
            nonlocal result
            result = value

        modal = BeadSnoozeModal(_task())
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("r")
        await pilot.pause()
        reason = modal.query_one("#bead-snooze-annotation-input", Input)
        assert pilot.app.focused is reason
        reason.value = "blocked"

        await pilot.press("escape")
        await pilot.pause()
        assert reason.value == "blocked"
        assert result is None

        await pilot.press("1")
        await pilot.pause()

    assert isinstance(result, BeadSnoozeRequest)
    assert result.reason == "blocked"


async def test_unparsable_custom_duration_keeps_the_modal_open() -> None:
    dismissed = False

    async with _Host().run_test() as pilot:

        def on_dismiss(_value: BeadSnoozeChoice | None) -> None:
            nonlocal dismissed
            dismissed = True

        modal = BeadSnoozeModal(_task())
        pilot.app.push_screen(modal, callback=on_dismiss)
        await pilot.pause()

        await pilot.press("c")
        await pilot.pause()
        modal.query_one("#bead-snooze-custom-input", Input).value = "next tuesday"
        await pilot.press("enter")
        await pilot.pause()

        error = modal.query_one("#bead-snooze-custom-error", Label)
        assert not error.has_class("hidden")

    assert not dismissed


_NOT_SNOOZABLE = "Only open, ready, and already snoozed task beads can be snoozed"


def _host_with_selection(row: BeadRow) -> SimpleNamespace:
    pane = SimpleNamespace(request_refresh=Mock())
    host = SimpleNamespace(
        _selected_bead=lambda: (pane, row),
        _notify_beads=Mock(),
        push_screen=Mock(),
        _submit_bead_mutation=Mock(),
    )
    return host


@pytest.mark.parametrize(
    ("issue", "message"),
    [
        (_task(issue_type=IssueType.PLAN), "Only task beads can be snoozed"),
        (_task(status=Status.IN_PROGRESS), _NOT_SNOOZABLE),
        (_task(status=Status.CLOSED), _NOT_SNOOZABLE),
    ],
)
def test_snooze_action_refuses_beads_the_store_would_reject(
    issue: Issue, message: str
) -> None:
    host = _host_with_selection(BeadRow("task", f"task:{issue.id}", "alpha", issue))

    ArtifactsBeadsActionsMixin.action_beads_snooze(host)

    host.push_screen.assert_not_called()
    assert host._notify_beads.call_args.args[0] == message


def test_snooze_action_opens_the_picker_for_a_snoozable_task() -> None:
    issue = _task(status=Status.OPEN)
    host = _host_with_selection(BeadRow("task", f"task:{issue.id}", "alpha", issue))

    ArtifactsBeadsActionsMixin.action_beads_snooze(host)

    (modal, _callback), _ = host.push_screen.call_args
    assert isinstance(modal, BeadSnoozeModal)


def test_snooze_submission_settles_the_triage_gate_and_commits_a_snooze() -> None:
    issue = _task()
    row = BeadRow("task", f"task:{issue.id}", "alpha", issue)
    host = _host_with_selection(row)
    project = Mock()

    ArtifactsBeadsActionsMixin._submit_bead_snooze(
        host,
        SimpleNamespace(),
        row,
        BeadSnoozeRequest(until="2099-01-01T09:00:00-05:00", plus_ones=2, reason="why"),
    )

    kwargs = host._submit_bead_mutation.call_args.kwargs
    assert kwargs["commit_operation"] == "snooze"
    assert kwargs["settle_triage_reason"] == "bead_status_changed"
    kwargs["mutation"](project)
    assert project.snooze.call_args.kwargs["until"] == "2099-01-01T09:00:00-05:00"
    assert project.snooze.call_args.kwargs["plus_ones"] == 2
    assert project.snooze.call_args.kwargs["reason"] == "why"


def test_cancel_choice_routes_to_the_wake_mutation() -> None:
    issue = _task(status=Status.SNOOZED, snooze=_snooze_record())
    row = BeadRow("task", f"task:{issue.id}", "alpha", issue)
    host = _host_with_selection(row)
    host._submit_bead_cancel_snooze = Mock()
    pane = SimpleNamespace()

    ArtifactsBeadsActionsMixin._submit_bead_snooze(host, pane, row, CANCEL_BEAD_SNOOZE)

    host._submit_bead_mutation.assert_not_called()
    host._submit_bead_cancel_snooze.assert_called_once_with(pane, row)


def test_waking_a_bead_commits_a_snooze_cancel_and_leaves_gates_alone() -> None:
    issue = _task(status=Status.SNOOZED, snooze=_snooze_record())
    row = BeadRow("task", f"task:{issue.id}", "alpha", issue)
    host = _host_with_selection(row)
    project = Mock()

    ArtifactsBeadsActionsMixin._submit_bead_cancel_snooze(host, SimpleNamespace(), row)

    kwargs = host._submit_bead_mutation.call_args.kwargs
    assert kwargs["commit_operation"] == "snooze_cancel"
    # The bead keeps its pending BeadSnooze gate until the reconciler swaps it:
    # only the triage gate has a direct settle path, and cancelling the wrong
    # kind here would race the reconciler that owns it.
    assert kwargs.get("settle_triage_reason") is None
    kwargs["mutation"](project)
    project.cancel_snooze.assert_called_once()


@pytest.mark.parametrize(
    ("issue", "expected"),
    [
        (_task(status=Status.READY), "snooze"),
        (_task(status=Status.OPEN), "snooze"),
        (_task(status=Status.SNOOZED, snooze=_snooze_record()), "re-snooze"),
        (_task(status=Status.IN_PROGRESS), None),
        (_task(issue_type=IssueType.PLAN), None),
    ],
)
def test_footer_offers_snooze_only_where_the_action_would_work(
    issue: Issue, expected: str | None
) -> None:
    from sase.ace.tui.widgets.artifacts.beads_navigation import BeadsNavigationMixin

    row = BeadRow("task", f"task:{issue.id}", "alpha", issue)
    pane = SimpleNamespace(selected_row=lambda: row, _snapshot=None)

    entries = dict(BeadsNavigationMixin.conditional_footer_entries(pane))

    assert entries.get("beads_snooze") == expected
