"""Replay real commits through the selector and measure recall against coverage.

``just selection-health`` can only learn that the diff-scoped lane missed a test
from a *later* full run, in the *same* workspace, over a superset change set. In
ephemeral workspaces that combination essentially only happens at landing, so
the correlatable sample grows about as fast as epics land — far too slowly to
answer "is the fast lane sound?".

This module answers the same question from history instead. For each of the last
N commits it takes the commit's own diff against its parent as a change set,
rebuilds the import graph *as of that commit*, and computes the selection the
scoped lane would have produced. Ground truth for the same change set comes from
a cached per-test coverage baseline: the test files coverage recorded as having
executed the lines that commit touched. Recall is the share of that ground truth
the selection contained.

Three properties of the measurement are worth stating up front, because they
bound what a reading from it proves:

* **The contexts arm is 1.0 by construction.** The selector unions the very same
  coverage query into its selection, so "closure plus contexts" cannot miss
  ground truth. That is not a null result: the *gap* between the two arms is
  precisely the exposure a workspace with no cached baseline runs with, which is
  the number phase ``compensate`` is tuned against.
* **The replay is conservative.** ``core-identity-changed`` cannot fire
  historically — the venv that a commit was tested against is long gone — so
  runs that escalated in reality may replay as narrow selections here. The
  harness therefore under-reports recall rather than over-reports it.
* **Recall is a proxy.** A missed test file is only a *true* false negative if it
  would actually have failed. ``--execute`` checks that for a small sample by
  running the missed files; it is opt-in and belongs to no ``check`` path.

Rendering lives in :mod:`tests._test_selection_backtest_report`; this half owns
the replay.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from tests._test_selection import Selection, SelectionOptions, select_tests
from tests._test_selection_changes import ChangeSet, commit_change_set
from tests._test_selection_contexts import (
    CONTEXTS_DIR_ENV,
    CONTEXTS_DISABLED_ENV,
    ContextBaseline,
    baseline_changed_lines,
    cached_baselines,
    find_tests_touching,
)
from tests._test_selection_graph import (
    ImportGraph,
    SelectionError,
    build_import_graph,
    is_test_file,
    is_visual_path,
    run_git,
)


DEFAULT_LIMIT = 50
DEFAULT_EXECUTE_LIMIT = 3
DEFAULT_EXECUTE_TIMEOUT = 1800

#: Mirrors ``tools/run_pytest``'s ``FAST_MARKER_EXPRESSION``. Duplicated rather
#: than imported because ``tools/run_pytest`` is a script, not a module, and an
#: importable copy of it is not worth the coupling for one probe mode.
EXECUTE_MARKER_EXPRESSION = "not slow and not visual"

#: The environment fingerprint stamped on every replayed selection. A commit's
#: real fingerprint is unrecoverable, so every replay shares one and
#: ``core-identity-changed`` never fires. See the module docstring.
REPLAY_ENVIRONMENT: Mapping[str, str] = {"replay": "selection-backtest"}

ANCESTOR = "baseline-ancestor"
DESCENDANT = "baseline-descendant"
UNRELATED = "baseline-unrelated"

CLOSURE_ARM = "closure-only"
UNION_ARM = "closure+contexts"

SKIP_ROOT_COMMIT = "root-commit"
SKIP_BASELINE_NOT_ANCESTOR = "baseline-not-ancestor"
SKIP_BASELINE_UNRELATED = "baseline-unrelated"
SKIP_NO_SRC_PYTHON = "no-src-python-changed"
SKIP_NO_BASELINE_LINES = "no-lines-in-baseline"
SKIP_EMPTY_GROUND_TRUTH = "empty-ground-truth"
SKIP_REPLAY_FAILED = "replay-failed"


def require_coverage() -> None:
    """Refuse to measure anything if ``coverage`` cannot be imported.

    :func:`~tests._test_selection_contexts.find_tests_touching` swallows that
    ImportError and returns an empty result, which is right for *selection* —
    contexts are an optional accelerant and the closure carries the run. For a
    measurement harness the same silence is a lie: every commit skips as
    ``empty-ground-truth`` and the report reads like a finding about the
    selector rather than a shell that never activated the venv.
    """
    if importlib.util.find_spec("coverage") is None:
        raise SelectionError(
            "the `coverage` package is not importable, so there is no ground "
            "truth to measure against — run this through `just "
            "selection-backtest`, or activate the workspace venv first"
        )


#: Why each skip reason means "this commit cannot contribute a recall reading".
#: Rendered verbatim by the report, because a skipped commit that nobody can
#: explain is indistinguishable from a bug in the harness.
SKIP_EXPLANATIONS = {
    SKIP_ROOT_COMMIT: "no parent commit to diff against",
    SKIP_BASELINE_NOT_ANCESTOR: (
        "the baseline is not an ancestor of this commit "
        "(pass --include-descendant-baseline to accept the reverse direction)"
    ),
    SKIP_BASELINE_UNRELATED: "the baseline shares no history with this commit",
    SKIP_NO_SRC_PYTHON: "the commit changed no src/**.py, which coverage indexes",
    SKIP_NO_BASELINE_LINES: (
        "no changed file has a baseline-side line to query — it was added after "
        "the baseline, or it is identical to the baseline's copy"
    ),
    SKIP_EMPTY_GROUND_TRUTH: "coverage recorded no test executing the changed lines",
    SKIP_REPLAY_FAILED: "the selector raised while replaying this commit",
}


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ArmResult:
    """One selection arm's verdict on one commit."""

    name: str
    selected: tuple[str, ...]
    escalated: bool
    rules: tuple[str, ...]
    missed: tuple[str, ...]
    ground_truth_count: int

    @property
    def recall(self) -> float:
        """An escalated run tests everything, so it misses nothing by definition."""
        if self.escalated or not self.ground_truth_count:
            return 1.0
        found = self.ground_truth_count - len(self.missed)
        return found / self.ground_truth_count


