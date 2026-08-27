"""Regression tests for done.json outcome classification."""

from sase.core.dismissed_agent_completion import GATE_OUTCOME, GATE_SUCCESS_STATES
from sase.core.wait_dependency_resolution import KNOWN_DONE_OUTCOMES
from sase.gate_shell.settlement import _done_marker
from sase.gate_shell.state import GATE_STATE_BUCKETS


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
            "monitored",
            "gated",
        }
    )

    assert reachable_done_outcomes <= KNOWN_DONE_OUTCOMES


def test_gate_outcome_classification_matches_gate_state_contract() -> None:
    done_bucket = frozenset(
        state for state, bucket in GATE_STATE_BUCKETS.items() if bucket == "Done"
    )

    assert GATE_SUCCESS_STATES == done_bucket
    assert (
        _done_marker({"artifacts_dir": ""}, gate_state="answered", reason=None)[
            "outcome"
        ]
        == GATE_OUTCOME
    )
