"""Per-test coverage contexts as a second, sound-ish selection source.

The static closure in :mod:`tests._test_selection` is a heuristic: it can only
see ``import`` statements, so dynamic dispatch, plugin lookup, and config
discovery are invisible to it. Per-test coverage *is* ground truth for the
question "which tests executed this line" — for the code that existed when the
baseline was recorded.

That caveat is the whole design:

* **Union, never replace.** Contexts say nothing about code added since the
  baseline, and a brand-new test file has no context rows at all. The static
  closure stays in the selection unconditionally.
* **A missing baseline is not an error.** An agent in a fresh workspace with no
  network must still get a working ``just check``; it records
  ``context-baseline-missing`` and proceeds on the static closure alone.
* **A stale baseline is used anyway, and said so.** Recording
  ``context-baseline-stale`` on the manifest is what lets ``just
  selection-health`` show whether staleness correlates with false negatives —
  which is a question only real use can answer.

Baselines are the ``.coverage`` SQLite database the CI coverage leg publishes
as the ``sase-coverage-contexts-<sha>`` artifact, cached by SHA under
``${SASE_HOME:-~/.sase}/test-selection/contexts/``. Obtaining one is an explicit
act, from either of two producers — ``just refresh-contexts-baseline`` fetches
CI's artifact, and ``just test-contexts`` files its own instrumented run under
``HEAD`` via ``tools/install_coverage_contexts`` — so a host that never fetched,
or whose 14-day artifact expired, is not left on the static closure alone.
Selection itself never touches the network.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from tests._test_selection_graph import SelectionError, is_visual_path, run_git


CONTEXTS_SUBDIRECTORY = "contexts"
BASELINE_SUFFIX = ".sqlite"
ARTIFACT_PREFIX = "sase-coverage-contexts"

#: Overrides the baseline cache directory outright; the tests use it.
CONTEXTS_DIR_ENV = "SASE_TEST_SELECTION_CONTEXTS_DIR"
#: Set to ``1`` to ignore any cached baseline entirely.
CONTEXTS_DISABLED_ENV = "SASE_TEST_SELECTION_CONTEXTS_DISABLED"
#: How many commits behind ``HEAD`` a baseline may be before it counts as stale.
CONTEXTS_MAX_DISTANCE_ENV = "SASE_TEST_SELECTION_CONTEXTS_MAX_DISTANCE"
DEFAULT_MAX_DISTANCE = 50

RULE_CONTEXT_BASELINE_MISSING = "context-baseline-missing"
RULE_CONTEXT_BASELINE_STALE = "context-baseline-stale"
RULE_CONTEXT_SELECTION = "context-selection"

#: Coverage records a context as ``<nodeid>|<phase>``; the phase is one of
#: ``setup``, ``run``, ``teardown``, and the empty context is import-time
#: execution that belongs to no test at all.
_CONTEXT_PHASE_PATTERN = re.compile(r"\|(?:setup|run|teardown)$")
_HUNK_PATTERN = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+")
_SHA_PATTERN = re.compile(r"^[0-9a-f]{7,40}$")


@dataclass(frozen=True)
class ContextBaseline:
    """A cached per-test coverage database and the commit it was recorded at."""

    path: Path
    sha: str


@dataclass(frozen=True)
class ContextSelection:
    """What the contexts baseline contributed, and how much to trust it."""

    selected: tuple[str, ...] = ()
    rules: tuple[str, ...] = ()
    baseline_sha: str | None = None
    stale: bool = False
    distance: int | None = None
    matched_files: tuple[str, ...] = ()
    #: Whether the baseline cache was looked at during this selection at all.
    #:
    #: A run a rule forces to the full suite never reaches
    #: :func:`select_from_contexts`: its selection is already the whole suite,
    #: so ground truth has nothing left to add. Recording that as a *missing*
    #: baseline charges the run with an exposure it never ran — the difference
    #: between "the static closure was the only source" and "the static closure
    #: was not the source either". Every reader that reports baseline
    #: availability has to tell those apart, so the selector states it rather
    #: than leaving each one to re-derive it from ``escalated``.
    consulted: bool = True

    @property
    def usable(self) -> bool:
        """Whether ground truth actually backed this selection.

        A missing baseline contributed nothing at all, and a stale one was
        recorded too far back for its rows to describe today's code. Either way
        the static closure is the only real source, which is the condition
        ``no-baseline-depth-boost`` compensates for. A *fresh* baseline counts as
        usable even when it matched no changed file: it looked and found
        nothing, which is an answer rather than an absence.
        """
        return self.baseline_sha is not None and not self.stale

    def payload(self) -> dict[str, Any]:
        """The manifest's ``contexts`` block."""
        return {
            "baseline": self.baseline_sha,
            "consulted": self.consulted,
            "stale": self.stale,
            "distance": self.distance,
            "selected_count": len(self.selected),
            "matched_files": list(self.matched_files),
        }


