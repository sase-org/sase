"""What each test file costs, measured by the runs the lane already does.

Selection has always known *which* tests it picked and never what picking them
costs. That gap is why a 94-file selection — 4% of the suite, comfortably
"scoped" — can run 465s serially while a 517-file one runs 404s: file count is
a 6x-spread proxy for runtime, and the ratio guard that uses it rates the
slowest selections as the cheapest.

This module owns the cost model and nothing else: it measures, and
:mod:`tests._test_selection_rules` decides. Its one consumer is
``RULE_SERIAL_BUDGET_EXCEEDED``, which escalates a selection whose estimated
serial cost exceeds the governed full lane's wall clock; where this module
refuses to answer, the file-count ratio decides instead.

The shape of the model:

* **Recorded by runs that already happen.** ``tools/run_pytest`` arms
  :mod:`tests._test_selection_timings_plugin` on the full lanes, where one
  ``just test`` covers every test file in a single pass, and on scoped runs,
  which refresh the files the lane actually touches most. No new lane, no new
  CI job.
* **Per test *file*, not per test.** That is the granularity selection works
  at, and it is stable across the parametrization churn individual node IDs
  suffer.
* **Wall seconds summed across phases**, which makes the table additive: the
  estimate for a selection is the sum of its files, and that sum is what a
  serial (``-n 1``) run of those files would take. A parallel full lane
  contributes the same per-test seconds a serial one would, so recording from
  the 28-worker lane is sound even though its own wall clock is not.
* **Host-local, keyed by nothing but the host.** This is a cost model, not
  ground truth about a commit; it has no per-commit identity to carry. It
  lives beside the selection-health records, under the same per-project store,
  because a table recorded by a phase agent in ``sase_3`` is exactly as useful
  to a land agent in ``sase_7``.
* **Merged newest-wins across the kept recordings**, so a partial scoped
  recording refreshes the files it covered without discarding the full lane's
  coverage of the ones it did not.

An estimate over files the table does not know is *stated*, never guessed at
silently: :class:`TimingEstimate` carries the coverage fraction, and answers
``available=False`` outright when the table is missing or covers too little of
the selection to be worth believing.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


#: Bumped when the recording payload changes shape.
TIMINGS_SCHEMA = 1

TIMINGS_SUBDIRECTORY = "timings"
RECORDING_SUFFIX = ".json"

#: Overrides the timing-table directory outright; the tests use it.
TIMINGS_DIR_ENV = "SASE_TEST_SELECTION_TIMINGS_DIR"
#: Set to ``1`` to record nothing and estimate nothing.
TIMINGS_DISABLED_ENV = "SASE_TEST_SELECTION_TIMINGS_DISABLED"
#: Overrides the coverage fraction below which an estimate is refused.
MIN_COVERAGE_ENV = "SASE_TEST_SELECTION_TIMINGS_MIN_COVERAGE"

#: How many recordings to merge. Enough that a run of scoped recordings cannot
#: evict the one full-lane recording that covers the whole suite, and few
#: enough that the merge stays cheap. Pruned like the contexts cache.
KEEP_RECORDINGS = 8

#: Below this share of the selection covered by the table, the estimate is
#: refused rather than extrapolated. The unknown files are extrapolated at the
#: covered files' mean, which is a defensible correction for a handful of new
#: test files and a fiction for a mostly-unknown selection; 0.8 is where this
#: module stops pretending to know.
DEFAULT_MIN_COVERAGE = 0.8

#: Explicit no-data answers. Callers branch on these, so they are values rather
#: than prose.
REASON_DISABLED = "timings-disabled"
REASON_NO_TABLE = "no-timing-data"
REASON_INSUFFICIENT_COVERAGE = "insufficient-timing-coverage"
REASON_EMPTY_SELECTION = "empty-selection"
#: The selector's own answer for a run that escalated: there is no per-file
#: selection left to cost, and recording that as ``0.0`` would read as "free".
REASON_ESCALATED = "escalated"

_TIMESTAMP_FORMAT = "%Y%m%dT%H%M%SZ"
_RECORDING_NAME_PATTERN = re.compile(
    r"^(?P<timestamp>\d{8}T\d{6}Z)-(?P<pid>\d+)\.json$"
)


def timings_enabled(environ: Mapping[str, str] | None = None) -> bool:
    environ = os.environ if environ is None else environ
    return environ.get(TIMINGS_DISABLED_ENV) != "1"


def recording_host() -> str:
    return platform.node() or "unknown"


def timings_directory(store: Path, environ: Mapping[str, str] | None = None) -> Path:
    """The timing table's directory, inside the project's record store.

    Inside rather than beside: unlike the contexts cache, whose databases are
    keyed by a commit SHA that means the same thing everywhere, a duration
    table is a statement about *this project's* test files and would be
    meaningless merged across projects.
    """
    environ = os.environ if environ is None else environ
    override = environ.get(TIMINGS_DIR_ENV)
    if override:
        return Path(override).expanduser()
    return store / TIMINGS_SUBDIRECTORY


# --------------------------------------------------------------------------
# Recording
# --------------------------------------------------------------------------


def file_for_nodeid(nodeid: str) -> str | None:
    """The repository-relative test file a node ID names, if it names one.

    A collection error reports the file itself as the node ID, with no ``::``;
    that is still a file, and the seconds spent failing to collect it are real
    seconds a selection including it would pay.
    """
    head = nodeid.split("::", 1)[0].replace("\\", "/").strip()
    return head if head.endswith(".py") else None


def recording_filename(*, now: datetime, pid: int) -> str:
    stamp = now.astimezone(UTC).strftime(_TIMESTAMP_FORMAT)
    return f"{stamp}-{pid}{RECORDING_SUFFIX}"


def timings_record(
    durations: Mapping[str, float],
    *,
    mode: str,
    worker_count: int | None,
    host: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build a recording payload.

    ``worker_count`` is recorded even though it does not affect the numbers:
    per-test seconds are per-test seconds at any width, and a reader who later
    doubts that has to be able to check which runs were parallel.
    """
    stamp = now or datetime.now(UTC)
    return {
        "schema": TIMINGS_SCHEMA,
        "recorded_at": stamp.astimezone(UTC).isoformat(),
        "host": recording_host() if host is None else host,
        "mode": mode,
        "worker_count": worker_count,
        "file_count": len(durations),
        "durations": {
            path: round(float(seconds), 4)
            for path, seconds in sorted(durations.items())
        },
    }


