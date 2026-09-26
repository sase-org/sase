"""Unit tests for :func:`sase.monitor_state.monitor_lane_status_bucket`."""

from __future__ import annotations

import pytest

from sase.monitor_state import monitor_lane_status_bucket


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        # Running monitors are not terminal: own bucket stands.
        (
            {"monitor_state": "running", "own_bucket": "Running"},
            "Running",
        ),
        # A launched continuation keeps the lane in progress.
        (
            {
                "monitor_state": "failed",
                "own_bucket": "Failed",
                "followup_outcome": "launched",
            },
            "Running",
        ),
        (
            {
                "monitor_state": "failed",
                "own_bucket": "Failed",
                "followup_outcome": "launched-degraded",
            },
            "Running",
        ),
        # A pending continuation (next_action set, no outcome yet) is Running.
        (
            {
                "monitor_state": "failed",
                "own_bucket": "Failed",
                "next_action": "continue",
            },
            "Running",
        ),
        # A continuation that failed to launch is a real failure.
        (
            {
                "monitor_state": "failed",
                "own_bucket": "Failed",
                "followup_outcome": "launched",
                "followup_error": "boom",
            },
            "Failed",
        ),
        # Host completion settles the lane as Done.
        (
            {
                "monitor_state": "completed",
                "own_bucket": "Done",
                "followup_outcome": "host-completed",
            },
            "Done",
        ),
        # A launched continuation outranks even a Done monitor.
        (
            {
                "monitor_state": "completed",
                "own_bucket": "Done",
                "followup_outcome": "launched",
            },
            "Running",
        ),
        # Lost monitors never count as pending: no follow-up lane.
        (
            {
                "monitor_state": "lost",
                "own_bucket": "Failed",
                "next_action": "continue",
            },
            "Failed",
        ),
        # Stopped monitors never count as pending: own Done bucket stands.
        (
            {
                "monitor_state": "stopped",
                "own_bucket": "Done",
                "next_action": "continue",
            },
            "Done",
        ),
        # Legacy monitors without continuation metadata keep their bucket.
        (
            {"monitor_state": "failed", "own_bucket": "Failed"},
            "Failed",
        ),
    ],
)
def test_monitor_lane_status_bucket_rules(kwargs: dict, expected: str) -> None:
    assert monitor_lane_status_bucket(**kwargs) == expected


def test_monitor_lane_status_bucket_host_completion_status() -> None:
    assert (
        monitor_lane_status_bucket(
            "failed",
            "Failed",
            host_completion_status="completed_by_host",
        )
        == "Done"
    )
