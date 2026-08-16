"""Unit tests for the known-flake gate that spares a failure from being charged.

A full-run failure that recurs across unrelated change sets and has an
independent passing full run between those failures is a known flake rather
than a selection miss. These tests pin the evidence bar itself — see
`reproducible_flake_nodeids` — and how a cleared failure is reported instead of
counted as a false negative (``test_test_selection_health_correlation.py``).
The supporting oracles live in ``test_test_selection_health_flake_oracles.py``.
"""

from __future__ import annotations

from pathlib import Path

from tests._selection_health_case_helpers import (
    WORKSPACE,
    linear_ancestry,
    manifest,
    write_full_run,
    write_selection,
)
from tests._test_selection_health import (
    find_false_negatives,
    find_flake_suppressed,
    reproducible_flake_nodeids,
)
from tests._test_selection_health_records import FullRunRecord, load_records


def test_reproducible_flake_nodeids_needs_at_least_two_full_runs() -> None:
    one_run = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=("tests/test_x.py::test_flaky",),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
    )

    assert reproducible_flake_nodeids(one_run) == frozenset()


def test_reproducible_flake_nodeids_flags_failures_with_no_change_set_in_common() -> (
    None
):
    nodeid = "tests/test_x.py::test_flaky"
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(nodeid,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
        FullRunRecord(
            name="pass",
            recorded_at=None,
            head="pass",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/pass.py"}),
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset({nodeid})


def test_reproducible_flake_nodeids_spares_fixed_deterministic_breaks() -> None:
    nodeid = "tests/test_x.py::test_fixed_break"
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(nodeid,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
        FullRunRecord(
            name="fixed",
            recorded_at=None,
            head="fixed",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/fix.py"}),
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset()


def test_reproducible_flake_nodeids_ignores_passes_that_change_the_test_file() -> None:
    nodeid = "tests/test_x.py::test_fixed_in_place"
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(nodeid,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
        FullRunRecord(
            name="fix",
            recorded_at=None,
            head="fix",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"tests/test_x.py"}),
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset()


def test_reproducible_flake_nodeids_orders_records_by_commit_when_available() -> None:
    nodeid = "tests/test_x.py::test_old_break"
    runs = (
        FullRunRecord(
            name="old-a",
            recorded_at=None,
            head="old",
            mode="fast",
            failures=(nodeid,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
        FullRunRecord(
            name="new-pass",
            recorded_at=None,
            head="new",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/unrelated.py"}),
        ),
        FullRunRecord(
            name="old-b",
            recorded_at=None,
            head="old",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
    )

    assert (
        reproducible_flake_nodeids(runs, commit_order={"old": 1, "new": 2}.__getitem__)
        == frozenset()
    )


def test_reproducible_flake_nodeids_can_ignore_broken_cluster_runs() -> None:
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=("tests/test_x.py::test_flaky",),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
        FullRunRecord(
            name="pass",
            recorded_at=None,
            head="pass",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/pass.py"}),
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(
                "tests/test_x.py::test_flaky",
                "tests/test_y.py::test_broken",
            ),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset(
        {"tests/test_x.py::test_flaky"}
    )
    assert reproducible_flake_nodeids(runs, max_failures_per_run=1) == frozenset()


def test_reproducible_flake_nodeids_spares_a_failure_with_a_shared_file() -> None:
    # Both occurrences' diffs touch src/shared.py: a single genuine cause is
    # still plausible, so this is not called reproducible.
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=("tests/test_x.py::test_missed",),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/shared.py", "src/a.py"}),
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=("tests/test_x.py::test_missed",),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/shared.py", "src/b.py"}),
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset()


def test_reproducible_flake_nodeids_ignores_runs_with_no_change_set() -> None:
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=("tests/test_x.py::test_flaky",),
            workspace=WORKSPACE,
            changed_files=None,
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=("tests/test_x.py::test_flaky",),
            workspace=WORKSPACE,
            changed_files=None,
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset()


def test_a_reproducible_flake_is_excluded_from_false_negatives_and_counted_separately(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="s1", changed_files=("src/a.py",)), minute=0)
    write_full_run(
        store,
        head="f1",
        failures=("tests/test_x.py::test_flaky",),
        changed_files=("src/a.py", "src/other1.py"),
        minute=1,
    )
    write_full_run(
        store,
        head="pass",
        failures=(),
        changed_files=("src/pass.py",),
        minute=2,
    )
    write_selection(store, manifest(head="s2", changed_files=("src/b.py",)), minute=3)
    write_full_run(
        store,
        head="f2",
        failures=("tests/test_x.py::test_flaky",),
        changed_files=("src/b.py", "src/other2.py"),
        minute=4,
    )
    records = load_records(store)
    is_ancestor = linear_ancestry("s1", "f1", "pass", "s2", "f2")

    assert not find_false_negatives(records, is_ancestor=is_ancestor)
    suppressed = find_flake_suppressed(records, is_ancestor=is_ancestor)
    assert {match.nodeid for match in suppressed} == {"tests/test_x.py::test_flaky"}
    assert len(suppressed) == 2


def test_a_single_occurrence_stays_a_false_negative_pending_a_second(
    tmp_path: Path,
) -> None:
    # One failure is not enough evidence to call it a flake; it is charged
    # as a false negative until it recurs across an unrelated change set.
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", selected=("tests/test_kept.py",)))
    write_full_run(store, head="bbb", failures=("tests/test_missed.py::test_x",))
    records = load_records(store)
    is_ancestor = linear_ancestry("aaa", "bbb")

    assert not find_flake_suppressed(records, is_ancestor=is_ancestor)
    found = find_false_negatives(records, is_ancestor=is_ancestor)
    assert [match.nodeid for match in found] == ["tests/test_missed.py::test_x"]
