"""Unit tests for the historical selection backtest.

Everything here runs against the synthetic repository from
``tests._test_selection_fixtures`` and a coverage database this module writes
itself, so no assertion depends on this repository's own history or on a
baseline downloaded from CI.

The shape the fixture adds for these tests is the one the backtest exists to
find: a test file that executes a module it never imports. The static closure
cannot see it, coverage can, and the gap between the two arms is exactly that
test file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from coverage import CoverageData

from tests._test_selection import SelectionOptions
from tests._test_selection_backtest import (
    ANCESTOR,
    CLOSURE_ARM,
    DESCENDANT,
    SKIP_BASELINE_NOT_ANCESTOR,
    SKIP_EMPTY_GROUND_TRUTH,
    SKIP_NO_SRC_PYTHON,
    SKIP_ROOT_COMMIT,
    UNION_ARM,
    UNRELATED,
    ArmResult,
    baseline_direction,
    execute_probes,
    list_commits,
    replay_worktree,
    resolve_backtest_baseline,
    run_backtest,
)
from tests._test_selection_backtest_report import (
    arm_statistics,
    backtest_payload,
    percentile,
    render_report,
)
from tests._test_selection_changes import commit_change_set
from tests._test_selection_fixtures import _git, _write, build_fixture_repo
from tests._test_selection_graph import SelectionError


DYNAMIC_TEST = "tests/test_dynamic.py"


@pytest.fixture
def contexts_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "contexts"
    directory.mkdir(parents=True)
    return directory


def _rev(repo: Path, ref: str = "HEAD") -> str:
    return subprocess.run(
        ["git", "rev-parse", ref],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _write_baseline(path: Path, coverage_map: dict[str, dict[str, list[int]]]) -> None:
    """Write a coverage database recording ``{measured file: {context: lines}}``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    data = CoverageData(basename=str(path))
    data.set_context("tests/test_placeholder.py::test_placeholder|run")
    data.add_lines({"src/pkg/never_changed.py": [1]})
    for measured_file, contexts in coverage_map.items():
        for context, lines in contexts.items():
            data.set_context(context)
            data.add_lines({measured_file: lines})
    data.write()