@dataclass(frozen=True)
class CommitReplay:
    sha: str
    subject: str
    changed_files: tuple[str, ...]
    ground_truth: tuple[str, ...]
    direction: str
    universe_count: int
    closure: ArmResult
    union: ArmResult

    def arm(self, name: str) -> ArmResult:
        return self.closure if name == CLOSURE_ARM else self.union


@dataclass(frozen=True)
class SkippedCommit:
    sha: str
    subject: str
    reason: str


@dataclass(frozen=True)
class ExecutedProbe:
    """The result of actually running one commit's missed test files."""

    sha: str
    missed: tuple[str, ...]
    returncode: int
    summary: str


@dataclass
class BacktestReport:
    baseline: ContextBaseline | None
    limit: int
    examined: int
    replays: list[CommitReplay] = field(default_factory=list)
    skipped: list[SkippedCommit] = field(default_factory=list)
    probes: list[ExecutedProbe] = field(default_factory=list)
    executed: bool = False

    def skip_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for entry in self.skipped:
            counts[entry.reason] = counts.get(entry.reason, 0) + 1
        return dict(sorted(counts.items()))

    def direction_counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for replay in self.replays:
            counts[replay.direction] = counts.get(replay.direction, 0) + 1
        return dict(sorted(counts.items()))


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------


def resolve_backtest_baseline(
    directory: Path, sha: str | None = None
) -> ContextBaseline | None:
    """Pick the coverage baseline to measure against.

    Unlike selection's own :func:`~tests._test_selection_contexts.resolve_baseline`
    this deliberately does *not* prefer an ancestor of ``HEAD``: the backtest
    walks backwards through history, so the newest baseline is the one with the
    most commits behind it to replay.
    """
    baselines = cached_baselines(directory)
    if sha is not None:
        for baseline in baselines:
            if baseline.sha == sha or baseline.sha.startswith(sha):
                return baseline
        return None
    return baselines[0] if baselines else None


def baseline_direction(root: Path, baseline_sha: str, sha: str) -> str:
    """Where ``baseline_sha`` sits relative to ``sha`` in the commit graph."""
    if _is_ancestor(root, baseline_sha, sha):
        return ANCESTOR
    if _is_ancestor(root, sha, baseline_sha):
        return DESCENDANT
    return UNRELATED


