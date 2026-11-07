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
FAILURES_SCHEMA = 1

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


def progress_directory(diagnostics: Path, repeat: int) -> Path:
    """Where one repeat's controller and workers record their progress."""
    return diagnostics / PROGRESS_DIRNAME / f"repeat-{repeat:02d}"


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


def write_failures(path: Path, failures: Iterable[str]) -> None:
    """Record one repeat's failing node IDs where the harness will read them."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"schema": FAILURES_SCHEMA, "failures": sorted(set(failures))}
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def read_failures(path: Path) -> tuple[str, ...]:
    """The node IDs a repeat recorded, or none if it recorded nothing usable.

    A repeat that crashed hard enough to leave no record still counts as a red
    repeat -- the harness tracks that from the exit status -- but it contributes
    no nodes, which is the honest answer rather than a fabricated one.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return ()
    try:
        payload = json.loads(raw)
    except ValueError:
        return ()
    if not isinstance(payload, dict) or payload.get("schema") != FAILURES_SCHEMA:
        return ()
    failures = payload.get("failures")
    if not isinstance(failures, list):
        return ()
    return tuple(sorted({str(nodeid) for nodeid in failures}))


def tally_failures(repeats: Sequence[Sequence[str]]) -> tuple[NodeTally, ...]:
    """Fold per-repeat failure sets into one tally, worst node first.

    Ordered by failure count descending and then by node ID, so the frequent
    nodes -- the ones worth attributing a mechanism to -- head the report and
    the order is stable across runs.
    """
    occurrences: dict[str, list[int]] = {}
    for index, failures in enumerate(repeats, start=1):
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
) -> str:
    """Render the end-of-soak report, including when nothing failed.

    "0 nodes failed across 6 repeats" is the result a remediation phase quotes
    as its after-measurement, so the empty case is a reported outcome rather
    than silence.
    """
    elapsed = "" if duration is None else f" in {duration:.1f}s"
    red = ",".join(str(index) for index in red_repeats) or "none"
    lines = [
        f"contention tally: {len(tallies)} node(s) failed across "
        f"{repeat_count} repeat(s){elapsed}; red repeats: {red}",
    ]
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
