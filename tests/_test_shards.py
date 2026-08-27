"""Deterministic whole-suite pytest sharding for the per-SHA master gate.

Diff-scoped selection (:mod:`tests._test_selection`) answers "which tests does
this change plausibly touch"; this module answers a different question for a
different lane: "how do we split the *entire* fast suite into N balanced
pieces that together cover every test file exactly once." The master gate
runs the whole suite on every push, never a heuristic subset, so coverage is
the one property that cannot bend: an unbalanced shard only costs wall clock,
but a dropped file costs correctness.

The shape of the model:

* **Discovery is a filesystem walk, not a git listing.** The master gate
  shards a checked-out commit, not a working tree with local edits, so every
  ``tests/**/test_*.py`` file that exists on disk is in scope regardless of
  tracked status. See :func:`discover_test_files`.
* **Cost estimates come from a table committed to the repository**
  (``tests/shard_timings.json``), not the host-local store
  :mod:`tests._test_selection_timings` reads. A CI runner starts with no
  local history, so the balance the shards need has to travel with the
  source tree. ``tools/refresh_shard_timings`` is what keeps that table
  current; see its docstring for how it is derived.
* **An unknown file still runs.** A file the table has never seen is
  estimated at the table's ``default_duration`` rather than excluded or
  guessed at zero — see :meth:`ShardTimingTable.estimate`. Table staleness
  can only skew *balance*; it can never drop a file from every shard's
  coverage, because assignment starts from a fresh filesystem discovery on
  every run, not from the table's own file list.
* **Assignment is longest-processing-time-first (LPT).** Files are sorted
  once by descending cost estimate, with ties broken by a SHA-256 digest of
  the path so the order is fully deterministic regardless of input order or
  platform, then dropped one at a time into whichever shard bin is lightest
  so far. Equally light bins prefer the lower index. LPT is not optimal
  bin-packing, but it keeps every bin within a small constant factor of the
  ideal split without needing to solve packing exactly, and — unlike a hash
  or round-robin split — it does not need the table to be complete or even
  present to produce a reasonable balance.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path


#: The environment variable a caller sets to select one shard, formatted
#: ``<1-based index>/<1-based count>`` (e.g. ``3/6``).
SHARD_ENV = "SASE_TEST_SHARD"

_TESTS_DIRNAME = "tests"
_TEST_FILE_GLOB = "test_*.py"

#: Bumped when the committed timing-table payload shape changes.
SHARD_TIMINGS_SCHEMA = 1

#: Where the committed timing table lives, repository-relative.
DEFAULT_TIMINGS_PATH = Path("tests") / "shard_timings.json"

#: The estimate for a file when no committed table exists at all — every file
#: costs the same, so LPT still splits them as evenly as file count allows.
FALLBACK_DURATION = 1.0


class ShardError(RuntimeError):
    """Raised when a shard spec, discovery, or assignment cannot be trusted."""


@dataclass(frozen=True)
class ShardSpec:
    """A 1-based ``index`` of ``count`` total shards. Never index 0."""

    index: int
    count: int


def parse_shard_spec(value: str) -> ShardSpec:
    """Strictly parse ``SASE_TEST_SHARD``'s ``<index>/<count>`` syntax.

    Both sides are 1-based positive integers with ``1 <= index <= count``.
    Anything else — a missing slash, non-digit characters, a zero, an index
    past the count — is a :class:`ShardError` naming exactly what is wrong,
    since a silently clamped bad spec would quietly run the wrong slice of
    the suite instead of failing the gate that asked for it.
    """
    parts = value.split("/")
    if len(parts) != 2:
        raise ShardError(
            f"{SHARD_ENV} must look like '<index>/<count>' (e.g. '1/6'); got {value!r}"
        )
    raw_index, raw_count = parts
    if not raw_index.isdigit() or not raw_count.isdigit():
        raise ShardError(
            f"{SHARD_ENV} index and count must be positive integers; got {value!r}"
        )
    index, count = int(raw_index), int(raw_count)
    if count < 1:
        raise ShardError(f"{SHARD_ENV} count must be at least 1; got {value!r}")
    if not 1 <= index <= count:
        raise ShardError(
            f"{SHARD_ENV} index must be between 1 and {count}; got {value!r}"
        )
    return ShardSpec(index=index, count=count)


def discover_test_files(repo_root: Path) -> list[str]:
    """Every ``tests/**/test_*.py`` file, repo-relative POSIX, sorted.

    A plain recursive walk, not :func:`tests._test_selection_graph.run_git`:
    the master gate shards whatever a checkout contains, including a file an
    agent just added and has not yet committed, and must not depend on git
    state at all. Pinned to pytest's own configuration —
    ``testpaths = ["tests"]`` and the default ``python_files`` pattern in
    ``pyproject.toml`` — by ``tests/test_test_shards.py``, which asserts this
    walk agrees with what pytest itself collects.
    """
    tests_dir = repo_root / _TESTS_DIRNAME
    discovered: list[str] = []
    for path in tests_dir.rglob(_TEST_FILE_GLOB):
        if not path.is_file():
            continue
        relative = path.relative_to(repo_root)
        if any(part.startswith(".") for part in relative.parts):
            continue
        if "__pycache__" in relative.parts:
            continue
        discovered.append(relative.as_posix())
    return sorted(discovered)


@dataclass(frozen=True)
class ShardTimingTable:
    """Per-test-file duration estimates loaded from the committed table."""

    default_duration: float = FALLBACK_DURATION
    durations: Mapping[str, float] = field(default_factory=dict)

    @property
    def empty(self) -> bool:
        return not self.durations

    def estimate(self, path: str) -> float:
        """This file's recorded duration, the table default, then 1.0."""
        return self.durations.get(path, self.default_duration)