def _is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


# --------------------------------------------------------------------------
# The replay worktree
# --------------------------------------------------------------------------


@contextmanager
def replay_worktree(root: Path) -> Iterator[Path]:
    """Yield one reusable detached worktree, removed on the way out.

    One worktree checked out N times, never N worktrees: a full clone of this
    repository per replayed commit is minutes of I/O for no added fidelity. The
    invoking checkout is never touched — that is the whole reason this exists
    rather than the harness stashing and checking out in place.
    """
    parent = Path(tempfile.mkdtemp(prefix="sase-selection-backtest-"))
    path = parent / "worktree"
    run_git(root, "worktree", "add", "--detach", "--quiet", str(path), "HEAD")
    try:
        yield path
    finally:
        try:
            run_git(root, "worktree", "remove", "--force", str(path))
        except SelectionError:
            shutil.rmtree(path, ignore_errors=True)
        shutil.rmtree(parent, ignore_errors=True)
        try:
            run_git(root, "worktree", "prune")
        except SelectionError:
            pass


def checkout_commit(worktree: Path, sha: str) -> None:
    run_git(worktree, "checkout", "--detach", "--force", "--quiet", sha)


# --------------------------------------------------------------------------
# Ground truth
# --------------------------------------------------------------------------


def ground_truth_for(
    worktree: Path,
    baseline: ContextBaseline,
    changed_paths: Sequence[str],
    known_test_files: frozenset[str],
) -> tuple[tuple[str, ...], str | None]:
    """The test files coverage says executed the lines this change set touched.

    Returns ``(ground_truth, skip_reason)``; exactly one of the two is
    meaningful. The query mirrors
    :func:`~tests._test_selection_contexts.select_from_contexts` line for line so
    that the closure-only arm is measured against the same ground truth the
    contexts arm would have unioned in — anything else would compare the
    selector against a yardstick it never had access to.
    """
    candidates = [
        path
        for path in changed_paths
        if path.startswith("src/") and path.endswith(".py")
    ]
    if not candidates:
        return (), SKIP_NO_SRC_PYTHON

    targets = {
        path: lines
        for path, lines in baseline_changed_lines(
            worktree, baseline.sha, candidates
        ).items()
        if lines
    }
    if not targets:
        return (), SKIP_NO_BASELINE_LINES

    candidates_found = find_tests_touching(baseline.path, targets)[0]
    truth = tuple(
        sorted(
            path
            for path in candidates_found
            if path in known_test_files and not is_visual_path(path)
        )
    )
    if not truth:
        return (), SKIP_EMPTY_GROUND_TRUTH
    return truth, None


# --------------------------------------------------------------------------
# Replaying one commit
# --------------------------------------------------------------------------


@contextmanager
def _contexts_environment(directory: Path) -> Iterator[None]:
    """Point selection's contexts lookup at ``directory`` and nowhere else.

    Both the override and the kill switch are forced, because the harness must
    produce the same numbers on a host whose environment happens to disable
    contexts as on one that does not.
    """
    previous = {
        key: os.environ.get(key) for key in (CONTEXTS_DIR_ENV, CONTEXTS_DISABLED_ENV)
    }
    os.environ[CONTEXTS_DIR_ENV] = str(directory)
    os.environ.pop(CONTEXTS_DISABLED_ENV, None)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _arm(name: str, selection: Selection, ground_truth: Sequence[str]) -> ArmResult:
    selected = frozenset(selection.selected)
    missed = tuple(sorted(path for path in ground_truth if path not in selected))
    return ArmResult(
        name=name,
        selected=selection.selected,
        escalated=selection.escalated,
        rules=selection.rules,
        missed=() if selection.escalated else missed,
        ground_truth_count=len(ground_truth),
    )


def _select_at(
    worktree: Path,
    options: SelectionOptions,
    change_set: ChangeSet,
    graph: ImportGraph,
    contexts_dir: Path,
) -> Selection:
    with _contexts_environment(contexts_dir):
        return select_tests(
            worktree,
            options,
            graph=graph,
            change_set=change_set,
            environment=REPLAY_ENVIRONMENT,
            previous_manifest={},
            contexts_store=worktree / ".selection-backtest-store",
        )


