"""Unit tests for correlating full-run failures against earlier scoped runs.

A false negative is a failure the full lane found that an ancestor scoped run
over the same change, in the same workspace, chose not to run. These tests pin
each half of that rule — what counts, and everything that deliberately does not.
"""

from __future__ import annotations

from pathlib import Path

from tests._selection_health_case_helpers import (
    CHANGED,
    WORKSPACE,
    git_init,
    linear_ancestry,
    manifest,
    write_full_run,
    write_selection,
)
from tests._test_selection_health import (
    count_pre_schema_records,
    find_false_negatives,
    find_flake_suppressed,
    git_ancestor_oracle,
    nodeid_test_file,
    reproducible_flake_nodeids,
)
from tests._test_selection_health_records import FullRunRecord, load_records


def test_a_failure_excluded_by_an_ancestor_selection_is_a_false_negative(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", selected=("tests/test_kept.py",)))
    write_full_run(store, head="bbb", failures=("tests/test_missed.py::test_x",))

    found = find_false_negatives(
        load_records(store), is_ancestor=linear_ancestry("aaa", "bbb")
    )

    assert len(found) == 1
    assert found[0].nodeid == "tests/test_missed.py::test_x"
    assert found[0].test_file == "tests/test_missed.py"
    assert found[0].rules == ("contract-set-always",)
    assert found[0].workspace == WORKSPACE
    assert found[0].selection_changed_files == CHANGED


def test_a_failure_from_another_workspace_is_never_a_false_negative(
    tmp_path: Path,
) -> None:
    # The store is shared across numbered workspaces, and they all sit on the
    # same master HEAD: without this restriction every manifest matches every
    # other workspace's failures, which is the defect this phase fixes.
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa"), workspace="/workspaces/sase_3")
    write_full_run(
        store,
        head="bbb",
        failures=("tests/test_missed.py::test_x",),
        workspace="/workspaces/sase_11",
    )

    assert not find_false_negatives(
        load_records(store), is_ancestor=linear_ancestry("aaa", "bbb")
    )


def test_a_full_run_of_a_disjoint_change_is_never_a_false_negative(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", changed_files=("docs/a.md",)))
    write_full_run(
        store,
        head="bbb",
        failures=("tests/test_missed.py::test_x",),
        changed_files=("src/sase/beta.py",),
    )

    assert not find_false_negatives(
        load_records(store), is_ancestor=linear_ancestry("aaa", "bbb")
    )


def test_a_full_run_that_grew_the_scoped_change_set_still_matches(
    tmp_path: Path,
) -> None:
    # Agents commit as they go, so the full run normally sees a superset of
    # what the earlier scoped run over the same change saw.
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", changed_files=("src/sase/a.py",)))
    write_full_run(
        store,
        head="bbb",
        failures=("tests/test_missed.py::test_x",),
        changed_files=("src/sase/a.py", "src/sase/b.py"),
    )

    found = find_false_negatives(
        load_records(store), is_ancestor=linear_ancestry("aaa", "bbb")
    )

    assert [match.nodeid for match in found] == ["tests/test_missed.py::test_x"]


def test_records_without_the_schema_2_identity_are_skipped_and_counted(
    tmp_path: Path,
) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", changed_files=None))
    write_selection(store, manifest(head="aaa"), minute=1, workspace=None)
    write_full_run(
        store,
        head="bbb",
        failures=("tests/test_missed.py::test_x",),
        changed_files=None,
    )
    records = load_records(store)

    assert not find_false_negatives(records, is_ancestor=linear_ancestry("aaa", "bbb"))
    pre_schema = count_pre_schema_records(records)
    assert (pre_schema.selections, pre_schema.full_runs, pre_schema.total) == (2, 1, 3)


def test_a_selected_failure_is_not_a_false_negative(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", selected=("tests/test_x.py",)))
    write_full_run(store, head="bbb", failures=("tests/test_x.py::test_y",))

    assert not find_false_negatives(
        load_records(store), is_ancestor=linear_ancestry("aaa", "bbb")
    )


def test_an_escalated_selection_can_never_be_a_false_negative(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa", escalated=True, outcome="escalated"))
    write_full_run(store, head="bbb", failures=("tests/test_x.py::test_y",))

    assert not find_false_negatives(
        load_records(store), is_ancestor=linear_ancestry("aaa", "bbb")
    )


def test_a_selection_that_is_not_an_ancestor_is_ignored(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="zzz"))
    write_full_run(store, head="bbb", failures=("tests/test_x.py::test_y",))

    assert not find_false_negatives(
        load_records(store), is_ancestor=linear_ancestry("aaa", "bbb")
    )


def test_visual_failures_are_never_false_negatives(tmp_path: Path) -> None:
    store = tmp_path / "store"
    write_selection(store, manifest(head="aaa"))
    write_full_run(
        store,
        head="bbb",
        failures=("tests/ace/tui/visual/test_png.py::test_snapshot",),
    )

    assert not find_false_negatives(
        load_records(store), is_ancestor=linear_ancestry("aaa", "bbb")
    )


def test_the_git_ancestor_oracle_answers_false_for_unknown_commits(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    git_init(root, remote=None)

    assert git_ancestor_oracle(root)("a" * 40, "b" * 40) is False


def test_nodeid_test_file_strips_the_node_part() -> None:
    assert nodeid_test_file("tests/a/test_b.py::TestC::test_d") == "tests/a/test_b.py"
    assert nodeid_test_file("tests/a/test_b.py") == "tests/a/test_b.py"


# --------------------------------------------------------------------------
# Known-flake suppression
# --------------------------------------------------------------------------
#
# A full-run failure that recurs across full runs whose change sets share no
# file cannot be explained by any one of those diffs, so it is a known flake
# rather than a selection miss. See `reproducible_flake_nodeids`.


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
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=("tests/test_x.py::test_flaky",),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset(
        {"tests/test_x.py::test_flaky"}
    )


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
    write_selection(store, manifest(head="s2", changed_files=("src/b.py",)), minute=2)
    write_full_run(
        store,
        head="f2",
        failures=("tests/test_x.py::test_flaky",),
        changed_files=("src/b.py", "src/other2.py"),
        minute=3,
    )
    records = load_records(store)
    is_ancestor = linear_ancestry("s1", "f1", "s2", "f2")

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
