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
    attributable_dirty_failures,
    collectible_nodeid_oracle,
    count_pre_schema_records,
    find_false_negatives,
    find_flake_suppressed,
    git_ancestor_oracle,
    nodeid_test_file,
    reproducible_flake_nodeids,
    stale_flake_nodeids,
    unresolved_commit_order_count,
)
from tests._test_selection_health_correlation import _SOURCE_AUDIT_SCAN_ROOTS
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
# A full-run failure that recurs across unrelated change sets and has an
# independent passing full run between those failures is a known flake rather
# than a selection miss. See `reproducible_flake_nodeids`.


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


# --------------------------------------------------------------------------
# Stale node IDs — a renamed or deleted test's old node ID can never pass
# again, so without a staleness check it would meet the reproducible-flake
# evidence bar forever. See `reproducible_flake_nodeids` and
# `stale_flake_nodeids`.


def _reproducible_flake_evidence_runs(nodeid: str) -> tuple[FullRunRecord, ...]:
    """Three full runs that meet the reproducible-flake evidence bar for ``nodeid``."""
    return (
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


def test_reproducible_flake_nodeids_omits_a_node_the_oracle_reports_uncollectable() -> (
    None
):
    nodeid = "tests/test_run_pytest_main.py::test_renamed_away"
    runs = _reproducible_flake_evidence_runs(nodeid)

    assert reproducible_flake_nodeids(runs) == frozenset({nodeid})
    assert reproducible_flake_nodeids(runs, collectible=lambda _n: True) == frozenset(
        {nodeid}
    )
    assert reproducible_flake_nodeids(runs, collectible=lambda _n: False) == frozenset()


def test_stale_flake_nodeids_reports_exactly_what_the_collectible_check_excluded() -> (
    None
):
    nodeid = "tests/test_run_pytest_main.py::test_renamed_away"
    runs = _reproducible_flake_evidence_runs(nodeid)

    assert stale_flake_nodeids(runs, collectible=lambda _n: False) == frozenset(
        {nodeid}
    )
    assert stale_flake_nodeids(runs, collectible=lambda _n: True) == frozenset()


def test_collectible_nodeid_oracle_finds_a_still_defined_function(
    tmp_path: Path,
) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(
        "def test_kept():\n    pass\n", encoding="utf-8"
    )

    is_collectible = collectible_nodeid_oracle(tmp_path)

    assert is_collectible("tests/test_sample.py::test_kept") is True
    assert is_collectible("tests/test_sample.py::test_renamed_away") is False
    assert is_collectible("tests/test_absent_file.py::test_kept") is False


def test_collectible_nodeid_oracle_matches_class_and_parametrized_nodeids(
    tmp_path: Path,
) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text(
        "class TestThing:\n    def test_method(self):\n        pass\n",
        encoding="utf-8",
    )

    is_collectible = collectible_nodeid_oracle(tmp_path)

    assert is_collectible("tests/test_sample.py::TestThing::test_method[case0]") is True
    assert is_collectible("tests/test_sample.py::TestThing::test_absent") is False


def test_unresolved_commit_order_count_needs_an_oracle_to_mean_anything() -> None:
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="unknown",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
    )

    assert unresolved_commit_order_count(runs) == 0


def test_unresolved_commit_order_count_counts_heads_the_oracle_cannot_resolve() -> None:
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="known",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="unknown",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/b.py"}),
        ),
        FullRunRecord(
            name="c",
            recorded_at=None,
            head=None,
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/c.py"}),
        ),
    )

    assert unresolved_commit_order_count(runs, commit_order={"known": 1}.get) == 2


# --------------------------------------------------------------------------
# Attributable dirty-tree failures — sase-lc. A source-tree audit (an AST or
# text scan compared against a checked-in reviewed inventory) can fail
# deterministically because the recording workspace's own uncommitted edit
# under the audited root legitimately broke it; that is not cross-workspace
# intermittency and must not be promoted into shared flake debt. See
# `_SOURCE_AUDIT_SCAN_ROOTS` and `_is_attributable_dirty_failure` in
# `tests._test_selection_health_correlation`.

_MARKER_AUDIT_NODEID = (
    "tests/test_agent_artifact_marker_path_passing_audit.py"
    "::test_tracked_marker_path_passing_sites_are_reviewed"
)


def test_dirty_tree_source_audit_failures_are_not_reproducible_flakes() -> None:
    # Reconstructs sase-lc's two evidence records: two disjoint dirty-tree
    # full runs, from unrelated workspaces, both failed the marker
    # path-passing audit only because each workspace's own uncommitted
    # src/sase/ edits broke the AST scan the audit runs against a checked-in
    # reviewed inventory — not because the node is flaky. A passing run with
    # an unrelated change set sits between them, which is exactly the
    # interleaved-independent-pass shape that made this look like a
    # reproducible flake before this rule existed.
    runs = (
        FullRunRecord(
            name="20260812T230235Z-9f93c3d8c0c5-2782438-full-run.json",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID,),
            workspace="/workspaces/sase_12",
            changed_files=frozenset(
                {
                    "src/sase/monitor/supervise.py",
                    "src/sase/plan_chain.py",
                    "tests/monitor/test_monitor_supervise.py",
                    "tests/test_plan_chain_roles.py",
                }
            ),
            tree_dirty=True,
        ),
        FullRunRecord(
            name="pass",
            recorded_at=None,
            head="pass",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/unrelated.py"}),
            tree_dirty=False,
        ),
        FullRunRecord(
            name="20260813T194513Z-1004f9eb33d6-2320907-full-run.json",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID,),
            workspace="/workspaces/sase_16",
            changed_files=frozenset(
                {
                    "src/sase/monitor/supervise.py",
                    "src/sase/monitor/settlement.py",
                    "src/sase/monitor/start.py",
                    "src/sase/monitor/reconcile.py",
                    "src/sase/ace/tui/models/_loaders/_workflow_loaders.py",
                }
            ),
            tree_dirty=True,
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset()
    excluded = attributable_dirty_failures(runs)
    assert {nodeid for nodeid, _record in excluded} == {_MARKER_AUDIT_NODEID}
    assert len(excluded) == 2


