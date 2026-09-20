"""JSONL stage protocol: parse, ingest through core, and timeline math.

``tools/run_silent`` writes events; this module never writes SQLite itself.
Rust ``tool_run_append_event`` owns validation and projection.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any

from sase.core.tool_run import tool_run_append_event
from sase.tool.logs import OUTPUT_RECORD_KIND, log_policy
from sase.tool.render import EMPTY, format_duration_ms


SCHEMA_VERSION = 1
KIND_STARTED = "started"
KIND_FINISHED = "finished"
MAX_LINE_BYTES = 65536
BATCH_LIMIT = 32
FLUSH_LIMIT = 10_000
READ_CHUNK_BYTES = 1024 * 1024


@dataclass
class _TimelineAttribution:
    """Unattributed child time from the union of completed stage intervals."""

    unattributed_ms: int | None
    incomplete: bool


@dataclass
class StageIngestor:
    """Tail one events.jsonl file on the executor's existing wait tick."""

    path: Path
    run_id: str
    compact: bool = False
    event_max_bytes: int = 0
    offset: int = 0
    pending: bytes = b""
    seen_event_ids: set[str] = field(default_factory=set)
    announced: set[str] = field(default_factory=set)
    diagnostics: list[str] = field(default_factory=list)
    stages: dict[str, dict[str, Any]] = field(default_factory=dict)
    compact_lines: list[str] = field(default_factory=list)
    queued: deque[tuple[dict[str, Any] | None, str | None]] = field(
        default_factory=deque
    )

    def tick(self, *, flush: bool = False, limit: int = BATCH_LIMIT) -> list[str]:
        """Ingest newly appended bytes. Flush rereads from offset 0."""

        if flush:
            self.offset = 0
            self.pending = b""
            self.queued.clear()
            limit = FLUSH_LIMIT
        self.queued.extend(self._read_records(flush=flush))
        produced: list[str] = []
        remaining = max(0, limit)
        while remaining > 0 and self.queued:
            record, diagnostic = self.queued.popleft()
            remaining -= 1
            if diagnostic:
                self._note(diagnostic)
                continue
            if record is None:
                continue
            line = self._ingest_record(record)
            if line:
                produced.append(line)
        return produced

    def flush(self) -> list[str]:
        """Reread the file at settlement and ingest surviving records."""

        return self.tick(flush=True, limit=FLUSH_LIMIT)

    def _read_records(
        self, *, flush: bool
    ) -> list[tuple[dict[str, Any] | None, str | None]]:
        if not self.path.is_file():
            return []
        try:
            size = self.path.stat().st_size
        except OSError as exc:
            self._note(f"could not stat events file: {exc}")
            return []
        cap = self.event_max_bytes or size
        if self.offset > size:
            self.offset = 0
            self.pending = b""
        try:
            with self.path.open("rb") as handle:
                handle.seek(self.offset)
                budget = min(READ_CHUNK_BYTES, max(0, cap - self.offset))
                chunk = handle.read(budget)
                self.offset = handle.tell()
        except OSError as exc:
            self._note(f"could not read events file: {exc}")
            return []
        self.pending += chunk
        records: list[tuple[dict[str, Any] | None, str | None]] = []
        while True:
            newline = self.pending.find(b"\n")
            if newline < 0:
                if len(self.pending) > MAX_LINE_BYTES:
                    self.pending = b""
                    records.append((None, "oversized events.jsonl line dropped"))
                break
            raw = self.pending[:newline]
            self.pending = self.pending[newline + 1 :]
            records.append(_parse_event_line(raw))
        if flush and self.pending:
            leftover = self.pending
            self.pending = b""
            if leftover.strip():
                parsed = _parse_event_line(leftover)
                if parsed[0] is None:
                    records.append((None, "torn final events.jsonl line"))
                else:
                    records.append(parsed)
        return records

    def _ingest_record(self, record: dict[str, Any]) -> str | None:
        if record.get("kind") == OUTPUT_RECORD_KIND:
            return None
        run_id = str(record.get("run_id") or "")
        if run_id != self.run_id:
            self._note(f"ignored cross-run event for {run_id or 'missing-run'}")
            return None
        events = _jsonl_to_core_events(record)
        compact_line: str | None = None
        for event in events:
            event_id = str(event.get("event_id") or "")
            if event_id and event_id in self.seen_event_ids:
                continue
            try:
                result = tool_run_append_event(
                    {"schema_version": SCHEMA_VERSION, "event": event}
                )
            except Exception as exc:  # noqa: BLE001 - recording must fail open.
                self._note(str(exc))
                continue
            if event_id:
                self.seen_event_ids.add(event_id)
            replayed = bool(result.get("replayed"))
            stage = event.get("stage")
            if isinstance(stage, dict):
                self._project_stage(stage)
                if (
                    self.compact
                    and not replayed
                    and event.get("kind") == "stage_finished"
                ):
                    stage_id = str(stage.get("stage_id") or "")
                    if stage_id and stage_id not in self.announced:
                        compact_line = format_stage_progress(
                            self.stages.get(stage_id) or stage
                        )
                        self.announced.add(stage_id)
                        self.compact_lines.append(compact_line)
        return compact_line

    def _project_stage(self, stage: dict[str, Any]) -> None:
        stage_id = str(stage.get("stage_id") or "")
        if not stage_id:
            return
        current = dict(self.stages.get(stage_id) or {})
        current.update(
            {key: value for key, value in stage.items() if value is not None}
        )
        self.stages[stage_id] = current

    def _note(self, message: str) -> None:
        text = message.strip()
        if text and text not in self.diagnostics:
            self.diagnostics.append(text)


