"""Unit tests for what a selection reports about itself.

The manifest's documented shape, the summary and explain lines, the paths
handed to pytest, and the options parsed out of the environment.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests._test_selection import SelectionOptions
from tests._test_selection_engine_helpers import (
    neutral_timings_environment,  # noqa: F401 (imported for fixture discovery)
    repo_fixture,  # noqa: F401 (imported for fixture discovery)
    select,
    with_timings,
)
from tests._test_selection_fixtures import _touch
from tests._test_selection_graph import SelectionError
from tests._test_selection_health import FULL_LANE_WALL_SECONDS
from tests._test_selection_manifest import MANIFEST_SCHEMA
from tests._test_selection_report import budget_line, summary_line


# --------------------------------------------------------------------------
# Manifest and reporting
# --------------------------------------------------------------------------


def test_manifest_carries_every_documented_field(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    manifest = select(repo).manifest

    assert manifest["schema"] == MANIFEST_SCHEMA
    assert set(manifest) == {
        "schema",
        "base",
        "changed_files",
        "depth",
        "effective_depth",
        "max_ratio",
        "max_serial_seconds",
        "rules_fired",
        "escalated",
        "selected",
        "selected_count",
        "universe_count",
        "baseline",
        "graph",
        "contexts",
        "timings",
    }
    assert manifest["changed_files"] == ["src/pkg/a.py"]
    assert set(manifest["contexts"]) == {
        "baseline",
        "consulted",
        "stale",
        "distance",
        "selected_count",
        "matched_files",
    }
    assert set(manifest["timings"]) == {
        "estimated_serial_seconds",
        "available",
        "reason",
        "coverage",
        "covered_count",
        "missing_count",
        "min_coverage",
        "table",
    }
    # Nothing compensated here, so the walked depth is the configured one.
    assert manifest["effective_depth"] == manifest["depth"]
    assert manifest["selected_count"] == len(manifest["selected"])
    assert set(manifest["baseline"]) == {
        "environment",
        "environment_changed_inputs",
        "head",
        "tree_dirty",
    }
    assert manifest["baseline"]["tree_dirty"] is True
    assert manifest["graph"]["modules"] > 0
    assert manifest["graph"]["edges"] > 0


def test_summary_line_reports_escalation(repo: Path) -> None:
    _touch(repo, "Justfile")

    assert "escalated to the full suite" in summary_line(select(repo))


def test_summary_line_reports_a_scoped_selection(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")

    assert summary_line(select(repo)).startswith("selected 5 of ")


def test_explain_reports_the_budget_a_scoped_run_stayed_within(repo: Path) -> None:
    _touch(repo, "src/pkg/a.py")
    store, _ = with_timings(repo, 2.0)

    line = budget_line(select(repo, max_serial_seconds=232.0, timings_store=store))

    assert line.startswith("serial budget: estimated 10s against a 232s budget")
    assert "within" in line


def test_explain_says_the_ratio_decided_when_there_is_no_estimate(
    repo: Path,
) -> None:
    _touch(repo, "src/pkg/a.py")

    line = budget_line(select(repo, max_ratio=0.25))

    assert "no estimate" in line
    assert "ratio decides instead" in line


def test_explain_does_not_claim_a_budget_on_a_change_set_escalation(
    repo: Path,
) -> None:
    _touch(repo, "Justfile")

    assert "not evaluated" in budget_line(select(repo))


def test_paths_output_is_one_path_per_line(repo: Path) -> None:
    _touch(repo, "src/pkg/d.py")

    output = select(repo).paths_output

    assert output.splitlines() == ["tests/test_d.py"]


# --------------------------------------------------------------------------
# Options
# --------------------------------------------------------------------------


def test_options_read_the_environment() -> None:
    options = SelectionOptions.from_environment(
        environ={
            "SASE_CHECK_BASE": "origin/main",
            "SASE_TEST_SELECTION_DEPTH": "3",
            "SASE_TEST_SELECTION_MAX_RATIO": "0.4",
            "SASE_TEST_SELECTION_MAX_SERIAL_SECONDS": "90",
        }
    )

    assert options.base_ref == "origin/main"
    assert options.depth == 3
    assert options.max_ratio == 0.4
    assert options.max_serial_seconds == 90.0


def test_options_default_when_unset() -> None:
    options = SelectionOptions.from_environment(environ={})

    assert options.base_ref == "origin/master"
    assert options.depth == 2
    assert options.max_ratio == 0.25
    # The budget defaults to the full lane's measured wall clock, not a round
    # number: past that crossover the scoped lane is the slow lane.
    assert options.max_serial_seconds == FULL_LANE_WALL_SECONDS


@pytest.mark.parametrize(
    "environ",
    [
        {"SASE_TEST_SELECTION_DEPTH": "not-a-number"},
        {"SASE_TEST_SELECTION_DEPTH": "-1"},
        {"SASE_TEST_SELECTION_MAX_RATIO": "0"},
        {"SASE_TEST_SELECTION_MAX_RATIO": "1.5"},
        {"SASE_TEST_SELECTION_MAX_RATIO": "nope"},
        {"SASE_TEST_SELECTION_MAX_SERIAL_SECONDS": "0"},
        {"SASE_TEST_SELECTION_MAX_SERIAL_SECONDS": "-5"},
        {"SASE_TEST_SELECTION_MAX_SERIAL_SECONDS": "nope"},
    ],
)
def test_options_reject_nonsense(environ: dict[str, str]) -> None:
    with pytest.raises(SelectionError):
        SelectionOptions.from_environment(environ=environ)
