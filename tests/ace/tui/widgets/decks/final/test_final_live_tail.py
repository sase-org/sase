"""Tail gate, sanitization, follow selection, and tick predicates.

Live-tail coverage (epic sase-1b2, bead sase-1b2.18, ``final-live``):
the tail gate, sanitization, newest-run/latest-attempt following, the
scroll follow-pause state, and the 1 Hz tick predicates over the real
projection dataclasses.
"""

from __future__ import annotations

from types import SimpleNamespace

from sase.ace.tui.widgets.decks.final.live import (
    FINAL_LIVE_TAIL_MAX_LINES,
    FinalLiveTicker,
    LiveFollowTarget,
    _LiveFollowState,
    _format_live_elapsed,
    _is_operation_active,
    _live_tail_lines_for_operation,
    _sanitize_live_tail_lines,
    _should_live_tick,
    _tail_gate_open,
    finalization_active,
    select_live_follow_target,
)
from sase.core.finalizer_run_view import _RunViewAttempt
from tests.ace.tui.widgets.decks.final._final_live_shared import (
    NOW,
    make_active_op,
    make_run,
    make_run_instance,
)

__all__ = [
    "test_finalization_active_phases",
    "test_follow_pause_and_resume",
    "test_follow_target_is_newest_run_with_live_content",
    "test_follow_target_names_latest_attempt",
    "test_follow_target_skips_runs_without_live_content",
    "test_format_live_elapsed",
    "test_is_operation_active_treats_missing_exit_as_running",
    "test_live_lines_require_active_op_and_open_gate",
    "test_live_lines_scoped_to_follow_target",
    "test_sanitize_caps_at_twelve_lines",
    "test_sanitize_collapses_carriage_returns",
    "test_should_live_tick_scope",
    "test_tail_gate_delay_zero_renders_immediately",
    "test_tail_gate_holds_fast_ops",
    "test_tail_gate_unknown_start_stays_closed",
    "test_ticker_coalesces_in_flight_and_pause",
]


# Gate -----------------------------------------------------------------


def test_tail_gate_delay_zero_renders_immediately() -> None:
    assert _tail_gate_open(op_started_at=NOW, now=NOW, delay_seconds=0)
    assert _tail_gate_open(op_started_at=None, now=NOW, delay_seconds=0)
    assert _tail_gate_open(op_started_at=NOW, now=NOW, delay_seconds=-1.0)


def test_tail_gate_holds_fast_ops() -> None:
    assert not _tail_gate_open(op_started_at=NOW - 1.0, now=NOW, delay_seconds=5.0)
    assert _tail_gate_open(op_started_at=NOW - 5.0, now=NOW, delay_seconds=5.0)
    assert _tail_gate_open(op_started_at=NOW - 30.0, now=NOW, delay_seconds=5.0)


def test_tail_gate_unknown_start_stays_closed() -> None:
    assert not _tail_gate_open(op_started_at=None, now=NOW, delay_seconds=5.0)
    assert not _tail_gate_open(op_started_at=True, now=NOW, delay_seconds=5.0)
    assert not _tail_gate_open(op_started_at="soon", now=NOW, delay_seconds=5.0)


# Sanitize --------------------------------------------------------------


def test_sanitize_caps_at_twelve_lines() -> None:
    lines = [f"line {index}" for index in range(30)]
    assert _sanitize_live_tail_lines(lines) == [
        f"line {index}" for index in range(18, 30)
    ]
    assert FINAL_LIVE_TAIL_MAX_LINES == 12


def test_sanitize_collapses_carriage_returns() -> None:
    assert _sanitize_live_tail_lines(["first\rsecond", "plain"]) == ["second", "plain"]
    assert _sanitize_live_tail_lines("not-a-list") == []
    assert _sanitize_live_tail_lines(None) == []


# Active + follow selection ---------------------------------------------


def test_finalization_active_phases() -> None:
    assert finalization_active(SimpleNamespace(phase="declaring"))
    assert finalization_active(SimpleNamespace(phase="executing"))
    assert finalization_active({"phase": "executing"})
    assert not finalization_active(SimpleNamespace(phase="planned"))
    assert not finalization_active(SimpleNamespace(phase="settled"))
    assert not finalization_active(SimpleNamespace(phase="skipped"))
    assert not finalization_active(None)
    assert not finalization_active(SimpleNamespace())


def test_is_operation_active_treats_missing_exit_as_running() -> None:
    assert _is_operation_active(make_active_op())
    assert not _is_operation_active(make_active_op(returncode=0))
    assert not _is_operation_active(make_active_op(returncode=1))


def test_follow_target_is_newest_run_with_live_content() -> None:
    old = make_run("run-old", make_run_instance(make_active_op()))
    new = make_run("run-new", make_run_instance(make_active_op()))
    target = select_live_follow_target([old, new])
    assert target == LiveFollowTarget(run_id="run-new", attempt=1)


