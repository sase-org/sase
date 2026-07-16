"""Markdown reports for slow tool-call hints."""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.core.paths import ensure_sase_directory, sase_subdir

from ._entry import ToolCallEntry
from ._report_recovery import (
    DEFAULT_MAX_TRANSCRIPT_BYTES,
    TranscriptRecovery as _TranscriptRecovery,
    recover_tool_call_output,
)
from ._report_render import (
    build_tool_call_report as _build_tool_call_report,
    has_captured_subagent_output,
)

_REPORT_SUBDIR = "tool_call_reports"
_REPORT_KEEP_COUNT = 50

# Kept here so callers and tests can lower the transcript scan limit at runtime.
_MAX_TRANSCRIPT_BYTES = DEFAULT_MAX_TRANSCRIPT_BYTES


@dataclass(frozen=True)
class SlowToolCallReportSpec:
    """Deferred report write request for one tool call."""

    entry: ToolCallEntry
    source_label: str | None
    agent_name: str | None
    report_path: str


def tool_call_report_path(entry: ToolCallEntry) -> str:
    """Return the deterministic report path for ``entry`` without writing."""
    tool = _safe_filename(entry.display_tool_name)
    hhmmss = _timestamp_hhmmss(entry.recorded_at)
    digest = _entry_digest(entry)
    return str(sase_subdir(_REPORT_SUBDIR) / f"{tool}-{hhmmss}-{digest}.md")


def write_tool_call_report(spec: SlowToolCallReportSpec) -> str | None:
    """Write a tool-call report atomically and return its path."""
    try:
        report_dir = Path(ensure_sase_directory(_REPORT_SUBDIR))
        report_path = Path(spec.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_recovery = (
            None
            if has_captured_subagent_output(spec.entry)
            else _recover_tool_call_output(spec.entry)
        )
        content = _build_tool_call_report(
            spec,
            transcript_recovery=transcript_recovery,
        )
        tmp_path = _write_atomic(report_path, content)
        os.replace(tmp_path, report_path)
        _prune_reports(report_dir)
        return str(report_path)
    except OSError:
        return None


def _recover_tool_call_output(entry: ToolCallEntry) -> _TranscriptRecovery:
    """Best-effort transcript recovery using the configured scan limit."""
    return recover_tool_call_output(
        entry,
        max_transcript_bytes=_MAX_TRANSCRIPT_BYTES,
    )


def _write_atomic(path: Path, content: str) -> str:
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=str(path.parent),
        text=True,
    )
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    return tmp_name


def _prune_reports(report_dir: Path) -> None:
    reports = sorted(
        report_dir.glob("*.md"),
        key=lambda path: (_mtime_ns(path), path.name),
        reverse=True,
    )
    for path in reports[_REPORT_KEEP_COUNT:]:
        try:
            path.unlink()
        except OSError:
            pass


def _mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _entry_digest(entry: ToolCallEntry) -> str:
    payload = "\0".join(
        (
            entry.source_path or "",
            str(entry.line_number),
            entry.tool_use_id or "",
        )
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]


def _timestamp_hhmmss(value: str | None) -> str:
    parsed = _parse_raw_timestamp(value)
    if parsed is None:
        return "unknown"
    return parsed.strftime("%H%M%S")


def _parse_raw_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return safe or "tool"


__all__ = [
    "SlowToolCallReportSpec",
    "tool_call_report_path",
    "write_tool_call_report",
]
