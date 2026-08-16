"""Unit tests for the oracles the known-flake gate leans on.

A renamed or deleted test's old node ID can never pass again, so without a
staleness check it would meet the reproducible-flake evidence bar forever; and
ordering the evidence needs commit positions the repo may no longer resolve.
These tests pin `collectible_nodeid_oracle`, `stale_flake_nodeids`, and
`unresolved_commit_order_count`. The evidence bar itself lives in
``test_test_selection_health_flake_gate.py``.
"""

from __future__ import annotations

from pathlib import Path

from tests._selection_health_case_helpers import WORKSPACE
from tests._test_selection_health import (
    collectible_nodeid_oracle,
    reproducible_flake_nodeids,
    stale_flake_nodeids,
    unresolved_commit_order_count,
)
from tests._test_selection_health_records import FullRunRecord


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
