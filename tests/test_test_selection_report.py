"""Unit tests for `manifest_summary_line`.

Unlike `summary_line`/`context_line`, which render a live `Selection` object,
`manifest_summary_line` renders the same facts back out of the JSON manifest
dict `tools/run_pytest` persists to disk — the shape a `check` step reads
after `run_silent` has already returned. Assertions here operate on plain
dicts rather than a synthetic repository fixture.
"""

from __future__ import annotations

from tests._test_selection_report import manifest_summary_line


def test_reports_selection_count_and_share() -> None:
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 5,
            "universe_count": 20,
            "rules_fired": [],
        }
    )

    assert (
        line
        == "scoped: selected 5 of 20 test files (25.0%; rules: none); contexts baseline missing"
    )


def test_reports_the_rules_that_fired() -> None:
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 1,
            "universe_count": 4,
            "rules_fired": ["contract-set-always", "justfile"],
        }
    )

    assert "rules: contract-set-always, justfile" in line


def test_reports_escalation_without_a_share() -> None:
    line = manifest_summary_line(
        {
            "escalated": True,
            "selected_count": 0,
            "universe_count": 20,
            "rules_fired": ["ratio-exceeded"],
        }
    )

    assert (
        line
        == "scoped: escalated to the full suite (rules: ratio-exceeded); contexts baseline missing"
    )


def test_reports_a_present_fresh_baseline() -> None:
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 1,
            "universe_count": 2,
            "rules_fired": [],
            "contexts": {"baseline": "0123456789abcdef", "stale": False},
        }
    )

    assert line.endswith("contexts baseline present")


def test_reports_a_stale_baseline() -> None:
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 1,
            "universe_count": 2,
            "rules_fired": [],
            "contexts": {"baseline": "0123456789abcdef", "stale": True},
        }
    )

    assert line.endswith("contexts baseline stale")


def test_reports_a_missing_baseline() -> None:
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 1,
            "universe_count": 2,
            "rules_fired": [],
            "contexts": {"baseline": None, "stale": False},
        }
    )

    assert line.endswith("contexts baseline missing")


def test_zero_universe_count_does_not_divide_by_zero() -> None:
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 0,
            "universe_count": 0,
            "rules_fired": [],
        }
    )

    assert "selected 0 of 0 test files (0.0%" in line
