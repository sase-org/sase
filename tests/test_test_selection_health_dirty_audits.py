"""Unit tests for the dirty-tree discount on source-tree audit failures — sase-lc.

A source-tree audit (an AST or text scan compared against a checked-in reviewed
inventory) can fail deterministically because the recording workspace's own
uncommitted edit under the audited root legitimately broke it; that is not
cross-workspace intermittency and must not be promoted into shared flake debt.
These tests pin `_SOURCE_AUDIT_SCAN_ROOTS` and `_is_attributable_dirty_failure`
in `tests._test_selection_health_correlation` against the evidence bar in
``test_test_selection_health_flake_gate.py``.
"""

from __future__ import annotations

from pathlib import Path

from tests._selection_health_case_helpers import WORKSPACE
from tests._test_selection_health import (
    attributable_dirty_failures,
    reproducible_flake_nodeids,
)
from tests._test_selection_health_correlation import _SOURCE_AUDIT_SCAN_ROOTS
from tests._test_selection_health_records import FullRunRecord


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