def replay_commit(
    worktree: Path,
    sha: str,
    subject: str,
    *,
    baseline: ContextBaseline,
    direction: str,
    options: SelectionOptions,
    graph_cache: Path,
    empty_contexts: Path,
    full_contexts: Path,
) -> CommitReplay | SkippedCommit:
    """Replay one commit through both arms, or say why it cannot be replayed."""
    checkout_commit(worktree, sha)
    try:
        change_set = commit_change_set(worktree, sha)
    except SelectionError:
        return SkippedCommit(sha=sha, subject=subject, reason=SKIP_ROOT_COMMIT)

    graph = build_import_graph(worktree, cache_path=graph_cache, use_cache=True)
    universe = frozenset(
        path for path in graph.paths if is_test_file(path) and not is_visual_path(path)
    )
    truth, reason = ground_truth_for(worktree, baseline, change_set.paths, universe)
    if reason is not None:
        return SkippedCommit(sha=sha, subject=subject, reason=reason)

    try:
        closure = _select_at(worktree, options, change_set, graph, empty_contexts)
        union = _select_at(worktree, options, change_set, graph, full_contexts)
    except SelectionError:
        return SkippedCommit(sha=sha, subject=subject, reason=SKIP_REPLAY_FAILED)

    return CommitReplay(
        sha=sha,
        subject=subject,
        changed_files=change_set.paths,
        ground_truth=truth,
        direction=direction,
        universe_count=closure.universe_count,
        closure=_arm(CLOSURE_ARM, closure, truth),
        union=_arm(UNION_ARM, union, truth),
    )


# --------------------------------------------------------------------------
# Driving the whole backtest
# --------------------------------------------------------------------------


def list_commits(root: Path, limit: int, rev: str = "HEAD") -> list[tuple[str, str]]:
    raw = run_git(root, "log", f"--max-count={limit}", "--format=%H%x1f%s", rev)
    commits: list[tuple[str, str]] = []
    for line in raw.splitlines():
        if "\x1f" not in line:
            continue
        sha, subject = line.split("\x1f", 1)
        commits.append((sha, subject))
    return commits


def run_backtest(
    root: Path,
    *,
    limit: int = DEFAULT_LIMIT,
    options: SelectionOptions | None = None,
    contexts_dir: Path,
    baseline_sha: str | None = None,
    include_descendant: bool = False,
    rev: str = "HEAD",
    progress: Callable[[str], None] | None = None,
) -> BacktestReport:
    """Replay the last ``limit`` commits and report recall against ground truth."""
    require_coverage()
    options = options or SelectionOptions()
    baseline = resolve_backtest_baseline(contexts_dir, baseline_sha)
    commits = list_commits(root, limit, rev)
    report = BacktestReport(baseline=baseline, limit=limit, examined=len(commits))
    if baseline is None:
        return report

    with replay_worktree(root) as worktree:
        scratch = worktree.parent
        graph_cache = scratch / "graph.json"
        empty_contexts = scratch / "contexts-absent"
        empty_contexts.mkdir(parents=True, exist_ok=True)
        full_contexts = scratch / "contexts-present"
        full_contexts.mkdir(parents=True, exist_ok=True)
        _link_baseline(baseline, full_contexts)

        for index, (sha, subject) in enumerate(commits, start=1):
            if progress is not None:
                progress(f"[{index}/{len(commits)}] {sha[:12]} {subject}")
            direction = baseline_direction(root, baseline.sha, sha)
            if direction == UNRELATED:
                report.skipped.append(
                    SkippedCommit(sha, subject, SKIP_BASELINE_UNRELATED)
                )
                continue
            if direction == DESCENDANT and not include_descendant:
                report.skipped.append(
                    SkippedCommit(sha, subject, SKIP_BASELINE_NOT_ANCESTOR)
                )
                continue
            outcome = replay_commit(
                worktree,
                sha,
                subject,
                baseline=baseline,
                direction=direction,
                options=options,
                graph_cache=graph_cache,
                empty_contexts=empty_contexts,
                full_contexts=full_contexts,
            )
            if isinstance(outcome, SkippedCommit):
                report.skipped.append(outcome)
            else:
                report.replays.append(outcome)
    return report