def write_timings(
    directory: Path,
    durations: Mapping[str, float],
    *,
    mode: str,
    worker_count: int | None = None,
    host: str | None = None,
    pid: int | None = None,
    now: datetime | None = None,
    keep: int = KEEP_RECORDINGS,
) -> Path | None:
    """Persist one recording and prune the directory; ``None`` if there is nothing to say.

    A run that measured no test file at all writes nothing: an empty recording
    would occupy a retention slot while telling a later reader less than the
    file it evicted.
    """
    if not durations:
        return None
    stamp = now or datetime.now(UTC)
    path = directory / recording_filename(
        now=stamp, pid=os.getpid() if pid is None else pid
    )
    directory.mkdir(parents=True, exist_ok=True)
    payload = timings_record(
        durations, mode=mode, worker_count=worker_count, host=host, now=stamp
    )
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    prune_recordings(directory, keep)
    return path


def recording_paths(directory: Path) -> list[Path]:
    """Every recognised recording, oldest first.

    Only ``<timestamp>-<pid>.json`` names are recognised. This directory lives
    under the user's ``~/.sase``, where treating an unfamiliar file as a
    duration table — or deleting it — is a liability rather than a feature.
    """
    try:
        entries = list(directory.iterdir())
    except OSError:
        return []
    recordings = [
        entry
        for entry in entries
        if _RECORDING_NAME_PATTERN.match(entry.name) and entry.is_file()
    ]
    recordings.sort(key=lambda path: path.name)
    return recordings


def prune_recordings(directory: Path, keep: int = KEEP_RECORDINGS) -> list[Path]:
    """Keep only the ``keep`` newest recordings; the table is disposable."""
    removed: list[Path] = []
    recordings = recording_paths(directory)
    for path in recordings[: max(0, len(recordings) - keep)]:
        try:
            path.unlink()
        except OSError:
            continue
        removed.append(path)
    return removed


# --------------------------------------------------------------------------
# The merged table
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TimingTable:
    """Per-test-file wall seconds, merged across the kept recordings."""

    durations: Mapping[str, float] = field(default_factory=dict)
    #: Recording file names that fed the merge, oldest first.
    sources: tuple[str, ...] = ()
    #: Digest of the source names, sizes, and mtimes: the table's identity, in
    #: the sense the manifest needs — "was this the same table?" — without
    #: pretending the durations themselves are content-addressed.
    identity: str | None = None
    #: The newest recording's ``recorded_at``.
    recorded_at: str | None = None

    @property
    def empty(self) -> bool:
        return not self.durations

    @property
    def file_count(self) -> int:
        return len(self.durations)

    @property
    def total_seconds(self) -> float:
        return sum(self.durations.values())

    def payload(self) -> dict[str, Any]:
        """The identity block a manifest records alongside an estimate."""
        return {
            "identity": self.identity,
            "recorded_at": self.recorded_at,
            "file_count": self.file_count,
            "sources": list(self.sources),
        }


def _read_recording(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema") != TIMINGS_SCHEMA:
        return None
    return payload if isinstance(payload.get("durations"), dict) else None


def _table_identity(paths: Sequence[Path]) -> str | None:
    digest = hashlib.sha256()
    seen = False
    for path in paths:
        try:
            stat = path.stat()
        except OSError:
            continue
        digest.update(path.name.encode("utf-8"))
        digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode())
        seen = True
    return digest.hexdigest()[:16] if seen else None


