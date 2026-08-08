"""Durable, bounded history for SASE-managed agent-CLI update runs."""

from __future__ import annotations

import json
import logging
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

from sase.core.paths import sase_subdir
from sase.core.time import get_timezone
from sase.logs._bounded import (
    DEFAULT_MAX_BYTES,
    append_jsonl_record,
    max_bytes_from_env,
)

from .models import (
    AgentCliOperation,
    AgentCliUpdateResult,
    UpdateResultStatus,
    UpdateTrigger,
)

AGENT_CLI_UPDATE_JOURNAL: str | None = None
ENV_MAX_BYTES = "SASE_AGENT_CLI_UPDATE_JOURNAL_MAX_BYTES"
HISTORY_SCHEMA_VERSION = 1
MAX_REASON_CHARS = 500
MAX_OUTPUT_TAIL_CHARS = 2_000

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class AgentCliUpdateRunEntry:
    """The durable subset of one agent CLI's update or install result."""

    name: str
    display_name: str
    status: UpdateResultStatus
    old_version: str | None
    new_version: str | None
    command: tuple[str, ...] | None
    reason: str | None
    elapsed_seconds: float
    output_tail: str | None
    operation: AgentCliOperation = AgentCliOperation.UPDATE
    script_digest: str | None = None


@dataclass(frozen=True)
class AgentCliUpdateRun:
    """One journaled batch of SASE-managed agent-CLI update results."""

    schema_version: int
    run_id: str
    timestamp: str
    epoch: float
    trigger: UpdateTrigger
    all_clis: bool
    elapsed_seconds: float
    counts: dict[str, int]
    entries: tuple[AgentCliUpdateRunEntry, ...]

    @property
    def executed_entries(self) -> tuple[AgentCliUpdateRunEntry, ...]:
        """Return entries for which SASE actually ran an update command."""
        return tuple(entry for entry in self.entries if entry.command is not None)

    @property
    def executed_count(self) -> int:
        """Return the number of entries for which an update command ran."""
        return len(self.executed_entries)


class RecordFn(Protocol):
    """Callable used by the execution choke point to persist one run."""

    def __call__(
        self,
        results: Sequence[AgentCliUpdateResult],
        *,
        trigger: UpdateTrigger,
        elapsed: float,
    ) -> AgentCliUpdateRun | None: ...


def agent_cli_update_journal_path() -> Path:
    """Return the canonical agent-CLI update journal path."""
    return Path(
        AGENT_CLI_UPDATE_JOURNAL or (sase_subdir("logs") / "agent_cli_updates.jsonl")
    )


def should_record_run(results: Sequence[AgentCliUpdateResult]) -> bool:
    """Return whether at least one update command reached a terminal outcome."""
    return any(
        result.status in {UpdateResultStatus.UPDATED, UpdateResultStatus.FAILED}
        for result in results
    )


def build_agent_cli_update_run(
    results: Sequence[AgentCliUpdateResult],
    *,
    trigger: UpdateTrigger,
    elapsed: float,
    now: datetime | None = None,
    run_id: str | None = None,
) -> AgentCliUpdateRun:
    """Build one serializable update run with an injectable clock and ID."""
    instant = now or datetime.now(get_timezone())
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=get_timezone())
    entries = tuple(_run_entry(result) for result in results)
    raw_counts = Counter(result.status.value for result in results)
    counts = {status.value: raw_counts[status.value] for status in UpdateResultStatus}
    return AgentCliUpdateRun(
        schema_version=HISTORY_SCHEMA_VERSION,
        run_id=run_id or uuid.uuid4().hex[:12],
        timestamp=instant.isoformat(timespec="seconds"),
        epoch=instant.timestamp(),
        trigger=trigger,
        all_clis=len(results) > 1,
        elapsed_seconds=elapsed,
        counts=counts,
        entries=entries,
    )


def record_agent_cli_update_run(
    results: Sequence[AgentCliUpdateResult],
    *,
    trigger: UpdateTrigger,
    elapsed: float,
    path: Path | None = None,
    now: datetime | None = None,
    run_id: str | None = None,
) -> AgentCliUpdateRun | None:
    """Best-effort append of one meaningful agent-CLI update run."""
    if not should_record_run(results):
        return None
    try:
        run = build_agent_cli_update_run(
            results,
            trigger=trigger,
            elapsed=elapsed,
            now=now,
            run_id=run_id,
        )
        append_jsonl_record(
            path or agent_cli_update_journal_path(),
            _run_record(run),
            max_bytes=max_bytes_from_env(ENV_MAX_BYTES, DEFAULT_MAX_BYTES),
            sort_keys=True,
        )
    except Exception:  # noqa: BLE001 - journaling must never fail an update.
        log.debug("Could not append agent-CLI update journal", exc_info=True)
        return None
    return run


def read_agent_cli_update_runs(
    *,
    limit: int = 200,
    path: Path | None = None,
) -> tuple[AgentCliUpdateRun, ...]:
    """Read the newest valid journal records, skipping malformed lines."""
    if limit <= 0:
        return ()
    target = path or agent_cli_update_journal_path()
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()

    runs: list[AgentCliUpdateRun] = []
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, Mapping):
                continue
            run = _decode_run(payload)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        runs.append(run)
        if len(runs) >= limit:
            break
    return tuple(runs)


