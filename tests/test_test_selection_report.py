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
    """A ratio escalation happens after contexts are consulted, so it reports them."""
    line = manifest_summary_line(
        {
            "escalated": True,
            "selected_count": 0,
            "universe_count": 20,
            "rules_fired": ["ratio-exceeded"],
            "contexts": {"baseline": None, "consulted": True, "stale": False},
        }
    )

    assert (
        line
        == "scoped: escalated to the full suite (rules: ratio-exceeded); contexts baseline missing"
    )


def test_a_forced_escalation_reports_contexts_as_unconsulted_not_missing() -> None:
    """A rule that forces the full suite short-circuits before the cache is read.

    Calling that a *missing* baseline tells an agent to go cache one — and
    tells `just selection-health` to charge the run with a closure-only
    exposure it never ran, when in fact it executed every test.
    """
    line = manifest_summary_line(
        {
            "escalated": True,
            "selected_count": 0,
            "universe_count": 20,
            "rules_fired": ["core-identity-changed"],
            "contexts": {"baseline": None, "consulted": False, "stale": False},
        }
    )

    assert line.endswith("contexts baseline not consulted")


def test_an_escalated_pre_schema_4_record_is_read_as_unconsulted() -> None:
    """Records written before `consulted` existed still have to read honestly."""
    line = manifest_summary_line(
        {
            "escalated": True,
            "selected_count": 0,
            "universe_count": 20,
            "rules_fired": ["justfile"],
        }
    )

    assert line.endswith("contexts baseline not consulted")


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


def test_reports_the_estimate_against_the_budget() -> None:
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 5,
            "universe_count": 20,
            "rules_fired": [],
            "max_serial_seconds": 232.0,
            "timings": {"estimated_serial_seconds": 117.6, "available": True},
        }
    )

    assert line.endswith("; est 118s/232s")


def test_says_nothing_about_a_budget_it_could_not_measure() -> None:
    """A run the ratio decided has no comparison to report."""
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 5,
            "universe_count": 20,
            "rules_fired": [],
            "max_serial_seconds": 232.0,
            "timings": {"estimated_serial_seconds": None, "available": False},
        }
    )

    assert "; est " not in line


def test_a_pre_schema_6_record_carries_no_budget() -> None:
    line = manifest_summary_line(
        {
            "escalated": False,
            "selected_count": 5,
            "universe_count": 20,
            "rules_fired": [],
            "timings": {"estimated_serial_seconds": 12.0, "available": True},
        }
    )

    assert "; est " not in line
