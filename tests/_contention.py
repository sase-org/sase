"""The per-node failure tally the contention soak harness reports.

`tools/run_pytest contention` runs the default (non-visual) lane repeatedly on a
pinned, heavily oversubscribed CPU set. One pass is not evidence about a flake
class whose base rate is under one node per run, so the harness runs the
selection R times and reports which node IDs failed, how often, and in which
repeats. That tally is what makes a fix falsifiable: a node that fails in 4 of 6
repeats before a change and 0 of 6 after it has been measured rather than
declared.

The runner is a script and the recorder is a pytest plugin, so the record format
and the tally live here, where both can import them and tests can exercise them
without launching pytest.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any


#: Names the file `tests._contention_plugin` writes one repeat's failures to.
FAILURES_ENV = "SASE_CONTENTION_FAILURES"
#: Bumped only if the on-disk shape changes; a mismatch is read as no record,
#: because a stale soak artifact is never worth failing a diagnostic run over.
FAILURES_SCHEMA = 2
FAILURE_RECORD_LIMIT = 500
FAILURE_DETAIL_LIMIT = 3_000

#: The per-repeat diagnostic progress directory the harness hands the
#: controller. `tests._contention_progress` writes it and
#: `tests._contention_sampler` reads it; neither may import the other's runtime
#: (the sampler must not pay for importing pytest), so the format lives here.
DIAGNOSTICS_ENV = "SASE_CONTENTION_DIAGNOSTICS"
DIAGNOSTICS_DIRNAME = "diagnostics"
PROGRESS_DIRNAME = "progress"
CONTROLLER_PROGRESS_FILENAME = "controller.json"
WORKER_PROGRESS_PREFIX = "worker-"
KILLS_FILENAME = "kills.jsonl"


#: The per-worker collection shards the harness hands the controller for a
#: whole-suite soak. Written by `tools/run_pytest contention`, read by
#: `tests._contention_shards`; the format lives here for the same reason the
#: progress format does.
SHARDS_ENV = "SASE_CONTENTION_SHARDS"
SHARD_MAP_FILENAME = "shards.json"
#: Bumped only if the on-disk shape changes. Unlike a failure record, a
#: mismatched shard map is an error: guessing would collect a file twice or
#: never.
SHARD_MAP_SCHEMA = 1


def progress_directory(diagnostics: Path, repeat: int) -> Path:
    """Where one repeat's controller and workers record their progress."""
    return diagnostics / PROGRESS_DIRNAME / f"repeat-{repeat:02d}"


def write_shard_map(path: Path, shards: Sequence[Sequence[str]]) -> None:
    """Record which repository-relative test files each worker collects."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": SHARD_MAP_SCHEMA,
        "shards": [sorted(files) for files in shards],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_shard_map(path: Path) -> tuple[tuple[str, ...], ...]:
    """The shards ``write_shard_map`` recorded; ``ValueError`` if unusable."""
    payload = read_json(path)
    if payload is None or payload.get("schema") != SHARD_MAP_SCHEMA:
        raise ValueError(f"no usable contention shard map at {path}")
    shards = payload.get("shards")
    if (
        not isinstance(shards, list)
        or not shards
        or not all(isinstance(files, list) for files in shards)
    ):
        raise ValueError(f"malformed contention shard map at {path}")
    return tuple(tuple(str(name) for name in files) for files in shards)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Replace ``path`` whole, so a concurrent reader never sees half a record."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def read_json(path: Path) -> dict[str, Any] | None:
    """A JSON object from ``path``, or ``None`` when absent or unreadable."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


@dataclass(frozen=True)
class NodeTally:
    """One node's soak result: how often it failed, and in which repeats."""

    nodeid: str
    failures: int
    #: One-based repeat indices, as the harness numbers them for the operator.
    repeats: tuple[int, ...]


