"""Regression tests for done.json outcome classification."""

from sase.core.wait_dependency_resolution import KNOWN_DONE_OUTCOMES


def test_done_marker_writer_terminal_outcomes_are_classified() -> None:
    reachable_done_outcomes = frozenset(
        {
            "completed",
            "noop",
            "plan_rejected",
            "failed",
            "killed",
            "stopped",
            "epic_approved",
            "plan_committed",
            "epic_launch_failed",
        }
    )

    assert reachable_done_outcomes <= KNOWN_DONE_OUTCOMES