def load_timing_table(directory: Path, *, host: str | None = None) -> TimingTable:
    """Merge the kept recordings into one table, newest recording winning.

    Recordings written by another host are skipped rather than merged: the
    store is host-local by design, but a ``SASE_HOME`` on shared storage would
    otherwise blend two machines' speeds into a number describing neither.
    """
    host = recording_host() if host is None else host
    merged: dict[str, float] = {}
    sources: list[str] = []
    used: list[Path] = []
    newest_recorded_at: str | None = None
    for path in recording_paths(directory):
        payload = _read_recording(path)
        if payload is None or str(payload.get("host") or host) != host:
            continue
        for raw_path, raw_seconds in payload["durations"].items():
            try:
                seconds = float(raw_seconds)
            except (TypeError, ValueError):
                continue
            if seconds >= 0:
                merged[str(raw_path)] = seconds
        sources.append(path.name)
        used.append(path)
        recorded_at = payload.get("recorded_at")
        if isinstance(recorded_at, str):
            newest_recorded_at = recorded_at
    return TimingTable(
        durations=merged,
        sources=tuple(sources),
        identity=_table_identity(used),
        recorded_at=newest_recorded_at,
    )


# --------------------------------------------------------------------------
# Estimating
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class TimingEstimate:
    """What a selection would cost serially, or why that cannot be said."""

    seconds: float | None = None
    #: Share of the selection's files the table knows a duration for.
    coverage: float = 0.0
    covered_count: int = 0
    missing_count: int = 0
    #: Set when ``seconds`` is ``None``; one of the ``REASON_*`` values.
    reason: str | None = REASON_NO_TABLE
    table: TimingTable = field(default_factory=TimingTable)
    min_coverage: float = DEFAULT_MIN_COVERAGE

    @property
    def available(self) -> bool:
        return self.seconds is not None

    def payload(self) -> dict[str, Any]:
        """The manifest's ``timings`` block."""
        return {
            "estimated_serial_seconds": (
                None if self.seconds is None else round(self.seconds, 2)
            ),
            "available": self.available,
            "reason": self.reason,
            "coverage": round(self.coverage, 4),
            "covered_count": self.covered_count,
            "missing_count": self.missing_count,
            "min_coverage": self.min_coverage,
            "table": self.table.payload(),
        }


def min_coverage(environ: Mapping[str, str] | None = None) -> float:
    environ = os.environ if environ is None else environ
    raw = environ.get(MIN_COVERAGE_ENV)
    if not raw or not raw.strip():
        return DEFAULT_MIN_COVERAGE
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_MIN_COVERAGE
    return value if 0 <= value <= 1 else DEFAULT_MIN_COVERAGE


def estimate_serial_seconds(
    paths: Iterable[str],
    *,
    table: TimingTable | None = None,
    directory: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> TimingEstimate:
    """Estimate a serial run of ``paths``, or say why it cannot be estimated.

    The answer is never a bare number. Files the table has never seen are
    extrapolated at the covered files' mean — the least-bad correction for the
    new test file an agent just wrote — but only while the covered share stays
    above :data:`DEFAULT_MIN_COVERAGE`. Below it the estimate is refused with
    :data:`REASON_INSUFFICIENT_COVERAGE`, because extrapolating most of a
    number from a fraction of a table is a guess wearing a float's clothes.

    Callers decide what an unavailable estimate means. Nothing in this
    repository treats one as zero, and nothing should: an unknown cost is
    unknown, not free.
    """
    environ = os.environ if environ is None else environ
    selection = sorted({str(path) for path in paths})
    floor = min_coverage(environ)
    if table is None:
        table = (
            TimingTable()
            if directory is None or not timings_enabled(environ)
            else load_timing_table(directory)
        )
    if not timings_enabled(environ):
        return TimingEstimate(reason=REASON_DISABLED, table=table, min_coverage=floor)
    if not selection:
        # An empty selection costs nothing, and that is a measured answer
        # rather than a missing one.
        return TimingEstimate(
            seconds=0.0,
            coverage=1.0,
            reason=REASON_EMPTY_SELECTION,
            table=table,
            min_coverage=floor,
        )
    if table.empty:
        return TimingEstimate(
            reason=REASON_NO_TABLE,
            missing_count=len(selection),
            table=table,
            min_coverage=floor,
        )

    known = [table.durations[path] for path in selection if path in table.durations]
    covered_count = len(known)
    missing_count = len(selection) - covered_count
    coverage = covered_count / len(selection)
    if coverage < floor:
        return TimingEstimate(
            coverage=coverage,
            covered_count=covered_count,
            missing_count=missing_count,
            reason=REASON_INSUFFICIENT_COVERAGE,
            table=table,
            min_coverage=floor,
        )
    mean = sum(known) / covered_count if covered_count else 0.0
    return TimingEstimate(
        seconds=sum(known) + mean * missing_count,
        coverage=coverage,
        covered_count=covered_count,
        missing_count=missing_count,
        reason=None,
        table=table,
        min_coverage=floor,
    )
