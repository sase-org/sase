"""Unit tests for the selection-health summary and its rendered report.

The summary is what the heuristic's track record boils down to; the report is
how an agent reads it. These tests pin both the numbers and the wording an agent
is expected to act on.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests._selection_health_case_helpers import (
    linear_ancestry,
    manifest,
    write_full_run,
    write_selection,
)
from tests._test_selection_health import FULL_SUITE_WORKER_SECONDS, summarize
from tests._test_selection_health_records import load_records
from tests._test_selection_health_report import health_payload, render_report


def test_summary_reports_coverage_escalation_and_savings(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(
        store,
        manifest(head="aaa", selected=("tests/test_a.py",), duration=50.0),
        minute=0,
    )
    write_selection(
        store,
        manifest(
            head="bbb",
            selected=("tests/test_a.py", "tests/test_b.py", "tests/test_c.py"),
            duration=150.0,
        ),
        minute=1,
    )
    write_selection(
        store,
        manifest(head="ccc", escalated=True, rules=("justfile",), duration=0.0),
        minute=2,
    )

    health = summarize(load_records(store), is_ancestor=lambda _a, _b: False)

    assert health.scoped_runs == 3
    assert health.escalated_runs == 1
    assert health.escalation_rate == pytest.approx(1 / 3)
    assert health.median_selected == pytest.approx(2.0)
    assert health.median_duration == pytest.approx(100.0)
    assert health.worker_seconds_saved == pytest.approx(
        2 * FULL_SUITE_WORKER_SECONDS - 200.0
    )
    assert health.rule_histogram == {"contract-set-always": 2, "justfile": 1}
    assert health.universe_count == 2400
    assert health.median_selected_ratio == pytest.approx(2 / 2400)


def test_summary_of_an_empty_store_is_reportable(tmp_path: Path) -> None:
    health = summarize(load_records(tmp_path), is_ancestor=lambda _a, _b: False)

    assert health.scoped_runs == 0
    assert health.escalation_rate is None
    assert "No runs recorded yet." in "\n".join(render_report(health))


def test_report_states_a_clean_bill_of_health_explicitly(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", selected=("tests/test_a.py",)))

    report = "\n".join(
        render_report(summarize(load_records(store), is_ancestor=lambda _a, _b: False))
    )

    assert "false negatives: 0" in report
    assert "worker-seconds avoided" in report


def test_report_counts_coverage_context_baselines_and_staleness(
    tmp_path: Path,
) -> None:
    """Whether contexts reach real runs is what says if they earn their CI cost."""
    store = tmp_path / "store"
    write_selection(
        store,
        manifest(
            head="aaa",
            selected=("tests/test_a.py",),
            contexts={"baseline": "abc123", "stale": False, "selected_count": 3},
        ),
        minute=0,
    )
    write_selection(
        store,
        manifest(
            head="bbb",
            selected=("tests/test_b.py",),
            contexts={"baseline": "abc123", "stale": True, "selected_count": 2},
        ),
        minute=1,
    )
    write_selection(
        store, manifest(head="ccc", selected=("tests/test_c.py",)), minute=2
    )

    health = summarize(load_records(store), is_ancestor=lambda _a, _b: False)

    assert (health.context_runs, health.context_stale_runs) == (2, 1)
    assert health.context_selected_total == 5
    report = "\n".join(render_report(health))
    assert "runs with a baseline:  2 of 3" in report
    assert "runs on a stale one:   1" in report


def test_report_points_at_the_remedy_when_no_baseline_is_cached(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", selected=("tests/test_a.py",)))

    report = "\n".join(
        render_report(summarize(load_records(store), is_ancestor=lambda _a, _b: False))
    )

    assert "just refresh-contexts-baseline" in report


def test_report_lists_every_false_negative_and_what_to_do(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", selected=("tests/test_kept.py",)))
    write_full_run(store, head="bbb", failures=("tests/test_missed.py::test_x",))

    health = summarize(load_records(store), is_ancestor=linear_ancestry("aaa", "bbb"))
    report = "\n".join(render_report(health))

    assert "false negatives: 1" in report
    assert "tests/test_missed.py::test_x" in report
    assert "SASE_TEST_SELECTION_DEPTH" in report


def test_report_states_the_matching_rule_whatever_the_count(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa"))

    report = "\n".join(
        render_report(summarize(load_records(store), is_ancestor=lambda _a, _b: False))
    )

    assert "matching rule:" in report
    assert "same workspace" in report
    assert "covers the scoped run's" in report


def test_report_says_how_many_records_predate_the_schema(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa"), workspace=None)
    write_full_run(store, head="bbb", failures=(), changed_files=None)

    report = "\n".join(
        render_report(summarize(load_records(store), is_ancestor=lambda _a, _b: False))
    )

    assert "2 record(s) predate schema 2" in report
    assert "excluded from correlation" in report


def test_report_flags_a_nodeid_matched_across_unrelated_changes(
    tmp_path: Path,
) -> None:
    # Two scoped runs over different changes, both charged with the same
    # failure: repetition across unrelated change sets reads as a flake.
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", changed_files=("src/sase/a.py",)))
    write_selection(
        store,
        manifest(head="aaa", changed_files=("src/sase/b.py",)),
        minute=1,
    )
    write_full_run(
        store,
        head="bbb",
        failures=("tests/test_flaky.py::test_x",),
        changed_files=("src/sase/a.py", "src/sase/b.py"),
    )

    health = summarize(load_records(store), is_ancestor=linear_ancestry("aaa", "bbb"))
    report = "\n".join(render_report(health))

    assert "false negatives: 1 (2 scoped run/failure matches)" in report
    assert "distinct change sets: 2" in report
    assert "suspect a flake before a miss" in report


def test_health_payload_is_machine_readable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", selected=("tests/test_kept.py",)))
    write_full_run(store, head="bbb", failures=("tests/test_missed.py::test_x",))

    payload = health_payload(
        summarize(load_records(store), is_ancestor=linear_ancestry("aaa", "bbb"))
    )

    assert json.loads(json.dumps(payload))["false_negatives"][0]["test_file"] == (
        "tests/test_missed.py"
    )