def test_a_clean_tree_intermittent_audit_failure_stays_a_reproducible_flake() -> None:
    # Same node, same shape, but neither failing run is recorded dirty: a
    # genuine cross-workspace intermittency on a source-tree audit must keep
    # meeting the ordinary evidence bar.
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/a.py"}),
            tree_dirty=False,
        ),
        FullRunRecord(
            name="pass",
            recorded_at=None,
            head="pass",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/unrelated.py"}),
            tree_dirty=False,
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/sase/b.py"}),
            tree_dirty=False,
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset({_MARKER_AUDIT_NODEID})
    assert attributable_dirty_failures(runs) == ()


def test_a_dirty_run_still_counts_as_evidence_when_the_change_misses_the_audit_root() -> (
    None
):
    # tree_dirty=True, but the uncommitted change is outside the audit's own
    # scanned root — there is nothing here that could have broken the audit,
    # so this stays ordinary flake evidence.
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID,),
            workspace=WORKSPACE,
            changed_files=frozenset({"docs/unrelated.md"}),
            tree_dirty=True,
        ),
        FullRunRecord(
            name="pass",
            recorded_at=None,
            head="pass",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/unrelated.py"}),
            tree_dirty=False,
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"docs/other.md"}),
            tree_dirty=True,
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset({_MARKER_AUDIT_NODEID})
    assert attributable_dirty_failures(runs) == ()


def test_an_unresolved_tree_dirty_flag_is_never_treated_as_clean() -> None:
    # tree_dirty=None (unresolvable, or a pre-existing record written before
    # this field existed) must not be read as "known clean" and must not be
    # read as "known dirty" either — it stays ordinary evidence either way.
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/a.py"}),
            tree_dirty=None,
        ),
        FullRunRecord(
            name="pass",
            recorded_at=None,
            head="pass",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/unrelated.py"}),
            tree_dirty=None,
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/sase/b.py"}),
            tree_dirty=None,
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset({_MARKER_AUDIT_NODEID})
    assert attributable_dirty_failures(runs) == ()


def test_a_dirty_source_audit_failure_on_an_unregistered_node_stays_evidence() -> None:
    # tree_dirty=True and the changed file is under src/sase/, but the failing
    # node is not a registered source-tree audit — nothing here explains an
    # ordinary test's failure, so the discount must not apply.
    nodeid = "tests/test_x.py::test_flaky"
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(nodeid,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/a.py"}),
            tree_dirty=True,
        ),
        FullRunRecord(
            name="pass",
            recorded_at=None,
            head="pass",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/unrelated.py"}),
            tree_dirty=False,
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/sase/b.py"}),
            tree_dirty=True,
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset({nodeid})
    assert attributable_dirty_failures(runs) == ()


def test_attributable_dirty_failures_respects_max_failures_per_run() -> None:
    # Mirrors reproducible_flake_nodeids' own catastrophic-run discount: a run
    # with too many failures to be flake-gate eligible in the first place
    # should not contribute to the dirty-attribution count either.
    runs = (
        FullRunRecord(
            name="broken",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(_MARKER_AUDIT_NODEID, "tests/test_y.py::test_a"),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/a.py"}),
            tree_dirty=True,
        ),
    )

    assert attributable_dirty_failures(runs, max_failures_per_run=1) == ()
    assert attributable_dirty_failures(runs, max_failures_per_run=2) == (
        (_MARKER_AUDIT_NODEID, "broken"),
    )


_PROC_INVARIANT_NODEID = (
    "tests/test_proc_submission_static_invariants.py"
    "::test_production_proc_writers_do_not_emit_legacy_kinds"
)


def test_an_invariant_style_source_audit_is_also_attributable_when_dirty() -> None:
    # The proc-submission static invariants walk every src/sase/ module and
    # assert the scan finds no offender, so an agent's own uncommitted edit
    # breaks them in that workspace exactly the way an inventory audit breaks:
    # deterministically and correctly. Registered after the fact because this
    # audit landed while sase-mi was still open.
    runs = (
        FullRunRecord(
            name="a",
            recorded_at=None,
            head="aaa",
            mode="fast",
            failures=(_PROC_INVARIANT_NODEID,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/sase/ace/tui/durable_submit.py"}),
            tree_dirty=True,
        ),
        FullRunRecord(
            name="pass",
            recorded_at=None,
            head="pass",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/sase/unrelated.py"}),
            tree_dirty=False,
        ),
        FullRunRecord(
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(_PROC_INVARIANT_NODEID,),
            workspace="/workspaces/sase_9",
            changed_files=frozenset({"src/sase/procs/submit.py"}),
            tree_dirty=True,
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset()
    assert {nodeid for nodeid, _record in attributable_dirty_failures(runs)} == {
        _PROC_INVARIANT_NODEID
    }


def test_every_registered_source_audit_file_still_exists() -> None:
    # The registry is keyed by test-file path, so renaming or splitting a
    # registered audit silently stops excluding its dirty-tree failures and
    # regresses sase-lc without any test going red. Fail loudly instead.
    repo_root = Path(__file__).resolve().parents[1]
    missing = sorted(
        relpath
        for relpath in _SOURCE_AUDIT_SCAN_ROOTS
        if not (repo_root / relpath).is_file()
    )

    assert missing == []
