"""Permanent stage timing for commit-triggered agent-hood publication drains.

Every drain started by :func:`sase.agents_sync._commit_publication_drain.drain_agent_publications`
emits one structured JSONL line to ``~/.sase/logs/agent_publication_drains.jsonl``
(following the existing ``~/.sase/logs`` JSONL conventions). The line records the
project, the active request count, the distinct hoods, the outcome and error class,
whether the drain alarm fired and in which stage, plus per-stage durations and
inventory counters. ``pub-fix`` (``sase-1nf.10``) plans from these records.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
import fcntl
import json
import os
from pathlib import Path
import time
from typing import Any

DRAIN_LOG_FILENAME = "agent_publication_drains.jsonl"
DRAIN_LOG_SCHEMA_VERSION = 1
_DRAIN_LOG_MAX_BYTES = 1_000_000


def _drain_log_path(*, sase_home: Path | None = None) -> Path:
    """Return the drain-timing JSONL path, honoring ``SASE_HOME``."""

    from sase.core.paths import sase_home as _default_sase_home

    root = sase_home if sase_home is not None else _default_sase_home()
    return root / "logs" / DRAIN_LOG_FILENAME


@dataclass
class DrainTiming:
    """Mutable per-drain timing accumulator threaded through the transaction."""

    project_key: str = ""
    active_requests: int = 0
    distinct_hoods: int = 0
    outcome: str = "unknown"
    stage: str = ""
    error: str | None = None
    error_class: str | None = None
    failure_scope: str | None = None
    failure_stage: str | None = None
    alarm_fired: bool = False
    alarm_stage: str | None = None
    alarm_keys: tuple[tuple[str, str], ...] | None = None
    active_keys: tuple[tuple[str, str], ...] = ()
    lock_wait_seconds: float = 0.0
    git_op_counts: dict[str, int] = field(default_factory=dict)
    runs_scanned: int = 0
    commit_record_calls: int = 0
    prompt_bytes: int = 0
    chat_bytes: int = 0
    stage_durations: dict[str, float] = field(default_factory=dict)

    @contextmanager
    def record_stage(self, name: str) -> Iterator[None]:
        """Time one drain stage, accumulating into ``stage_durations``."""

        self.stage = name
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self.stage_durations[name] = self.stage_durations.get(name, 0.0) + elapsed

    def to_json_dict(self) -> dict[str, Any]:
        from sase.agents_sync.publication_outbox_diagnostics import (
            classify_publication_error,
        )

        error_class = self.error_class
        if error_class is None and self.error:
            error_class = classify_publication_error(self.error)
        return {
            "schema_version": DRAIN_LOG_SCHEMA_VERSION,
            "timestamp": time.time(),
            "pid": os.getpid(),
            "project_key": self.project_key,
            "active_requests": self.active_requests,
            "distinct_hoods": self.distinct_hoods,
            "outcome": self.outcome,
            "stage": self.stage,
            "error": self.error,
            "error_class": error_class,
            "failure_scope": self.failure_scope,
            "failure_stage": self.failure_stage,
            "alarm_fired": self.alarm_fired,
            "alarm_stage": self.alarm_stage,
            "alarm_keys": (
                [list(key) for key in self.alarm_keys]
                if self.alarm_keys is not None
                else None
            ),
            "lock_wait_seconds": self.lock_wait_seconds,
            "git_op_counts": dict(self.git_op_counts),
            "runs_scanned": self.runs_scanned,
            "commit_record_calls": self.commit_record_calls,
            "prompt_bytes": self.prompt_bytes,
            "chat_bytes": self.chat_bytes,
            "stage_durations": dict(self.stage_durations),
        }


def emit_drain_timing(
    timing: DrainTiming,
    *,
    log_path: Path | None = None,
) -> None:
    """Append one drain record to the bounded, rotated JSONL log.

    Never raises: timing must not fail a publication drain.
    """

    path = log_path if log_path is not None else _drain_log_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_drain_log(path)
        with path.open("a", encoding="utf-8") as output_file:
            try:
                fcntl.flock(output_file.fileno(), fcntl.LOCK_EX)
                json.dump(timing.to_json_dict(), output_file, sort_keys=True)
                output_file.write("\n")
            finally:
                fcntl.flock(output_file.fileno(), fcntl.LOCK_UN)
    except (OSError, ValueError):
        return


def _rotate_drain_log(path: Path) -> None:
    """Rotate the drain log once past 1 MiB, keeping a single ``.1`` backup."""

    try:
        if not path.is_file() or path.stat().st_size <= _DRAIN_LOG_MAX_BYTES:
            return
        backup = path.with_name(f"{path.name}.1")
        backup.unlink(missing_ok=True)
        path.rename(backup)
    except OSError:
        return


__all__ = [
    "DRAIN_LOG_FILENAME",
    "DRAIN_LOG_SCHEMA_VERSION",
    "DrainTiming",
    "emit_drain_timing",
]