def contexts_consulted(payload: Mapping[str, Any], *, escalated: bool) -> bool:
    """Whether a manifest's ``contexts`` block records a real lookup.

    Manifests written before schema 4 carry no ``consulted`` flag, so the
    answer has to be inferred for them: an escalated run that also recorded no
    baseline is the forced-full-suite shape, since a ratio escalation happens
    only *after* contexts are consulted and keeps whatever baseline it found.
    Reading it wrong in that direction is safe — such a run executed the whole
    suite either way — while reading a forced escalation as a missing baseline
    is what inflates the exposure count this function exists to keep honest.
    """
    recorded = payload.get("consulted")
    if recorded is not None:
        return bool(recorded)
    return not (escalated and payload.get("baseline") is None)


# --------------------------------------------------------------------------
# Baseline cache
# --------------------------------------------------------------------------


def contexts_directory(store: Path) -> Path:
    """The per-SHA baseline cache, beside the selection-health record store."""
    override = os.environ.get(CONTEXTS_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return store.parent / CONTEXTS_SUBDIRECTORY


def baseline_path(directory: Path, sha: str) -> Path:
    return directory / f"{sha}{BASELINE_SUFFIX}"


def cached_baselines(directory: Path) -> list[ContextBaseline]:
    """Every cached baseline, newest file first.

    Only names that look like ``<sha>.sqlite`` are recognised: this directory
    lives under the user's ``~/.sase``, and treating an unfamiliar file there as
    a coverage database is how you get a confusing traceback instead of a
    clean fallback.
    """
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    baselines = [
        ContextBaseline(path=entry, sha=entry.name[: -len(BASELINE_SUFFIX)])
        for entry in entries
        if entry.name.endswith(BASELINE_SUFFIX)
        and _SHA_PATTERN.match(entry.name[: -len(BASELINE_SUFFIX)])
        and entry.is_file()
    ]
    baselines.sort(key=lambda baseline: _mtime(baseline.path), reverse=True)
    return baselines


def _mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def prune_baselines(directory: Path, keep: int) -> list[Path]:
    """Keep only the ``keep`` newest baselines; the cache is disposable.

    Both producers — the CI fetch and a local ``cov-contexts`` run — call this,
    so one bound holds however a baseline arrived. Each database is tens of
    megabytes, and only the newest ancestor is ever read.
    """
    removed: list[Path] = []
    for baseline in cached_baselines(directory)[keep:]:
        try:
            baseline.path.unlink()
        except OSError:
            continue
        removed.append(baseline.path)
    return removed


def resolve_baseline(root: Path, directory: Path) -> ContextBaseline | None:
    """Pick the cached baseline closest to ``HEAD``.

    "Closest" means the most recent ancestor of ``HEAD``; a baseline recorded on
    a branch this workspace never merged is still usable — contexts only ever
    *add* tests — so an unrelated baseline is accepted as a last resort rather
    than discarded.
    """
    baselines = cached_baselines(directory)
    if not baselines:
        return None
    ancestors = [
        baseline
        for baseline in baselines
        if _is_ancestor_of_head(root, baseline.sha) is True
    ]
    return ancestors[0] if ancestors else baselines[0]


def _is_ancestor_of_head(root: Path, sha: str) -> bool | None:
    """``True``/``False`` for a known commit, ``None`` when git cannot say."""
    try:
        run_git(root, "cat-file", "-e", f"{sha}^{{commit}}")
    except SelectionError:
        return None
    try:
        run_git(root, "merge-base", "--is-ancestor", sha, "HEAD")
    except SelectionError:
        return False
    return True


def baseline_distance(root: Path, sha: str) -> int | None:
    """Commits between ``sha`` and ``HEAD``, or ``None`` when unknowable."""
    try:
        raw = run_git(root, "rev-list", "--count", f"{sha}..HEAD")
    except SelectionError:
        return None
    try:
        return int(raw.strip())
    except ValueError:
        return None


def max_distance(environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    raw = environ.get(CONTEXTS_MAX_DISTANCE_ENV)
    if not raw or not raw.strip():
        return DEFAULT_MAX_DISTANCE
    try:
        value = int(raw)
    except ValueError as error:
        raise SelectionError(
            f"{CONTEXTS_MAX_DISTANCE_ENV} must be a non-negative integer"
        ) from error
    if value < 0:
        raise SelectionError(
            f"{CONTEXTS_MAX_DISTANCE_ENV} must be a non-negative integer"
        )
    return value


# --------------------------------------------------------------------------
# Changed lines
# --------------------------------------------------------------------------


def parse_baseline_lines(diff: str) -> dict[str, set[int]]:
    """Map each file in a ``git diff -U0`` to the lines it touches *on the old side*.

    Old-side numbering is what matters here and it is easy to get wrong. The
    contexts database is keyed by line numbers as they were **in the baseline**,
    so querying it with the working tree's line numbers silently reads the wrong
    rows the moment an earlier hunk changes a file's length.

    A pure insertion has a zero-length old side. Both neighbours of the
    insertion point are recorded, because the tests that ran the surrounding
    code are the best available proxy for code that did not exist yet. A file
    that did not exist in the baseline has no old side at all and contributes
    nothing, which is correct: it has no context rows either.
    """
    changed: dict[str, set[int]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("--- a/"):
            current = line[len("--- a/") :]
            changed.setdefault(current, set())
            continue
        if line.startswith("--- /dev/null"):
            current = None
            continue
        if current is None or not line.startswith("@@"):
            continue
        match = _HUNK_PATTERN.match(line)
        if match is None:
            continue
        start = int(match.group(1))
        count = int(match.group(2)) if match.group(2) is not None else 1
        if count == 0:
            changed[current].update({start, start + 1})
            continue
        changed[current].update(range(start, start + count))
    return changed


def baseline_changed_lines(
    root: Path, baseline_sha: str, paths: Sequence[str]
) -> dict[str, set[int]]:
    """Which baseline lines this working tree has since touched, per file.

    The diff is taken against the *baseline commit* rather than the merge base,
    so the line numbers line up with the database. It is restricted to the
    change set's own files: between the baseline and the merge base other people
    changed other files, and inheriting their tests would inflate every
    selection made against a slightly old baseline.
    """
    if not paths:
        return {}
    try:
        diff = run_git(root, "diff", "-U0", baseline_sha, "--", *paths)
    except SelectionError:
        return {}
    return parse_baseline_lines(diff)


# --------------------------------------------------------------------------
# Reading the baseline
# --------------------------------------------------------------------------


def context_test_file(context: str) -> str | None:
    """The test file a coverage context names, if it names one.

    The empty context is import-time execution attributable to no test; a
    context without a ``::`` is not a pytest node ID and is ignored rather than
    guessed at.
    """
    stripped = _CONTEXT_PHASE_PATTERN.sub("", context).strip()
    if not stripped or "::" not in stripped:
        return None
    return stripped.split("::", 1)[0].replace("\\", "/")


def normalize_measured_file(measured: str) -> str | None:
    """Map a database path back onto a repository-relative ``src/`` path.

    Coverage records whatever path the run saw. The CI leg sets
    ``relative_files``, so a fresh artifact is already repo-relative, but a
    database recorded before that setting — or by a local run — holds absolute
    checkout paths. Both reduce to the same thing here.
    """
    posix = measured.replace("\\", "/")
    marker = "/src/"
    index = posix.rfind(marker)
    if index != -1:
        return posix[index + 1 :]
    return posix if posix.startswith("src/") else None


def find_tests_touching(
    database: Path, targets: Mapping[str, set[int]]
) -> tuple[set[str], set[str]]:
    """Return the test files that executed a changed line, and which files matched.

    An unreadable or schema-incompatible database is not an error: contexts are
    an optional accelerant, and the caller falls back to the static closure.
    """
    try:
        from coverage import CoverageData
    except ImportError:
        return set(), set()

    data = CoverageData(basename=str(database))
    try:
        data.read()
        measured = list(data.measured_files())
    except Exception:
        return set(), set()

    by_path: dict[str, list[str]] = {}
    for entry in measured:
        normalized = normalize_measured_file(entry)
        if normalized is not None and normalized in targets:
            by_path.setdefault(normalized, []).append(entry)

    selected: set[str] = set()
    matched: set[str] = set()
    for path, entries in by_path.items():
        wanted = targets[path]
        for entry in entries:
            try:
                contexts_by_line = data.contexts_by_lineno(entry)
            except Exception:
                continue
            for lineno, contexts in contexts_by_line.items():
                if lineno not in wanted:
                    continue
                for context in contexts:
                    test_file = context_test_file(context)
                    if test_file is not None:
                        selected.add(test_file)
                        matched.add(path)
    return selected, matched


# --------------------------------------------------------------------------
# Selection
# --------------------------------------------------------------------------


def select_from_contexts(
    root: Path,
    *,
    store: Path,
    changed_paths: Sequence[str],
    known_test_files: frozenset[str],
    environ: Mapping[str, str] | None = None,
) -> ContextSelection:
    """Select tests from a cached per-test coverage baseline.

    Everything about this function fails toward "contribute nothing": a missing
    baseline, an unreadable database, a change set with no ``src/`` Python in it
    at all. It never subtracts from the static closure and never raises for a
    baseline problem.
    """
    environ = os.environ if environ is None else environ
    if environ.get(CONTEXTS_DISABLED_ENV) == "1":
        return ContextSelection()

    directory = contexts_directory(store)
    baseline = resolve_baseline(root, directory)
    if baseline is None:
        return ContextSelection(rules=(RULE_CONTEXT_BASELINE_MISSING,))

    candidate_paths = [
        path
        for path in changed_paths
        if path.startswith("src/") and path.endswith(".py")
    ]
    targets = {
        path: lines
        for path, lines in baseline_changed_lines(
            root, baseline.sha, candidate_paths
        ).items()
        if lines
    }
    distance = baseline_distance(root, baseline.sha)
    stale = distance is None or distance > max_distance(environ)

    rules: list[str] = []
    if stale:
        rules.append(RULE_CONTEXT_BASELINE_STALE)
    if not targets:
        return ContextSelection(
            rules=tuple(rules),
            baseline_sha=baseline.sha,
            stale=stale,
            distance=distance,
        )

    candidates, matched = find_tests_touching(baseline.path, targets)
    selected = {
        path
        for path in candidates
        if path in known_test_files and not is_visual_path(path)
    }
    if selected:
        rules.append(RULE_CONTEXT_SELECTION)
    return ContextSelection(
        selected=tuple(sorted(selected)),
        rules=tuple(rules),
        baseline_sha=baseline.sha,
        stale=stale,
        distance=distance,
        matched_files=tuple(sorted(matched)),
    )