def test_follow_target_skips_runs_without_live_content() -> None:
    old = make_run("run-old", make_run_instance(make_active_op()))
    quiet = make_run(
        "run-quiet",
        make_run_instance(make_active_op(live_tail=[], returncode=0)),
    )
    assert select_live_follow_target([old, quiet]) == LiveFollowTarget(
        run_id="run-old", attempt=1
    )
    assert select_live_follow_target([quiet]) is None
    assert select_live_follow_target([]) is None


def test_follow_target_names_latest_attempt() -> None:
    op_new = make_active_op(attempt=2)
    item = make_run_instance(
        op_new,
        attempts=[
            _RunViewAttempt(attempt=1, status="failed"),
            _RunViewAttempt(attempt=2, status="running"),
        ],
    )
    target = select_live_follow_target([make_run("run-a", item)])
    assert target == LiveFollowTarget(run_id="run-a", attempt=2)


def test_live_lines_scoped_to_follow_target() -> None:
    op = make_active_op()
    follow = LiveFollowTarget(run_id="run-new", attempt=1)
    assert _live_tail_lines_for_operation(
        op, delay_seconds=0, now=NOW, follow=follow, run_id="run-new"
    ) == ["line one", "line two"]
    assert (
        _live_tail_lines_for_operation(
            op, delay_seconds=0, now=NOW, follow=follow, run_id="run-old"
        )
        == []
    )
    assert (
        _live_tail_lines_for_operation(
            op,
            delay_seconds=0,
            now=NOW,
            follow=LiveFollowTarget(run_id="run-new", attempt=2),
            run_id="run-new",
        )
        == []
    )
    # Unscoped ops (no attempt number) still render under the follow run.
    assert _live_tail_lines_for_operation(
        make_active_op(attempt=None),
        delay_seconds=0,
        now=NOW,
        follow=follow,
        run_id="run-new",
    ) == ["line one", "line two"]


def test_live_lines_require_active_op_and_open_gate() -> None:
    assert (
        _live_tail_lines_for_operation(
            make_active_op(returncode=0), delay_seconds=0, now=NOW
        )
        == []
    )
    assert (
        _live_tail_lines_for_operation(
            make_active_op(started_at=NOW - 1.0), delay_seconds=5.0, now=NOW
        )
        == []
    )
    assert _live_tail_lines_for_operation(
        make_active_op(started_at=NOW - 30.0), delay_seconds=5.0, now=NOW
    ) == ["line one", "line two"]


# Follow pause + tick predicates -----------------------------------------


def test_follow_pause_and_resume() -> None:
    state = _LiveFollowState()
    assert state.paused is False
    assert state.note_scroll(at_bottom=True) is False
    assert state.paused is False
    assert state.note_scroll(at_bottom=False) is False
    assert state.paused is True
    # Still scrolled up: no refresh due.
    assert state.note_scroll(at_bottom=False) is False
    # Back at the bottom: resume with one refresh.
    assert state.note_scroll(at_bottom=True) is True
    assert state.paused is False
    assert state.note_scroll(at_bottom=True) is False


def test_format_live_elapsed() -> None:
    assert _format_live_elapsed(NOW - 12.0, NOW) == "12s"
    assert _format_live_elapsed(NOW - 184.0, NOW) == "3m04s"
    assert _format_live_elapsed(None, NOW) is None
    assert _format_live_elapsed(NOW + 5.0, NOW) is None


def test_should_live_tick_scope() -> None:
    good = {
        "visible": True,
        "active": True,
        "navigating": False,
        "typing": False,
        "paused": False,
        "in_flight": False,
    }
    assert _should_live_tick(**good) is True
    for key in good:
        blocked = dict(good)
        blocked[key] = not blocked[key] if key in ("visible", "active") else True
        if key in ("visible", "active"):
            assert _should_live_tick(**blocked) is False, key
        else:
            assert _should_live_tick(**blocked) is False, key


def test_ticker_coalesces_in_flight_and_pause() -> None:
    ticker = FinalLiveTicker()
    assert (
        ticker.want_tick(visible=True, active=True, navigating=False, typing=False)
        is True
    )
    assert ticker.begin() is True
    assert ticker.begin() is False
    assert (
        ticker.want_tick(visible=True, active=True, navigating=False, typing=False)
        is False
    )
    ticker.finish()
    assert (
        ticker.want_tick(visible=True, active=True, navigating=False, typing=False)
        is True
    )
    assert ticker.note_scroll(at_bottom=False) is False
    assert (
        ticker.want_tick(visible=True, active=True, navigating=False, typing=False)
        is False
    )
    assert ticker.note_scroll(at_bottom=True) is True
