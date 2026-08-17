"""Unit tests for retiring a fixed node's pre-fix reproducible-flake evidence.

A node that meets the reproducible-flake evidence bar (see
`test_test_selection_health_flake_gate.py`) stays evidence forever unless a
caller opts in to a `retired_evidence` oracle that discounts one node's
failures recorded at or before a declared fix instant. These tests pin that
retirement at the evidence-bar level: retiring a node clears it, retiring only
part of a node's evidence can still leave it flagged, retiring one node never
touches another's evidence, and omitting the oracle changes nothing for
existing callers. The CLI-level, real-file-syntax proof lives in
`test_selection_health_tool.py`.
"""

from __future__ import annotations

from tests._selection_health_case_helpers import WORKSPACE
from tests._test_selection_health import (
    reproducible_flake_nodeids,
    retired_flake_evidence,
    stale_flake_nodeids,
)
from tests._test_selection_health_records import FullRunRecord


def test_retired_evidence_clears_a_node_that_meets_the_evidence_bar() -> None:
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
    assert (
        reproducible_flake_nodeids(runs, retired_evidence=lambda n, _run: n == nodeid)
        == frozenset()
    )


def test_a_node_still_failing_past_the_fix_point_stays_flagged() -> None:
    # Only the earliest occurrence predates the declared fix; the two later,
    # disjoint occurrences with an interleaved pass between them are still
    # enough evidence on their own.
    nodeid = "tests/test_x.py::test_still_broken"
    fixed_at = "2026-08-01T12:00:00Z"
    runs = (
        FullRunRecord(
            name="early",
            recorded_at="2026-08-01T00:00:00Z",
            head="e",
            mode="fast",
            failures=(nodeid,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
        FullRunRecord(
            name="pass1",
            recorded_at="2026-08-02T00:00:00Z",
            head="p1",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/unrelated1.py"}),
        ),
        FullRunRecord(
            name="mid",
            recorded_at="2026-08-03T00:00:00Z",
            head="m",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
        FullRunRecord(
            name="pass2",
            recorded_at="2026-08-04T00:00:00Z",
            head="p2",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/unrelated2.py"}),
        ),
        FullRunRecord(
            name="late",
            recorded_at="2026-08-05T00:00:00Z",
            head="l",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/c.py"}),
        ),
    )

    def retired_evidence(candidate: str, full_run: FullRunRecord) -> bool:
        return (
            candidate == nodeid
            and full_run.recorded_at is not None
            and full_run.recorded_at <= fixed_at
        )

    assert reproducible_flake_nodeids(
        runs, retired_evidence=retired_evidence
    ) == frozenset({nodeid})


def test_retiring_one_node_leaves_another_flaky_node_reported() -> None:
    node_a = "tests/test_x.py::test_a_flaky"
    node_b = "tests/test_x.py::test_b_flaky"
    runs = (
        FullRunRecord(
            name="a1",
            recorded_at=None,
            head="a1",
            mode="fast",
            failures=(node_a,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a1.py"}),
        ),
        FullRunRecord(
            name="a-pass",
            recorded_at=None,
            head="ap",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a-pass.py"}),
        ),
        FullRunRecord(
            name="a2",
            recorded_at=None,
            head="a2",
            mode="fast",
            failures=(node_a,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/a2.py"}),
        ),
        FullRunRecord(
            name="b1",
            recorded_at=None,
            head="b1",
            mode="fast",
            failures=(node_b,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/b1.py"}),
        ),
        FullRunRecord(
            name="b-pass",
            recorded_at=None,
            head="bp",
            mode="fast",
            failures=(),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/b-pass.py"}),
        ),
        FullRunRecord(
            name="b2",
            recorded_at=None,
            head="b2",
            mode="fast",
            failures=(node_b,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b2.py"}),
        ),
    )

    assert reproducible_flake_nodeids(runs) == frozenset({node_a, node_b})
    assert reproducible_flake_nodeids(
        runs, retired_evidence=lambda n, _run: n == node_a
    ) == frozenset({node_b})


def test_omitting_retired_evidence_reproduces_the_unretired_result() -> None:
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
            name="b",
            recorded_at=None,
            head="bbb",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
    )

    assert reproducible_flake_nodeids(runs) == reproducible_flake_nodeids(
        runs, retired_evidence=None
    )


def test_stale_flake_nodeids_honours_retirement_too() -> None:
    nodeid = "tests/test_run_pytest_main.py::test_renamed_away"
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

    assert stale_flake_nodeids(runs, collectible=lambda _n: False) == frozenset(
        {nodeid}
    )
    assert (
        stale_flake_nodeids(
            runs,
            collectible=lambda _n: False,
            retired_evidence=lambda n, _run: n == nodeid,
        )
        == frozenset()
    )


def test_retired_flake_evidence_reports_exactly_the_discounted_pairs() -> None:
    nodeid = "tests/test_x.py::test_flaky"
    runs = (
        FullRunRecord(
            name="a",
            recorded_at="2026-08-01T00:00:00Z",
            head="aaa",
            mode="fast",
            failures=(nodeid,),
            workspace=WORKSPACE,
            changed_files=frozenset({"src/a.py"}),
        ),
        FullRunRecord(
            name="b",
            recorded_at="2026-08-02T00:00:00Z",
            head="bbb",
            mode="fast",
            failures=(nodeid,),
            workspace="/workspaces/sase_3",
            changed_files=frozenset({"src/b.py"}),
        ),
    )

    assert retired_flake_evidence(
        runs, retired_evidence=lambda _n, full_run: full_run.name == "a"
    ) == ((nodeid, "a"),)
    assert retired_flake_evidence(runs, retired_evidence=lambda _n, _run: False) == ()
