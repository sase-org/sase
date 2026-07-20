"""Per-chop run history (metadata + logs) under each lumberjack.

Internal helper module — public API is re-exported through
``sase.axe.state``. Do not import from this module directly.

Paths and shared helpers are looked up through ``sase.axe.state`` at call
time so home-directory redirection applies to every reader.
"""

import sase.axe.state as _state  # noqa: I001
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from sase.axe._state_lumberjack import lumberjack_state_dir
from sase.core.state_write_guard import best_effort_test_state_write_allowed
from sase.core.time import get_timezone

#: Maximum number of run-history entries retained per chop. Older runs are
#: pruned (both metadata and log) when a new run is recorded.
MAX_CHOP_RUN_HISTORY = 10

ChopRunStatus = Literal[
    "running",
    "success",
    "failure",
    "timeout",
    "missing_script",
    "skipped",
    "no_op",
    "check_error",
    "launched",
    "action_succeeded",
    "action_failed",
]

ACTIVE_CHOP_RUN_STATUSES: frozenset[ChopRunStatus] = frozenset({"running", "launched"})

#: Allowed values for ``ChopRunEntry.source`` — how the run was kicked off.
ChopRunSource = Literal["scheduled", "manual", "oneshot"]


@dataclass
class ChopRunEntry:
    """Metadata for a single recorded chop run attempt.

    ``finished_at`` is ``None`` while the script or launched action is active;
    once the run terminates the same entry is updated with terminal status,
    ``finished_at``, and computed ``duration_ms``.
    """

    run_id: str
    lumberjack_name: str
    chop_name: str
    started_at: str
    finished_at: str | None
    duration_ms: int
    status: ChopRunStatus
    exit_code: int | None = None
    agent_pid: int | None = None
    pid: int | None = None
    error: str | None = None
    traceback: str | None = None
    output_bytes: int = 0
    output_log: str = ""
    source: ChopRunSource = "scheduled"
    started_by: str | None = None
    result_file: str = ""
    result: dict[str, Any] | None = None
    proposals: list[dict[str, Any]] = field(default_factory=list)
    launches: list[dict[str, Any]] = field(default_factory=list)
    dry_run: bool = False
    reason: str | None = None


def _chop_dir(lumberjack_name: str, chop_name: str) -> Path:
    """Return the state directory for a single chop under a lumberjack."""
    return lumberjack_state_dir(lumberjack_name) / "chops" / chop_name


def chop_runs_dir(lumberjack_name: str, chop_name: str) -> Path:
    """Return the directory holding per-run metadata/log files for a chop."""
    return _chop_dir(lumberjack_name, chop_name) / "runs"


def chop_index_path(lumberjack_name: str, chop_name: str) -> Path:
    """Return the index.json path that records ordered run ids for a chop."""
    return _chop_dir(lumberjack_name, chop_name) / "index.json"


def chop_run_meta_path(lumberjack_name: str, chop_name: str, run_id: str) -> Path:
    """Return the metadata JSON path for a recorded chop run."""
    return chop_runs_dir(lumberjack_name, chop_name) / f"{run_id}.json"


def chop_run_log_path(lumberjack_name: str, chop_name: str, run_id: str) -> Path:
    """Return the output log path for a recorded chop run."""
    return chop_runs_dir(lumberjack_name, chop_name) / f"{run_id}.log"


def chop_run_result_path(lumberjack_name: str, chop_name: str, run_id: str) -> Path:
    """Return the structured result path offered to one chop invocation."""
    return chop_runs_dir(lumberjack_name, chop_name) / f"{run_id}.result.json"


def chop_run_context_path(lumberjack_name: str, chop_name: str, run_id: str) -> Path:
    """Return the run-local context path containing ``result_file``."""
    return chop_runs_dir(lumberjack_name, chop_name) / f"{run_id}.context.json"


def ensure_chop_dirs(lumberjack_name: str, chop_name: str) -> Path:
    """Lazily create the run-history directory tree for a single chop.

    Returns:
        Path to ``~/.sase/axe/lumberjacks/{lumberjack}/chops/{chop}/``.
    """
    chop_dir = _chop_dir(lumberjack_name, chop_name)
    if not best_effort_test_state_write_allowed(chop_dir, category="axe-chop-state"):
        return chop_dir
    (chop_dir / "runs").mkdir(parents=True, exist_ok=True)
    return chop_dir


def generate_chop_run_id(when: datetime | None = None) -> str:
    """Produce a sortable, filesystem-safe run id from a timestamp.

    Microsecond precision keeps same-second runs from colliding while
    preserving lexicographic newest-last ordering.
    """
    ts = when or datetime.now(get_timezone())
    return ts.strftime("%Y%m%dT%H%M%S_%f")


