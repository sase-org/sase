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
from tests._test_selection_health import (
    FULL_LANE_WALL_SECONDS,
    FULL_SUITE_WORKER_SECONDS,
    summarize,
)
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


def test_summary_reports_duration_percentiles_and_the_slow_run_tail(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    for minute, duration in enumerate((50.0, 100.0, 150.0, 200.0, 300.0)):
        write_selection(
            store,
            manifest(
                head=f"h{minute}",
                selected=(f"tests/test_{minute}.py",),
                duration=duration,
                rules=(
                    ("compensate-narrow-diff",)
                    if duration > FULL_LANE_WALL_SECONDS
                    else ("contract-set-always",)
                ),
            ),
            minute=minute,
        )
    write_selection(
        store,
        manifest(head="esc", escalated=True, rules=("justfile",), duration=0.0),
        minute=5,
    )

    health = summarize(load_records(store), is_ancestor=lambda _a, _b: False)

    assert health.median_duration == pytest.approx(150.0)
    assert health.p75_duration == pytest.approx(200.0)
    assert health.p90_duration == pytest.approx(260.0)
    assert health.max_duration == pytest.approx(300.0)
    assert len(health.slow_runs) == 1
    assert health.slow_runs[0].duration == pytest.approx(300.0)
    assert health.slow_runs[0].selected_count == 1
    assert health.slow_runs[0].rules == ("compensate-narrow-diff",)

    report = "\n".join(render_report(health))
    assert "p75 duration:         200.0s" in report
    assert "p90 duration:         260.0s" in report
    assert "max duration:         300.0s" in report
    assert "scoped runs slower than the full lane (232.0s): 1 of 6" in report
    assert "1 escalated run(s) not counted here: cost not measured" in report
    assert "1 file(s) selected, rules: compensate-narrow-diff" in report


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


def test_an_escalated_run_is_not_counted_against_the_baseline(tmp_path: Path) -> None:
    """A forced escalation never consulted contexts, so it is not exposure.

    Counting it as a run that narrowed on the static closure alone is what made
    a lane with two genuinely baseline-less runs read as twenty-three of them,
    and that inflated number is what the compensating rule was first sized
    against.
    """
    store = tmp_path / "store"
    write_selection(
        store,
        manifest(
            head="aaa",
            selected=("tests/test_a.py",),
            contexts={"baseline": "abc123", "consulted": True, "selected_count": 3},
        ),
        minute=0,
    )
    for minute, rule in enumerate(("justfile", "core-identity-changed"), start=1):
        write_selection(
            store,
            manifest(
                head=f"esc{minute}",
                escalated=True,
                rules=(rule,),
                duration=0.0,
                outcome="escalated",
                contexts={"baseline": None, "consulted": False},
            ),
            minute=minute,
        )

    health = summarize(load_records(store), is_ancestor=lambda _a, _b: False)

    assert health.scoped_runs == 3
    assert health.context_consulted_runs == 1
    assert health.context_not_consulted_runs == 2
    assert health.context_runs == 1
    assert health.context_missing_runs == 0
    report = "\n".join(render_report(health))
    assert "runs that consulted it: 1 of 3 (2 escalated before it mattered)" in report
    assert "runs with a baseline:  1 of 1" in report
    assert "runs without one:      0 (static closure alone)" in report


def test_escalated_records_written_before_the_flag_are_read_the_same_way(
    tmp_path: Path,
) -> None:
    """The store keeps 30 days of records, so the fix has to reach back."""
    store = tmp_path / "store"
    write_selection(
        store,
        manifest(head="aaa", escalated=True, rules=("justfile",), duration=0.0),
        minute=0,
    )

    health = summarize(load_records(store), is_ancestor=lambda _a, _b: False)

    assert (health.context_consulted_runs, health.context_missing_runs) == (0, 0)
    assert "runs that consulted it: 0 of 1" in "\n".join(render_report(health))


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
    assert "flake-suppressed" in report  # remedy points at the split, not just depth


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


def test_health_payload_includes_duration_percentiles_and_slow_runs(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    write_selection(
        store,
        manifest(
            head="aaa",
            selected=("tests/test_a.py",),
            duration=300.0,
            rules=("compensate-narrow-diff",),
        ),
    )

    payload = health_payload(
        summarize(load_records(store), is_ancestor=lambda _a, _b: False)
    )
    round_tripped = json.loads(json.dumps(payload))

    assert round_tripped["max_duration"] == pytest.approx(300.0)
    assert round_tripped["full_lane_wall_seconds"] == pytest.approx(
        FULL_LANE_WALL_SECONDS
    )
    assert len(round_tripped["slow_runs"]) == 1
    slow_run = round_tripped["slow_runs"][0]
    assert slow_run["duration"] == pytest.approx(300.0)
    assert slow_run["selected_count"] == 1
    assert slow_run["rules"] == ["compensate-narrow-diff"]


def test_report_suppresses_a_reproducible_flake_and_states_it_separately(
    tmp_path: Path,
) -> None:
    # The same node fails in two full runs whose change sets share no file:
    # no single diff explains it, so it is a known flake, not a false negative.
    store = tmp_path / "store"
    write_selection(store, manifest(head="s1", changed_files=("src/a.py",)), minute=0)
    write_full_run(
        store,
        head="f1",
        failures=("tests/test_flaky.py::test_x",),
        changed_files=("src/a.py",),
        minute=1,
    )
    write_selection(store, manifest(head="s2", changed_files=("src/b.py",)), minute=2)
    write_full_run(
        store,
        head="f2",
        failures=("tests/test_flaky.py::test_x",),
        changed_files=("src/b.py",),
        minute=3,
    )

    health = summarize(
        load_records(store), is_ancestor=linear_ancestry("s1", "f1", "s2", "f2")
    )
    report = "\n".join(render_report(health))

    assert "false negatives: 0" in report
    assert "flake-suppressed: 1 (2 scoped run/failure matches)" in report
    assert "tests/test_flaky.py::test_x" in report


def test_health_payload_is_machine_readable(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", selected=("tests/test_kept.py",)))
    write_full_run(store, head="bbb", failures=("tests/test_missed.py::test_x",))

    payload = health_payload(
        summarize(load_records(store), is_ancestor=linear_ancestry("aaa", "bbb"))
    )

    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["false_negatives"][0]["test_file"] == "tests/test_missed.py"
    assert round_tripped["flake_suppressed"] == []
    # The exposure split is machine-readable too, so a reader that parses
    # rather than reads cannot fall back into the every-scoped-run denominator.
    assert round_tripped["context_consulted_runs"] == 1
    assert round_tripped["context_not_consulted_runs"] == 0
    assert round_tripped["context_missing_runs"] == 1


def test_health_payload_reports_flake_suppressed_matches(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="s1", changed_files=("src/a.py",)), minute=0)
    write_full_run(
        store,
        head="f1",
        failures=("tests/test_flaky.py::test_x",),
        changed_files=("src/a.py",),
        minute=1,
    )
    write_selection(store, manifest(head="s2", changed_files=("src/b.py",)), minute=2)
    write_full_run(
        store,
        head="f2",
        failures=("tests/test_flaky.py::test_x",),
        changed_files=("src/b.py",),
        minute=3,
    )

    payload = health_payload(
        summarize(
            load_records(store), is_ancestor=linear_ancestry("s1", "f1", "s2", "f2")
        )
    )

    round_tripped = json.loads(json.dumps(payload))
    assert round_tripped["false_negatives"] == []
    assert len(round_tripped["flake_suppressed"]) == 2
    assert {m["nodeid"] for m in round_tripped["flake_suppressed"]} == {
        "tests/test_flaky.py::test_x"
    }
