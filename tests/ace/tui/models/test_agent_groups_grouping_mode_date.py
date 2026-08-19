"""GroupingMode: date bucketing."""

from __future__ import annotations

from datetime import datetime

from sase.ace.tui.models.agent_groups import _date_bucket_for
from sase.ace.tui.models.agent_groups._buckets import date_anchor_time

from ._agent_groups_helpers import _NOW, _agent


def test_date_bucket_today() -> None:
    a = _agent(start_time=datetime(2026, 4, 26, 9, 30, 0))
    assert _date_bucket_for(a, _NOW) == "Today"


def test_date_bucket_yesterday() -> None:
    a = _agent(start_time=datetime(2026, 4, 25, 15, 0, 0))
    assert _date_bucket_for(a, _NOW) == "Yesterday"


def test_date_bucket_yesterday_at_midnight_rollover() -> None:
    """An agent that ran at 23:59 the prior day still buckets as Yesterday."""
    a = _agent(start_time=datetime(2026, 4, 25, 23, 59, 59))
    just_after_midnight = datetime(2026, 4, 26, 0, 0, 1)
    assert _date_bucket_for(a, just_after_midnight) == "Yesterday"


def test_date_bucket_this_week_within_six_days() -> None:
    a = _agent(start_time=datetime(2026, 4, 22, 12, 0, 0))
    assert _date_bucket_for(a, _NOW) == "This Week"


def test_date_bucket_earlier_past_week() -> None:
    a = _agent(start_time=datetime(2026, 4, 18, 12, 0, 0))
    assert _date_bucket_for(a, _NOW) == "Earlier"


def test_date_bucket_missing_start_time_lands_in_earlier() -> None:
    a = _agent(start_time=None)
    assert _date_bucket_for(a, _NOW) == "Earlier"


def test_date_bucket_uses_local_calendar_date_not_24h_window() -> None:
    """A 23h-old start that crossed midnight is Yesterday, not Today."""
    a = _agent(start_time=datetime(2026, 4, 25, 13, 0, 0))
    now = datetime(2026, 4, 26, 12, 0, 0)
    assert _date_bucket_for(a, now) == "Yesterday"


def test_date_bucket_terminal_agent_uses_stop_time_not_start_time() -> None:
    a = _agent(
        status="DONE",
        start_time=datetime(2026, 4, 24, 18, 9, 0),
        stop_time=datetime(2026, 4, 25, 10, 56, 0),
    )
    assert _date_bucket_for(a, _NOW) == "Yesterday"


def test_date_bucket_terminal_agent_that_finished_today_is_today() -> None:
    a = _agent(
        status="DONE",
        start_time=datetime(2026, 4, 25, 13, 8, 0),
        stop_time=datetime(2026, 4, 26, 0, 10, 0),
    )
    assert _date_bucket_for(a, _NOW) == "Today"


def test_date_bucket_terminal_agent_without_stop_time_falls_back_to_start_time() -> (
    None
):
    a = _agent(
        status="DONE",
        start_time=datetime(2026, 4, 25, 15, 0, 0),
        stop_time=None,
    )
    assert _date_bucket_for(a, _NOW) == "Yesterday"


def test_date_bucket_running_agent_still_uses_start_time() -> None:
    a = _agent(
        status="RUNNING",
        start_time=datetime(2026, 4, 25, 23, 0, 0),
        stop_time=None,
    )
    assert _date_bucket_for(a, _NOW) == "Yesterday"


def test_date_bucket_terminal_agent_without_start_time_uses_stop_time() -> None:
    a = _agent(
        status="DONE",
        start_time=None,
        stop_time=datetime(2026, 4, 26, 9, 0, 0),
    )
    assert _date_bucket_for(a, _NOW) == "Today"


def test_date_bucket_settled_monitor_with_custom_stop_label_uses_stop_time() -> None:
    start = datetime(2026, 4, 24, 18, 9, 0)
    stop = datetime(2026, 4, 25, 10, 56, 0)
    a = _agent(
        status="TESTED",
        start_time=start,
        stop_time=stop,
        agent_family_role="monitor",
        role_suffix="--mon",
    )
    a.monitor_state = "completed"

    assert date_anchor_time(a) == stop
    assert _date_bucket_for(a, _NOW) == "Yesterday"


def test_date_bucket_running_monitor_uses_start_time() -> None:
    start = datetime(2026, 4, 25, 15, 0, 0)
    a = _agent(
        status="TESTING",
        start_time=start,
        stop_time=datetime(2026, 4, 26, 11, 0, 0),
        agent_family_role="monitor",
        role_suffix="--mon",
    )
    a.monitor_state = "running"

    assert date_anchor_time(a) == start
    assert _date_bucket_for(a, _NOW) == "Yesterday"