def _safe_unlink(path: Path) -> None:
    if not best_effort_test_state_write_allowed(path, category="axe-chop-state"):
        return
    try:
        path.unlink()
    except OSError:
        pass


def _prune_chop_run_history(lumberjack_name: str, chop_name: str) -> None:
    """Trim per-chop run history to the newest ``MAX_CHOP_RUN_HISTORY`` terminal runs.

    Entries with status ``running`` are always kept regardless of position;
    pruning never deletes a run whose process is still being tracked.
    """
    index_path = chop_index_path(lumberjack_name, chop_name)
    raw = _state.read_json(index_path)
    if not isinstance(raw, list):
        return
    ordered = [str(r) for r in raw]

    kept: list[str] = []
    terminal_kept = 0
    to_prune: list[str] = []
    for rid in ordered:
        entry = read_chop_run(lumberjack_name, chop_name, rid)
        if entry is None:
            continue
        if entry.status in ACTIVE_CHOP_RUN_STATUSES:
            kept.append(rid)
        elif terminal_kept < MAX_CHOP_RUN_HISTORY:
            kept.append(rid)
            terminal_kept += 1
        else:
            to_prune.append(rid)

    _state.atomic_write_json(index_path, kept)
    for old_id in to_prune:
        _safe_unlink(chop_run_meta_path(lumberjack_name, chop_name, old_id))
        _safe_unlink(chop_run_log_path(lumberjack_name, chop_name, old_id))
        _safe_unlink(chop_run_result_path(lumberjack_name, chop_name, old_id))
        _safe_unlink(chop_run_context_path(lumberjack_name, chop_name, old_id))


def write_chop_run(entry: ChopRunEntry, output: str = "") -> None:
    """Persist a single-shot chop run-history entry.

    Writes the run log, the metadata JSON, then updates the index newest-first.
    Used for runs whose lifetime is fully known at record time (agent launches,
    missing-script records). Streaming script runs use the
    :func:`start_chop_run`/:func:`finish_chop_run` pair instead.

    History is pruned to ``MAX_CHOP_RUN_HISTORY`` terminal entries after each
    write; entries still in ``running`` state are preserved regardless of
    position.
    """
    lumberjack_name = entry.lumberjack_name
    chop_name = entry.chop_name
    log_path = chop_run_log_path(lumberjack_name, chop_name, entry.run_id)
    if not best_effort_test_state_write_allowed(log_path, category="axe-chop-log"):
        return
    ensure_chop_dirs(lumberjack_name, chop_name)

    log_path.write_text(output)
    entry.output_bytes = len(output.encode("utf-8"))
    entry.output_log = log_path.name

    meta_path = chop_run_meta_path(lumberjack_name, chop_name, entry.run_id)
    _state.atomic_write_json(meta_path, asdict(entry))

    index_path = chop_index_path(lumberjack_name, chop_name)
    existing_raw = _state.read_json(index_path)
    existing: list = existing_raw if isinstance(existing_raw, list) else []
    ordered: list[str] = [str(r) for r in existing if r != entry.run_id]
    ordered.insert(0, entry.run_id)
    _state.atomic_write_json(index_path, ordered)

    _prune_chop_run_history(lumberjack_name, chop_name)


def start_chop_run(entry: ChopRunEntry) -> Path:
    """Open a new run-history entry in ``running`` state and return its log path.

    Creates the runs directory, writes an empty log file (the script runner
    appends to this path as output arrives), persists the metadata JSON, and
    inserts ``run_id`` at the top of the index. Pruning is intentionally
    deferred to :func:`finish_chop_run` so an active run is never deleted
    out from under a still-executing subprocess.
    """
    lumberjack_name = entry.lumberjack_name
    chop_name = entry.chop_name
    log_path = chop_run_log_path(lumberjack_name, chop_name, entry.run_id)
    if not best_effort_test_state_write_allowed(log_path, category="axe-chop-log"):
        return log_path
    ensure_chop_dirs(lumberjack_name, chop_name)

    if not log_path.exists():
        log_path.write_bytes(b"")
    entry.output_log = log_path.name
    entry.output_bytes = 0

    meta_path = chop_run_meta_path(lumberjack_name, chop_name, entry.run_id)
    _state.atomic_write_json(meta_path, asdict(entry))

    index_path = chop_index_path(lumberjack_name, chop_name)
    existing_raw = _state.read_json(index_path)
    existing: list = existing_raw if isinstance(existing_raw, list) else []
    ordered: list[str] = [str(r) for r in existing if r != entry.run_id]
    ordered.insert(0, entry.run_id)
    _state.atomic_write_json(index_path, ordered)

    return log_path