def _run_entry(result: AgentCliUpdateResult) -> AgentCliUpdateRunEntry:
    return AgentCliUpdateRunEntry(
        name=result.name,
        display_name=result.display_name,
        status=result.status,
        old_version=result.old_version,
        new_version=result.new_version,
        command=result.command,
        reason=_truncate_start(result.reason, MAX_REASON_CHARS),
        elapsed_seconds=result.elapsed,
        output_tail=(
            _truncate_end(result.output_tail, MAX_OUTPUT_TAIL_CHARS)
            if result.status is UpdateResultStatus.FAILED
            else None
        ),
        operation=result.operation,
        script_digest=result.script_digest,
    )


def _run_record(run: AgentCliUpdateRun) -> dict[str, Any]:
    return {
        "schema_version": run.schema_version,
        "run_id": run.run_id,
        "timestamp": run.timestamp,
        "epoch": run.epoch,
        "trigger": run.trigger.value,
        "all_clis": run.all_clis,
        "elapsed_seconds": run.elapsed_seconds,
        "counts": run.counts,
        "entries": [
            {
                "name": entry.name,
                "display_name": entry.display_name,
                "status": entry.status.value,
                "old_version": entry.old_version,
                "new_version": entry.new_version,
                "command": list(entry.command) if entry.command is not None else None,
                "reason": entry.reason,
                "elapsed_seconds": entry.elapsed_seconds,
                "output_tail": entry.output_tail,
                "operation": entry.operation.value,
                "script_digest": entry.script_digest,
            }
            for entry in run.entries
        ],
    }


def _decode_run(payload: Mapping[str, object]) -> AgentCliUpdateRun:
    if _required_int(payload, "schema_version") != HISTORY_SCHEMA_VERSION:
        raise ValueError("unsupported agent-CLI update history schema")
    entries_raw = _required_list(payload, "entries")
    entries = tuple(_decode_entry(_required_mapping(item)) for item in entries_raw)
    counts_raw = _required_mapping(payload.get("counts"))
    counts = {
        status.value: _required_int(counts_raw, status.value)
        for status in UpdateResultStatus
    }
    trigger_raw = _required_str(payload, "trigger")
    try:
        trigger = UpdateTrigger(trigger_raw)
    except ValueError:
        trigger = UpdateTrigger.UNKNOWN
    return AgentCliUpdateRun(
        schema_version=HISTORY_SCHEMA_VERSION,
        run_id=_required_str(payload, "run_id"),
        timestamp=_required_str(payload, "timestamp"),
        epoch=_required_float(payload, "epoch"),
        trigger=trigger,
        all_clis=_required_bool(payload, "all_clis"),
        elapsed_seconds=_required_float(payload, "elapsed_seconds"),
        counts=counts,
        entries=entries,
    )


def _decode_entry(payload: Mapping[str, object]) -> AgentCliUpdateRunEntry:
    command_raw = payload.get("command")
    command = None
    if command_raw is not None:
        command = tuple(
            _required_str_value(item) for item in _required_list_value(command_raw)
        )
    return AgentCliUpdateRunEntry(
        name=_required_str(payload, "name"),
        display_name=_required_str(payload, "display_name"),
        status=UpdateResultStatus(_required_str(payload, "status")),
        old_version=_optional_str(payload, "old_version"),
        new_version=_optional_str(payload, "new_version"),
        command=command,
        reason=_optional_str(payload, "reason"),
        elapsed_seconds=_required_float(payload, "elapsed_seconds"),
        output_tail=_optional_str(payload, "output_tail"),
        operation=_operation(payload.get("operation")),
        script_digest=_absent_or_str(payload.get("script_digest")),
    )


def _operation(value: object) -> AgentCliOperation:
    """Decode an operation, defaulting to the update-only records SASE wrote first."""
    if not isinstance(value, str):
        return AgentCliOperation.UPDATE
    try:
        return AgentCliOperation(value)
    except ValueError:
        return AgentCliOperation.UPDATE


def _absent_or_str(value: object) -> str | None:
    """Read a field added after the schema shipped; absence is not corruption."""
    return value if isinstance(value, str) else None


def _truncate_start(value: str | None, limit: int) -> str | None:
    return value[:limit] if value is not None else None


def _truncate_end(value: str | None, limit: int) -> str | None:
    return value[-limit:] if value is not None else None


def _required_mapping(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("expected mapping")
    return value


def _required_list(payload: Mapping[str, object], key: str) -> list[object]:
    return _required_list_value(payload.get(key))


def _required_list_value(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("expected list")
    return value


def _required_str(payload: Mapping[str, object], key: str) -> str:
    return _required_str_value(payload.get(key))


def _required_str_value(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("expected string")
    return value


def _optional_str(payload: Mapping[str, object], key: str) -> str | None:
    if key not in payload:
        raise ValueError(f"missing required field: {key}")
    value = payload[key]
    if value is not None and not isinstance(value, str):
        raise TypeError("expected optional string")
    return value


def _required_float(payload: Mapping[str, object], key: str) -> float:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError("expected number")
    return float(value)


def _required_int(payload: Mapping[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("expected integer")
    return value


def _required_bool(payload: Mapping[str, object], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise TypeError("expected boolean")
    return value


__all__ = [
    "AGENT_CLI_UPDATE_JOURNAL",
    "ENV_MAX_BYTES",
    "HISTORY_SCHEMA_VERSION",
    "MAX_OUTPUT_TAIL_CHARS",
    "MAX_REASON_CHARS",
    "AgentCliUpdateRun",
    "AgentCliUpdateRunEntry",
    "RecordFn",
    "agent_cli_update_journal_path",
    "build_agent_cli_update_run",
    "read_agent_cli_update_runs",
    "record_agent_cli_update_run",
    "should_record_run",
]
