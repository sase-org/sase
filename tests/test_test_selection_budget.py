"""Unit tests for the two gates that decide a selection is too big.

The file-count ratio and the serial-runtime budget, including which of the two
decides when a timing table is available and which never runs at all because
the change set escalated first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._test_selection import FULL_SUITE
from tests._test_selection_engine_helpers import (
    neutral_timings_environment,  # noqa: F401 (imported for fixture discovery)
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
    with_timings,
)
from tests._test_selection_fixtures import _touch
from tests._test_selection_rules import (
    RULE_PACKAGING_CONFIG,
    RULE_RATIO_EXCEEDED,
    RULE_SERIAL_BUDGET_EXCEEDED,
)
from tests._test_selection_timings import REASON_ESCALATED


# --------------------------------------------------------------------------
# The file-count ratio
# --------------------------------------------------------------------------


def test_ratio_escalation_trips_at_the_threshold(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    selection = select(repo, max_ratio=0.05)

    assert RULE_RATIO_EXCEEDED in selection.rules
    assert selection.escalated
    assert selection.selected == ()


def test_ratio_escalation_does_not_trip_below_the_threshold(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    selection = select(repo, max_ratio=0.9)

    assert RULE_RATIO_EXCEEDED not in selection.rules
    assert not selection.escalated


# --------------------------------------------------------------------------
# The serial-runtime budget
# --------------------------------------------------------------------------


def test_serial_budget_escalates_a_selection_that_costs_more_than_the_full_lane(
    repo: Path,
) -> None:
    _touch(repo, "src/pkg/a.py")
    store, baseline = with_timings(repo, 100.0)

    selection = select(repo, max_serial_seconds=50.0, timings_store=store)

    assert RULE_SERIAL_BUDGET_EXCEEDED in selection.rules
    assert selection.escalated
    assert selection.selected == ()
    assert selection.paths_output == FULL_SUITE
    # The rejected selection's cost stays on the record: an escalation that
    # cannot say what it was avoiding is not attributable.
    assert selection.timings.seconds == pytest.approx(100.0 * len(baseline.selected))


def test_serial_budget_leaves_a_selection_within_it_alone(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")
    store, baseline = with_timings(repo, 1.0)

    selection = select(repo, max_serial_seconds=1.0e6, timings_store=store)

    assert RULE_SERIAL_BUDGET_EXCEEDED not in selection.rules
    assert not selection.escalated
    assert selection.selected == baseline.selected
    assert selection.timings.available


def test_serial_budget_supersedes_the_file_count_ratio(repo: Path) -> None:
    """A cheap selection stays scoped even when the ratio would have escalated.

    This is the epic's whole point: the ratio rated a 94-file selection that
    cost 465s as comfortably scoped, and a 517-file one that cost 404s as too
    big. Where the table can answer, runtime decides.
    """
    _touch(repo, "src/pkg/a.py")
    store, _ = with_timings(repo, 0.1)

    selection = select(
        repo, max_ratio=0.05, max_serial_seconds=1.0e6, timings_store=store
    )

    assert not selection.escalated
    assert RULE_RATIO_EXCEEDED not in selection.rules


def test_the_ratio_still_decides_when_there_is_no_timing_data(repo: Path) -> None:
    """A fresh host with no table behaves exactly as it did before."""
    _touch(repo, "src/pkg/a.py")

    selection = select(repo, max_ratio=0.05, max_serial_seconds=0.001)

    assert selection.escalated
    assert RULE_RATIO_EXCEEDED in selection.rules
    assert RULE_SERIAL_BUDGET_EXCEEDED not in selection.rules
    assert not selection.timings.available


def test_manifest_records_the_budget_the_estimate_was_measured_against(
    repo: Path,
) -> None:
    _touch(repo, "src/pkg/a.py")
    store, _ = with_timings(repo, 1.0)

    selection = select(repo, max_serial_seconds=1234.5, timings_store=store)

    assert selection.manifest["max_serial_seconds"] == pytest.approx(1234.5)
    assert selection.manifest["timings"]["available"] is True


def test_a_change_set_escalation_never_reaches_the_budget(repo: Path) -> None:
    """`pyproject.toml` escalates before there is a selection to cost."""
    _touch(repo, "pyproject.toml")
    store, _ = with_timings(repo, 100.0)

    selection = select(repo, max_serial_seconds=0.001, timings_store=store)

    assert selection.escalated
    assert RULE_PACKAGING_CONFIG in selection.rules
    assert RULE_SERIAL_BUDGET_EXCEEDED not in selection.rules
    assert selection.timings.reason == REASON_ESCALATED