def append_chop_run_output(
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    data: str | bytes,
) -> int:
    """Append output to a running chop's per-run log file.

    Returns the number of bytes written. No-op (returns 0) when the log does
    not exist — call :func:`start_chop_run` first.
    """
    log_path = chop_run_log_path(lumberjack_name, chop_name, run_id)
    if not best_effort_test_state_write_allowed(log_path, category="axe-chop-log"):
        return 0
    if not log_path.exists():
        return 0
    payload = data.encode("utf-8") if isinstance(data, str) else data
    try:
        with open(log_path, "ab") as f:
            f.write(payload)
    except OSError:
        return 0
    return len(payload)


def update_chop_run_pid(
    lumberjack_name: str, chop_name: str, run_id: str, pid: int
) -> None:
    """Patch a running chop's metadata with the subprocess PID.

    Best-effort: silently no-op when the metadata is missing or unreadable.
    """
    meta_path = chop_run_meta_path(lumberjack_name, chop_name, run_id)
    data = _state.read_json(meta_path)
    if not isinstance(data, dict):
        return
    data["pid"] = pid
    _state.atomic_write_json(meta_path, data)


def finish_chop_run(
    lumberjack_name: str,
    chop_name: str,
    run_id: str,
    *,
    status: ChopRunStatus,
    finished_at: str | None,
    duration_ms: int,
    exit_code: int | None = None,
    agent_pid: int | None = None,
    error: str | None = None,
    traceback: str | None = None,
    output_bytes: int | None = None,
    result_file: str | None = None,
    result: dict[str, Any] | None = None,
    proposals: list[dict[str, Any]] | None = None,
    launches: list[dict[str, Any]] | None = None,
    dry_run: bool | None = None,
    reason: str | None = None,
) -> None:
    """Transition a running chop entry and prune terminal history.

    Reads the existing metadata so fields written at start (e.g. ``pid``,
    ``source``, ``started_by``) survive the transition. ``launched`` is an
    active state and therefore keeps ``finished_at=None`` until lifecycle
    housekeeping observes all linked agent completions.
    """
    meta_path = chop_run_meta_path(lumberjack_name, chop_name, run_id)
    data = _state.read_json(meta_path)
    if not isinstance(data, dict):
        return

    data["status"] = status
    data["finished_at"] = finished_at
    data["duration_ms"] = duration_ms
    data["exit_code"] = exit_code
    data["agent_pid"] = agent_pid
    data["error"] = error
    data["traceback"] = traceback
    if result_file is not None:
        data["result_file"] = result_file
    if result is not None:
        data["result"] = result
    if proposals is not None:
        data["proposals"] = proposals
    if launches is not None:
        data["launches"] = launches
    if dry_run is not None:
        data["dry_run"] = dry_run
    if reason is not None:
        data["reason"] = reason

    if output_bytes is None:
        log_path = chop_run_log_path(lumberjack_name, chop_name, run_id)
        try:
            output_bytes = log_path.stat().st_size if log_path.exists() else 0
        except OSError:
            output_bytes = data.get("output_bytes", 0)
    data["output_bytes"] = output_bytes

    _state.atomic_write_json(meta_path, data)
    _prune_chop_run_history(lumberjack_name, chop_name)


def read_chop_run_index(lumberjack_name: str, chop_name: str) -> list[str]:
    """Read the newest-first list of run ids for a chop.

    Pruning bounds the index to ``MAX_CHOP_RUN_HISTORY`` terminal entries
    plus any entries whose script or launched action is still active, so
    callers do not need to slice defensively. Returns an empty list if the
    index is missing or invalid.
    """
    data = _state.read_json(chop_index_path(lumberjack_name, chop_name))
    if not isinstance(data, list):
        return []
    return [str(r) for r in data]


def read_chop_run(
    lumberjack_name: str, chop_name: str, run_id: str
) -> ChopRunEntry | None:
    """Read a single chop run metadata entry, or None if unavailable."""
    data = _state.read_json(chop_run_meta_path(lumberjack_name, chop_name, run_id))
    if not isinstance(data, dict):
        return None
    try:
        return ChopRunEntry(**data)
    except TypeError:
        return None


def read_chop_run_log_tail(
    lumberjack_name: str, chop_name: str, run_id: str, lines: int = 1000
) -> str:
    """Read the last ``lines`` lines of a chop run's output log."""
    log_path = chop_run_log_path(lumberjack_name, chop_name, run_id)
    if not log_path.exists():
        return ""
    return _state.read_tail_seek(log_path, lines)
