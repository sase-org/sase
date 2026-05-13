"""Tests for agent runtime notification formatting."""

from datetime import UTC, datetime

from sase.axe.run_agent_runtime import format_agent_run_runtime
from sase.core.time import get_timezone


def test_format_agent_run_runtime_uses_run_started_at_over_launch_timestamp() -> None:
    runtime = format_agent_run_runtime(
        launch_timestamp_suffix="20260425140000",
        run_started_at="2026-04-25T18:10:00+00:00",
        completion_time=datetime(2026, 4, 25, 18, 14, 32, tzinfo=UTC),
    )

    assert runtime == "4m32s"


def test_format_agent_run_runtime_falls_back_to_launch_timestamp() -> None:
    tz = get_timezone()

    runtime = format_agent_run_runtime(
        launch_timestamp_suffix="20260425140000",
        run_started_at=None,
        completion_time=datetime(2026, 4, 25, 14, 5, 0, tzinfo=tz),
    )

    assert runtime == "5m"


def test_format_agent_run_runtime_omits_malformed_run_started_at() -> None:
    runtime = format_agent_run_runtime(
        launch_timestamp_suffix="20260425140000",
        run_started_at="not-a-time",
        completion_time=datetime(2026, 4, 25, 18, 14, 32, tzinfo=UTC),
    )

    assert runtime is None


def test_format_agent_run_runtime_omits_missing_or_malformed_launch_timestamp() -> None:
    assert (
        format_agent_run_runtime(
            launch_timestamp_suffix=None,
            run_started_at=None,
            completion_time=datetime(2026, 4, 25, 18, 14, 32, tzinfo=UTC),
        )
        is None
    )
    assert (
        format_agent_run_runtime(
            launch_timestamp_suffix="bad",
            run_started_at=None,
            completion_time=datetime(2026, 4, 25, 18, 14, 32, tzinfo=UTC),
        )
        is None
    )