def _parse_event_line(raw: bytes) -> tuple[dict[str, Any] | None, str | None]:
    if len(raw) > MAX_LINE_BYTES:
        return None, "oversized events.jsonl line dropped"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return None, "malformed events.jsonl line is not utf-8"
    stripped = text.strip()
    if not stripped:
        return None, None
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return None, "malformed events.jsonl line"
    if not isinstance(payload, dict):
        return None, "malformed events.jsonl line"
    if int(payload.get("schema_version") or 0) != SCHEMA_VERSION:
        return None, "events.jsonl schema_version is not 1"
    kind = str(payload.get("kind") or "")
    if kind not in {KIND_STARTED, KIND_FINISHED, OUTPUT_RECORD_KIND}:
        return None, f"unknown events.jsonl kind {kind!r}"
    return payload, None


def _jsonl_to_core_events(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Convert one producer JSONL record into core append-event payloads."""

    kind = str(record.get("kind") or "")
    run_id = str(record.get("run_id") or "")
    stage_id = str(record.get("stage_id") or "")
    event_id = str(record.get("event_id") or "")
    description = str(record.get("description") or "")
    started_ts = _optional_int(record.get("started_ts"))
    finished_ts = _optional_int(record.get("finished_ts"))
    elapsed_ms = _optional_int(record.get("elapsed_ms"))
    exit_code = _optional_int(record.get("exit_code"))
    output_bytes = _optional_int(record.get("output_bytes"))
    created_ts = started_ts
    if kind == KIND_FINISHED and finished_ts is not None:
        created_ts = finished_ts
    if created_ts is None:
        created_ts = 0
    stage: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "stage_id": stage_id,
        "run_id": run_id,
        "attempt": 1,
        "description": description,
        "started_ts": started_ts,
        "incomplete": kind == KIND_STARTED,
        "diagnostics": [],
    }
    if kind == KIND_FINISHED:
        stage["finished_ts"] = finished_ts
        stage["elapsed_ms"] = elapsed_ms
        stage["exit_code"] = exit_code
        stage["output_bytes"] = output_bytes
        stage["incomplete"] = False
    core_kind = "stage_started" if kind == KIND_STARTED else "stage_finished"
    return [
        {
            "schema_version": SCHEMA_VERSION,
            "event_id": event_id,
            "run_id": run_id,
            "attempt": 1,
            "kind": core_kind,
            "created_ts": created_ts if created_ts < 10**12 else created_ts // 1000,
            "stage": stage,
            "diagnostics": [],
        }
    ]


def ingest_event_file(path: Path, run_id: str) -> list[str]:
    """Reread an events file for lost-run recovery. Idempotent by event id."""

    if not run_id or not path:
        return []
    policy = log_policy()
    ingestor = StageIngestor(
        path=path,
        run_id=run_id,
        compact=False,
        event_max_bytes=int(policy.get("event_max_bytes") or 0),
    )
    ingestor.flush()
    return list(ingestor.diagnostics)


def unattributed_from_stages(
    stages: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    duration_ms: object,
) -> _TimelineAttribution:
    """Union completed observed intervals; never invent a missing duration."""

    if type(duration_ms) is not int:
        return _TimelineAttribution(unattributed_ms=None, incomplete=True)
    incomplete = False
    intervals: list[tuple[int, int]] = []
    for stage in stages:
        if not isinstance(stage, dict):
            incomplete = True
            continue
        if stage.get("incomplete"):
            incomplete = True
            continue
        start = stage.get("started_ts")
        end = stage.get("finished_ts")
        if type(start) is not int or type(end) is not int:
            incomplete = True
            continue
        if end < start:
            incomplete = True
            continue
        intervals.append((start, end))
    covered = _union_ms(intervals)
    unattributed = duration_ms - covered
    if unattributed < 0:
        return _TimelineAttribution(unattributed_ms=0, incomplete=True)
    return _TimelineAttribution(unattributed_ms=unattributed, incomplete=incomplete)


def attach_timeline(envelope: dict[str, Any]) -> dict[str, Any]:
    """Add presentation fields shared by show, show -j, and compact footer."""

    run = envelope.get("run")
    stages = envelope.get("stages") or ()
    stage_list = [item for item in stages if isinstance(item, dict)]
    if not stage_list:
        return envelope
    duration = run.get("duration_ms") if isinstance(run, dict) else None
    attribution = unattributed_from_stages(stage_list, duration)
    envelope["unattributed_ms"] = attribution.unattributed_ms
    envelope["unattributed_incomplete"] = attribution.incomplete
    return envelope


def format_stage_progress(stage: dict[str, Any]) -> str:
    """One compact completion line; values match human ``show`` stages."""

    desc = str(stage.get("description") or EMPTY)
    elapsed = stage.get("elapsed_ms")
    duration = format_duration_ms(elapsed if type(elapsed) is int else None)
    extra = ""
    if stage.get("incomplete"):
        extra = "  incomplete"
    return f"{desc}  {duration}{extra}"


def format_unattributed_line(attribution: _TimelineAttribution) -> str:
    duration = format_duration_ms(attribution.unattributed_ms)
    extra = "  incomplete" if attribution.incomplete else ""
    return f"unattrib  {duration}{extra}"


def _union_ms(intervals: list[tuple[int, int]]) -> int:
    if not intervals:
        return 0
    ordered = sorted(interval for interval in intervals if interval[1] >= interval[0])
    if not ordered:
        return 0
    total = 0
    current_start, current_end = ordered[0]
    for start, end in ordered[1:]:
        if start <= current_end:
            current_end = max(current_end, end)
            continue
        total += current_end - current_start
        current_start, current_end = start, end
    total += current_end - current_start
    return total


def _optional_int(value: object) -> int | None:
    if type(value) is int:
        return value
    if type(value) is float and value == int(value):
        return int(value)
    return None


__all__ = [
    "BATCH_LIMIT",
    "KIND_FINISHED",
    "KIND_STARTED",
    "MAX_LINE_BYTES",
    "SCHEMA_VERSION",
    "StageIngestor",
    "attach_timeline",
    "format_stage_progress",
    "format_unattributed_line",
    "ingest_event_file",
    "unattributed_from_stages",
]