def _link_baseline(baseline: ContextBaseline, directory: Path) -> None:
    """Expose exactly one baseline under ``directory`` as ``<sha>.sqlite``.

    A symlink keeps a 49 MB database from being copied once per run; a copy is
    the fallback for filesystems that refuse one.
    """
    target = directory / f"{baseline.sha}.sqlite"
    if target.exists() or target.is_symlink():
        return
    try:
        target.symlink_to(baseline.path)
    except OSError:
        shutil.copy2(baseline.path, target)


# --------------------------------------------------------------------------
# `--execute`: recall is a proxy, an executed failure is not
# --------------------------------------------------------------------------


def execute_probes(
    root: Path,
    report: BacktestReport,
    *,
    arm: str = CLOSURE_ARM,
    limit: int = DEFAULT_EXECUTE_LIMIT,
    timeout: int = DEFAULT_EXECUTE_TIMEOUT,
    progress: Callable[[str], None] | None = None,
) -> list[ExecutedProbe]:
    """Run the missed test files for the worst few blind spots.

    A missed test file only proves a false negative if it *fails*. This runs
    them at the commit that missed them, worst blind spot first, and reports
    what happened. It is never wired into a ``check`` path: it checks out old
    commits and runs arbitrary historical tests, which is a measurement act, not
    a gate.
    """
    candidates = sorted(
        (replay for replay in report.replays if replay.arm(arm).missed),
        key=lambda replay: len(replay.arm(arm).missed),
        reverse=True,
    )[:limit]
    if not candidates:
        return []

    probes: list[ExecutedProbe] = []
    with replay_worktree(root) as worktree:
        for replay in candidates:
            missed = replay.arm(arm).missed
            if progress is not None:
                progress(
                    f"executing {len(missed)} missed test file(s) at {replay.sha[:12]}"
                )
            checkout_commit(worktree, replay.sha)
            probes.append(
                _execute_missed(worktree, replay.sha, missed, timeout=timeout)
            )
    return probes


def _execute_missed(
    worktree: Path, sha: str, missed: Sequence[str], *, timeout: int
) -> ExecutedProbe:
    environ = os.environ.copy()
    # A probe that inherited the invoking run's pytest options would be
    # measuring that run's configuration, not this commit's tests.
    for key in ("PYTEST_ADDOPTS", "PYTEST_CURRENT_TEST", "PYTEST_XDIST_WORKER"):
        environ.pop(key, None)
    # The venv's editable `.pth` points at the *invoking* checkout, so without
    # this the historical tests would run against today's `src/sase`. PYTHONPATH
    # lands earlier on `sys.path` than a `.pth` entry, so the worktree wins. The
    # compiled `sase_core_rs` extension is still the installed one; that
    # limitation is stated in the report rather than papered over.
    environ["PYTHONPATH"] = os.pathsep.join(
        [str(worktree / "src"), str(worktree), environ.get("PYTHONPATH", "")]
    ).rstrip(os.pathsep)
    command = [
        sys.executable,
        "-m",
        "pytest",
        "-m",
        EXECUTE_MARKER_EXPRESSION,
        "-p",
        "no:randomly",
        "--no-header",
        "-q",
        *missed,
    ]
    try:
        result = subprocess.run(
            command,
            cwd=worktree,
            env=environ,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return ExecutedProbe(
            sha=sha,
            missed=tuple(missed),
            returncode=-1,
            summary=f"timed out after {timeout}s",
        )
    return ExecutedProbe(
        sha=sha,
        missed=tuple(missed),
        returncode=result.returncode,
        summary=_pytest_summary(result.stdout + result.stderr),
    )


def _pytest_summary(output: str) -> str:
    """The last line of pytest output that looks like a run summary."""
    for line in reversed(output.splitlines()):
        stripped = line.strip()
        if any(
            token in stripped for token in ("passed", "failed", "error", "no tests ran")
        ):
            return stripped.strip("= ")
    return "no pytest summary line"