@dataclass(frozen=True)
class FailureRecord:
    """One repeat's durable failure reports and whether pytest finished."""

    complete: bool
    reports: tuple[Mapping[str, Any], ...]
    reports_seen: int
    reports_written: int
    reports_omitted: int
    reports_unwritten: int
    exitstatus: int | None

    @property
    def nodeids(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {
                    str(report["nodeid"])
                    for report in self.reports
                    if report.get("nodeid")
                }
            )
        )


def _failure_line(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n"


def start_failure_record(path: Path) -> None:
    """Create a partial-record marker before pytest starts running tests."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        _failure_line({"schema": FAILURES_SCHEMA, "kind": "started"}),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def append_failure_report(
    path: Path,
    *,
    nodeid: str,
    phase: str,
    detail: str,
    detail_truncated: bool = False,
) -> None:
    """Append one bounded report as soon as the controller receives it."""
    payload = {
        "schema": FAILURES_SCHEMA,
        "kind": "report",
        "nodeid": nodeid,
        "phase": phase,
        "detail": detail[:FAILURE_DETAIL_LIMIT],
        "detail_truncated": detail_truncated or len(detail) > FAILURE_DETAIL_LIMIT,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_failure_line(payload))
        handle.flush()


def finish_failure_record(
    path: Path,
    *,
    exitstatus: int | None,
    reports_seen: int,
    reports_written: int,
    reports_omitted: int,
    reports_unwritten: int,
) -> None:
    """Mark the repeat complete only after pytest reaches session finish."""
    payload = {
        "schema": FAILURES_SCHEMA,
        "kind": "complete",
        "exitstatus": exitstatus,
        "reports_seen": reports_seen,
        "reports_written": reports_written,
        "reports_omitted": reports_omitted,
        "reports_unwritten": reports_unwritten,
    }
    with path.open("a", encoding="utf-8") as handle:
        handle.write(_failure_line(payload))
        handle.flush()


def write_failures(path: Path, failures: Iterable[str]) -> None:
    """Write a completed failure record for tests and synthetic harness results."""
    nodeids = sorted(set(failures))
    start_failure_record(path)
    written = min(len(nodeids), FAILURE_RECORD_LIMIT)
    for nodeid in nodeids[:written]:
        append_failure_report(path, nodeid=nodeid, phase="call", detail="")
    finish_failure_record(
        path,
        exitstatus=1 if nodeids else 0,
        reports_seen=len(nodeids),
        reports_written=written,
        reports_omitted=max(0, len(nodeids) - written),
        reports_unwritten=0,
    )


def read_failure_record(path: Path) -> FailureRecord | None:
    """Read complete or interrupted evidence; ignore a torn final JSON line."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    started = False
    last_kind: str | None = None
    reports: list[Mapping[str, Any]] = []
    completion: Mapping[str, Any] | None = None
    for line in lines:
        try:
            payload = json.loads(line)
        except ValueError:
            continue
        if not isinstance(payload, dict) or payload.get("schema") != FAILURES_SCHEMA:
            continue
        kind = payload.get("kind")
        if kind == "started" and not started:
            started = True
        elif kind == "report" and started:
            nodeid, phase = payload.get("nodeid"), payload.get("phase")
            if not isinstance(nodeid, str) or not isinstance(phase, str):
                continue
            if len(reports) < FAILURE_RECORD_LIMIT:
                detail = payload.get("detail", "")
                reports.append(
                    {
                        "nodeid": nodeid,
                        "phase": phase,
                        "detail": str(detail)[:FAILURE_DETAIL_LIMIT],
                        "detail_truncated": bool(payload.get("detail_truncated")),
                    }
                )
        elif kind == "complete" and started:
            completion = payload
        else:
            continue
        last_kind = str(kind)
    if not started:
        return None
    complete = last_kind == "complete" and completion is not None

    def count_field(name: str, default: int) -> int:
        if not complete or completion is None:
            return default
        try:
            return max(0, int(completion.get(name, default)))
        except (TypeError, ValueError):
            return default

    reports_seen = (
        count_field("reports_seen", len(reports)) if complete else len(reports)
    )
    reports_written = (
        count_field("reports_written", len(reports)) if complete else len(reports)
    )
    reports_omitted = (
        count_field("reports_omitted", max(0, reports_seen - len(reports)))
        if complete
        else max(0, reports_seen - len(reports))
    )
    reports_unwritten = count_field("reports_unwritten", 0) if complete else 0
    raw_exitstatus = completion.get("exitstatus") if complete else None
    try:
        exitstatus = None if raw_exitstatus is None else int(raw_exitstatus)
    except (TypeError, ValueError):
        exitstatus = None
    return FailureRecord(
        complete=complete,
        reports=tuple(reports),
        reports_seen=reports_seen,
        reports_written=reports_written,
        reports_omitted=reports_omitted,
        reports_unwritten=reports_unwritten,
        exitstatus=exitstatus,
    )


def read_failures(path: Path) -> tuple[str, ...]:
    """The node IDs a repeat recorded, or none if it recorded nothing usable.

    A repeat that crashed hard enough to leave no record still counts as a red
    repeat -- the harness tracks that from the exit status -- but it contributes
    no nodes, which is the honest answer rather than a fabricated one.
    """
    record = read_failure_record(path)
    return () if record is None or not record.complete else record.nodeids


def tally_failures(
    repeats: Sequence[Sequence[str]], *, repeat_indices: Sequence[int] | None = None
) -> tuple[NodeTally, ...]:
    """Fold per-repeat failure sets into one tally, worst node first.

    Ordered by failure count descending and then by node ID, so the frequent
    nodes -- the ones worth attributing a mechanism to -- head the report and
    the order is stable across runs.
    """
    indices = tuple(repeat_indices or range(1, len(repeats) + 1))
    if len(indices) != len(repeats):
        raise ValueError("repeat_indices must match the number of completed repeats")
    occurrences: dict[str, list[int]] = {}
    for index, failures in zip(indices, repeats, strict=True):
        for nodeid in dict.fromkeys(failures):
            occurrences.setdefault(nodeid, []).append(index)
    return tuple(
        sorted(
            (
                NodeTally(nodeid=nodeid, failures=len(indices), repeats=tuple(indices))
                for nodeid, indices in occurrences.items()
            ),
            key=lambda tally: (-tally.failures, tally.nodeid),
        )
    )


def format_tally(
    tallies: Sequence[NodeTally],
    *,
    repeat_count: int,
    red_repeats: Sequence[int],
    duration: float | None = None,
    completed_repeat_count: int | None = None,
) -> str:
    """Render the end-of-soak report, including when nothing failed.

    "0 nodes failed across 6 repeats" is the result a remediation phase quotes
    as its after-measurement, so the empty case is a reported outcome rather
    than silence.
    """
    elapsed = "" if duration is None else f" in {duration:.1f}s"
    red = ",".join(str(index) for index in red_repeats) or "none"
    completed = (
        repeat_count if completed_repeat_count is None else completed_repeat_count
    )
    if completed == repeat_count:
        headline = (
            f"contention tally: {len(tallies)} node(s) failed across "
            f"{repeat_count} repeat(s){elapsed}; red repeats: {red}"
        )
    else:
        headline = (
            f"contention tally: {len(tallies)} node(s) failed across "
            f"{completed} completed repeat(s) of {repeat_count} requested"
            f"{elapsed}; red repeats: {red}"
        )
    lines = [headline]
    if not tallies:
        lines.append("  no node failed in any repeat")
        return "\n".join(lines)
    width = len(str(max(tally.failures for tally in tallies)))
    for tally in tallies:
        repeats = ",".join(str(index) for index in tally.repeats)
        lines.append(
            f"  {tally.failures:>{width}}/{repeat_count}  {tally.nodeid}  "
            f"(repeats {repeats})"
        )
    return "\n".join(lines)