def load_shard_timings(path: Path) -> ShardTimingTable:
    """Load the committed timing table, degrading to an empty one if unusable.

    A missing, unreadable, or malformed table is never fatal — every
    unrecognised file still costs ``FALLBACK_DURATION`` and is still
    assigned, just less evenly. Coverage never depends on this file existing;
    only balance does.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ShardTimingTable()
    if not isinstance(payload, dict) or payload.get("schema") != SHARD_TIMINGS_SCHEMA:
        return ShardTimingTable()

    raw_durations = payload.get("durations")
    durations: dict[str, float] = {}
    if isinstance(raw_durations, dict):
        for file_path, seconds in raw_durations.items():
            try:
                durations[str(file_path)] = float(seconds)
            except (TypeError, ValueError):
                continue

    try:
        default_duration = float(payload.get("default_duration", FALLBACK_DURATION))
    except (TypeError, ValueError):
        default_duration = FALLBACK_DURATION

    return ShardTimingTable(default_duration=default_duration, durations=durations)


def _tiebreak(path: str) -> str:
    """A stable, platform-independent tiebreak for two equal cost estimates."""
    return hashlib.sha256(path.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ShardBin:
    """One shard's assigned files and their summed cost estimate."""

    files: tuple[str, ...]
    estimated_seconds: float


def assign_shards(
    files: Sequence[str], count: int, table: ShardTimingTable
) -> list[ShardBin]:
    """Partition ``files`` into ``count`` disjoint, exhaustive bins via LPT.

    Every file is assigned to exactly one bin: the loop consumes each file
    from ``files`` once, in descending-cost order, so the bins' combined file
    count and set always equal the input exactly. Refuses to produce more
    bins than there are files to put in them, since an empty shard would run
    nothing while still claiming a CI job slot.
    """
    if count < 1:
        raise ShardError(f"shard count must be at least 1; got {count}")
    if count > len(files):
        raise ShardError(
            f"cannot split {len(files)} test file(s) into {count} shard(s): "
            "more shards than files"
        )

    ordered = sorted(files, key=lambda path: (-table.estimate(path), _tiebreak(path)))
    bin_files: list[list[str]] = [[] for _ in range(count)]
    bin_totals = [0.0] * count
    for path in ordered:
        target = min(range(count), key=lambda index: (bin_totals[index], index))
        bin_files[target].append(path)
        bin_totals[target] += table.estimate(path)

    return [
        ShardBin(
            files=tuple(sorted(bin_files[index])), estimated_seconds=bin_totals[index]
        )
        for index in range(count)
    ]


def shard_files(
    files: Sequence[str], spec: ShardSpec, table: ShardTimingTable
) -> ShardBin:
    """The one bin ``spec`` names, from the full deterministic assignment."""
    bins = assign_shards(files, spec.count, table)
    return bins[spec.index - 1]


def format_shard_summary(
    spec: ShardSpec, selected: ShardBin, *, total_files: int
) -> str:
    """One concise line describing what this shard picked up."""
    share = 0.0 if total_files == 0 else 100 * len(selected.files) / total_files
    return (
        f"shard {spec.index}/{spec.count}: {len(selected.files)} of {total_files} "
        f"test file(s) ({share:.1f}%), ~{selected.estimated_seconds:.0f}s estimated"
    )