@pytest.fixture
def history(tmp_path: Path, contexts_dir: Path) -> Path:
    """A fixture repo whose second commit edits a module coverage has ground truth for.

    Commit 1 is the baseline the coverage database is recorded at; commit 2 is
    the commit the backtest replays.
    """
    repo = build_fixture_repo(tmp_path)
    _write(repo, DYNAMIC_TEST, "def test_dynamic() -> None:\n    assert True\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add a test that imports nothing")
    baseline_sha = _rev(repo)

    _write(repo, "src/pkg/a.py", "VALUE = 2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "change a")

    _write_baseline(
        contexts_dir / f"{baseline_sha}.sqlite",
        {
            "src/pkg/a.py": {
                f"{DYNAMIC_TEST}::test_dynamic|run": [1],
                "tests/test_a.py::test_a|run": [1],
            }
        },
    )
    return repo


def _options() -> SelectionOptions:
    # The fixture suite is 21 test files, so the real 0.25 escalation ratio
    # would escalate this change set and hide the recall reading behind a
    # full-suite run. Escalation has its own test below.
    return SelectionOptions(depth=2, max_ratio=1.0)


# --------------------------------------------------------------------------
# commit_change_set
# --------------------------------------------------------------------------


def test_commit_change_set_is_the_commits_own_diff(history: Path) -> None:
    change_set = commit_change_set(history, _rev(history))

    assert change_set.paths == ("src/pkg/a.py",)
    assert change_set.merge_base == _rev(history, "HEAD^")
    assert change_set.head == _rev(history)
    assert change_set.tree_dirty is False


def test_commit_change_set_rejects_a_root_commit(history: Path) -> None:
    root = subprocess.run(
        ["git", "rev-list", "--max-parents=0", "HEAD"],
        cwd=history,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()

    with pytest.raises(SelectionError):
        commit_change_set(history, root)


# --------------------------------------------------------------------------
# The replay worktree
# --------------------------------------------------------------------------


def test_replay_worktree_is_removed_and_never_touches_the_checkout(
    history: Path,
) -> None:
    before = _rev(history)

    with replay_worktree(history) as worktree:
        assert (worktree / "src" / "pkg" / "a.py").exists()
        subprocess.run(
            ["git", "checkout", "--detach", "--force", "--quiet", "HEAD^"],
            cwd=worktree,
            check=True,
            capture_output=True,
        )
        assert (history / "src" / "pkg" / "a.py").read_text() == "VALUE = 2\n"
        path = worktree

    assert not path.exists()
    assert _rev(history) == before


# --------------------------------------------------------------------------
# Baseline resolution and direction
# --------------------------------------------------------------------------


def test_resolve_backtest_baseline_prefers_the_newest_cached_database(
    history: Path, contexts_dir: Path
) -> None:
    baseline = resolve_backtest_baseline(contexts_dir)

    assert baseline is not None
    assert baseline.sha == _rev(history, "HEAD^")


def test_resolve_backtest_baseline_accepts_an_explicit_sha(
    history: Path, contexts_dir: Path
) -> None:
    wanted = _rev(history, "HEAD^")

    assert resolve_backtest_baseline(contexts_dir, wanted[:12]) is not None
    assert resolve_backtest_baseline(contexts_dir, "f" * 40) is None


def test_baseline_direction_names_where_the_baseline_sits(history: Path) -> None:
    head = _rev(history)
    parent = _rev(history, "HEAD^")

    assert baseline_direction(history, parent, head) == ANCESTOR
    assert baseline_direction(history, head, parent) == DESCENDANT
    assert baseline_direction(history, "0" * 40, head) == UNRELATED


def test_list_commits_returns_newest_first(history: Path) -> None:
    commits = list_commits(history, 2)

    assert [sha for sha, _ in commits] == [_rev(history), _rev(history, "HEAD^")]
    assert commits[0][1] == "change a"


# --------------------------------------------------------------------------
# The measurement itself
# --------------------------------------------------------------------------


def test_backtest_measures_the_closure_blind_spot_the_contexts_arm_covers(
    history: Path, contexts_dir: Path
) -> None:
    report = run_backtest(
        history, limit=1, options=_options(), contexts_dir=contexts_dir
    )

    assert len(report.replays) == 1
    replay = report.replays[0]
    assert replay.direction == ANCESTOR
    assert replay.ground_truth == ("tests/test_a.py", DYNAMIC_TEST)
    assert replay.closure.missed == (DYNAMIC_TEST,)
    assert replay.closure.recall == pytest.approx(0.5)
    assert replay.union.missed == ()
    assert replay.union.recall == pytest.approx(1.0)


def test_backtest_reports_the_root_commit_rather_than_dropping_it(
    history: Path, contexts_dir: Path
) -> None:
    report = run_backtest(
        history,
        limit=99,
        options=_options(),
        contexts_dir=contexts_dir,
        include_descendant=True,
    )

    assert report.examined == 3
    assert report.skip_counts()[SKIP_ROOT_COMMIT] == 1
    assert len(report.replays) + len(report.skipped) == report.examined


def test_backtest_reports_a_commit_that_changed_no_src_python(
    history: Path, contexts_dir: Path
) -> None:
    _write(history, "docs/development.md", "# docs\nmore\n")
    _git(history, "add", "-A")
    _git(history, "commit", "-q", "-m", "docs only")

    report = run_backtest(
        history, limit=1, options=_options(), contexts_dir=contexts_dir
    )

    assert report.replays == []
    assert report.skip_counts() == {SKIP_NO_SRC_PYTHON: 1}


def test_backtest_reports_a_change_no_test_ever_executed(
    history: Path, contexts_dir: Path
) -> None:
    _write(history, "src/pkg/hub.py", "from .a import VALUE\nOTHER = 2\n")
    _git(history, "add", "-A")
    _git(history, "commit", "-q", "-m", "touch a module coverage never saw")

    report = run_backtest(
        history, limit=1, options=_options(), contexts_dir=contexts_dir
    )

    assert report.skip_counts() == {SKIP_EMPTY_GROUND_TRUTH: 1}


def test_backtest_without_a_cached_baseline_measures_nothing(
    history: Path, tmp_path: Path
) -> None:
    report = run_backtest(
        history,
        limit=1,
        options=_options(),
        contexts_dir=tmp_path / "empty",
    )

    assert report.baseline is None
    assert report.replays == []
    assert "no coverage-contexts baseline cached" in render_report(report)[0]


def test_backtest_skips_descendant_baselines_unless_asked(
    history: Path, contexts_dir: Path
) -> None:
    """A newer baseline puts the commit being replayed *behind* the ground truth.

    Ground truth for that direction is widened by every later change to the same
    file, so it is opt-in and labelled rather than folded into the headline.
    """
    _write(history, "src/pkg/a.py", "VALUE = 3\n")
    _git(history, "add", "-A")
    _git(history, "commit", "-q", "-m", "change a again")
    _write_baseline(
        contexts_dir / f"{_rev(history)}.sqlite",
        {
            "src/pkg/a.py": {
                f"{DYNAMIC_TEST}::test_dynamic|run": [1],
                "tests/test_a.py::test_a|run": [1],
            }
        },
    )
    target = _rev(history, "HEAD^")

    strict = run_backtest(
        history,
        limit=1,
        options=_options(),
        contexts_dir=contexts_dir,
        rev=target,
    )
    relaxed = run_backtest(
        history,
        limit=1,
        options=_options(),
        contexts_dir=contexts_dir,
        rev=target,
        include_descendant=True,
    )

    assert strict.replays == []
    assert strict.skip_counts() == {SKIP_BASELINE_NOT_ANCESTOR: 1}
    assert relaxed.direction_counts() == {DESCENDANT: 1}


def test_an_escalated_arm_has_perfect_recall_by_definition(
    history: Path, contexts_dir: Path
) -> None:
    report = run_backtest(
        history,
        limit=1,
        options=SelectionOptions(depth=2, max_ratio=0.01),
        contexts_dir=contexts_dir,
    )

    replay = report.replays[0]
    assert replay.closure.escalated is True
    assert replay.closure.selected == ()
    assert replay.closure.missed == ()
    assert replay.closure.recall == pytest.approx(1.0)


def test_the_replay_never_fires_core_identity_changed(
    history: Path, contexts_dir: Path
) -> None:
    """Every replay shares one environment fingerprint, so it cannot escalate on it."""
    report = run_backtest(
        history, limit=1, options=_options(), contexts_dir=contexts_dir
    )

    assert "core-identity-changed" not in report.replays[0].closure.rules


# --------------------------------------------------------------------------
# --execute
# --------------------------------------------------------------------------


def test_execute_probes_run_the_missed_test_files(
    history: Path, contexts_dir: Path
) -> None:
    report = run_backtest(
        history, limit=1, options=_options(), contexts_dir=contexts_dir
    )

    probes = execute_probes(history, report, arm=CLOSURE_ARM, limit=1)

    assert len(probes) == 1
    assert probes[0].missed == (DYNAMIC_TEST,)
    assert probes[0].returncode == 0
    assert "passed" in probes[0].summary


def test_execute_probes_are_empty_without_a_blind_spot(
    history: Path, contexts_dir: Path
) -> None:
    report = run_backtest(
        history, limit=1, options=_options(), contexts_dir=contexts_dir
    )

    assert execute_probes(history, report, arm=UNION_ARM, limit=1) == []


# --------------------------------------------------------------------------
# Reporting
# --------------------------------------------------------------------------


def test_percentile_reports_a_rank_some_commit_actually_had() -> None:
    values = [0.2, 0.5, 0.9, 1.0]

    assert percentile(values, 0.90) == 1.0
    assert percentile(values, 0.10) == 0.2
    assert percentile([], 0.5) == 0.0


def _arm(*, missed: int, total: int, escalated: bool = False) -> ArmResult:
    return ArmResult(
        name=CLOSURE_ARM,
        selected=("tests/test_a.py",),
        escalated=escalated,
        rules=(),
        missed=tuple(f"tests/test_{index}.py" for index in range(missed)),
        ground_truth_count=total,
    )


def test_arm_recall_is_perfect_when_there_is_nothing_to_find() -> None:
    assert _arm(missed=0, total=0).recall == pytest.approx(1.0)
    assert _arm(missed=1, total=4).recall == pytest.approx(0.75)


def test_arm_statistics_separate_escalations_from_genuine_hits(
    history: Path, contexts_dir: Path
) -> None:
    report = run_backtest(
        history, limit=1, options=_options(), contexts_dir=contexts_dir
    )

    stats = arm_statistics(report, CLOSURE_ARM)
    assert stats["commits"] == 1
    assert stats["blind_spot_commits"] == 1
    assert stats["missed_total"] == 1
    assert stats["escalated_commits"] == 0
    assert stats["recall_worst"] == pytest.approx(0.5)


def test_render_report_itemises_every_skip_reason(
    history: Path, contexts_dir: Path
) -> None:
    report = run_backtest(
        history,
        limit=99,
        options=_options(),
        contexts_dir=contexts_dir,
        include_descendant=True,
    )

    rendered = "\n".join(render_report(report))
    assert "commits skipped: 2" in rendered
    assert SKIP_ROOT_COMMIT in rendered
    assert "no parent commit to diff against" in rendered
    assert "1.0 by construction" in rendered


def test_backtest_payload_round_trips_the_measurement(
    history: Path, contexts_dir: Path
) -> None:
    report = run_backtest(
        history, limit=1, options=_options(), contexts_dir=contexts_dir
    )

    payload = backtest_payload(report)
    assert payload["baseline"] == _rev(history, "HEAD^")
    assert payload["commits_measured"] == 1
    assert [arm["arm"] for arm in payload["arms"]] == [CLOSURE_ARM, UNION_ARM]
    assert payload["commits"][0]["arms"][CLOSURE_ARM]["missed"] == [DYNAMIC_TEST]
    assert payload["executed"] is False
