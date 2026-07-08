"""Markdown reports for slow tool-call hints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.paths import ensure_sase_directory, sase_subdir
from sase.core.time import get_timezone

from ._entry import ToolCallEntry
from .slow import format_long_duration

_REPORT_SUBDIR = "tool_call_reports"
_REPORT_KEEP_COUNT = 50
_MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
_MAX_RECOVERED_OUTPUT_CHARS = 64 * 1024

_OUTPUT_KEYS = (
    "exit_code",
    "stderr_preview",
    "stdout_preview",
    "output_preview",
    "content_preview",
    "result_preview",
    "preview",
)
_TEXT_RESULT_KEYS = (
    "stderr",
    "stdout",
    "output",
    "content",
    "text",
    "error",
    "result",
    "tool_result",
    "tool_response",
    "response",
)


@dataclass(frozen=True)
class SlowToolCallReportSpec:
    """Deferred report write request for one tool call."""

    entry: ToolCallEntry
    source_label: str | None
    agent_name: str | None
    report_path: str


@dataclass(frozen=True)
class _TranscriptRecovery:
    text: str | None
    note: str


def tool_call_report_path(entry: ToolCallEntry) -> str:
    """Return the deterministic report path for ``entry`` without writing."""
    tool = _safe_filename(entry.display_tool_name)
    hhmmss = _timestamp_hhmmss(entry.recorded_at)
    digest = _entry_digest(entry)
    return str(sase_subdir(_REPORT_SUBDIR) / f"{tool}-{hhmmss}-{digest}.md")


def _build_tool_call_report(
    spec: SlowToolCallReportSpec,
    *,
    transcript_recovery: _TranscriptRecovery | None = None,
) -> str:
    """Build the Markdown report body for a tool call."""
    entry = spec.entry
    duration = (
        f" after {format_long_duration(entry.duration_ms)}"
        if entry.duration_ms is not None
        else ""
    )
    title_glyph, title_status = _title_status(entry)

    lines: list[str] = [
        f"# {title_glyph} {entry.display_tool_name} - {title_status}{duration}",
        "",
        *_metadata_lines(spec),
        "",
        "## Target",
        "",
        f"`{entry.compact_target or 'unavailable'}`",
        "",
        "## Tool Input",
        "",
        *_tool_input_lines(entry),
        "",
    ]
    if _include_error_section(entry):
        lines.extend(
            (
                "## Error",
                "",
                *_error_lines(entry),
                "",
            )
        )
    lines.extend(
        [
            "## Recorded Output",
            "",
            *_recorded_output_lines(entry),
            "",
            "## Full Output (transcript)",
            "",
            *_transcript_lines(transcript_recovery),
            "",
            "## Provenance",
            "",
            *_provenance_lines(entry),
            "",
        ]
    )
    return "\n".join(lines)


def write_tool_call_report(spec: SlowToolCallReportSpec) -> str | None:
    """Write a tool-call report atomically and return its path."""
    try:
        report_dir = Path(ensure_sase_directory(_REPORT_SUBDIR))
        report_path = Path(spec.report_path)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        transcript_recovery = _recover_tool_call_output(spec.entry)
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
    """Best-effort transcript recovery for a tool call."""
    tool_use_id = entry.tool_use_id
    if not tool_use_id:
        return _TranscriptRecovery(None, "Not recovered: tool use ID unavailable.")

    transcript_path = entry.transcript_path
    if not transcript_path:
        return _TranscriptRecovery(None, "Not recovered: transcript unavailable.")

    path = Path(transcript_path).expanduser()
    try:
        size = path.stat().st_size
    except OSError:
        return _TranscriptRecovery(None, "Not recovered: transcript file missing.")

    if size > _MAX_TRANSCRIPT_BYTES:
        return _TranscriptRecovery(
            None,
            "Not recovered: transcript exceeds the 16 MiB scan cap.",
        )

    parts: list[str] = []
    seen: set[str] = set()
    recovered_chars = 0
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if tool_use_id not in line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for mapping in _walk_mappings(payload):
                    if not _references_tool_use_id(mapping, tool_use_id):
                        continue
                    for text in _extract_text_result_fields(mapping):
                        if not text or text in seen:
                            continue
                        seen.add(text)
                        parts.append(text)
                        recovered_chars += len(text)
                        if recovered_chars > _MAX_RECOVERED_OUTPUT_CHARS * 2:
                            break
                    if recovered_chars > _MAX_RECOVERED_OUTPUT_CHARS * 2:
                        break
    except OSError:
        return _TranscriptRecovery(None, "Not recovered: transcript read failed.")

    if not parts:
        return _TranscriptRecovery(
            None,
            "Not recovered: no matching result text found in transcript.",
        )

    text = "\n\n---\n\n".join(parts)
    if len(text) > _MAX_RECOVERED_OUTPUT_CHARS:
        remaining = len(text) - _MAX_RECOVERED_OUTPUT_CHARS
        text = (
            text[:_MAX_RECOVERED_OUTPUT_CHARS] + f"\n...[truncated {remaining} chars]"
        )
        return _TranscriptRecovery(text, "Recovered and capped at 64 KiB.")
    return _TranscriptRecovery(text, "Recovered from transcript.")


def _metadata_lines(spec: SlowToolCallReportSpec) -> list[str]:
    entry = spec.entry
    agent = spec.agent_name or "unavailable"
    if spec.source_label:
        agent = f"{agent} (chip: `{spec.source_label}`)"

    started = _format_local_timestamp(entry.recorded_at)
    completed = _format_local_timestamp(entry.completed_at)
    lines = [
        f"- **Agent**: {agent}",
        f"- **Runtime**: {entry.runtime or 'unavailable'} | "
        f"**Session**: {entry.session_id or 'unavailable'}",
        f"- **Started**: {started} | **Completed**: {completed} (local)",
    ]
    if entry.cwd:
        lines.append(f"- **Cwd**: {entry.cwd}")
    if entry.permission_mode or entry.tool_use_id:
        lines.append(
            f"- **Permission mode**: {entry.permission_mode or 'unavailable'} | "
            f"**Tool use ID**: {entry.tool_use_id or 'unavailable'}"
        )
    return lines


def _tool_input_lines(entry: ToolCallEntry) -> list[str]:
    if not entry.tool_input_summary:
        return ["No tool input summary recorded."]
    return [_fenced(_json_dumps(entry.tool_input_summary), "json")]


def _title_status(entry: ToolCallEntry) -> tuple[str, str]:
    status = (entry.status or "").lower()
    if status == "success":
        return "\u2714", "succeeded"
    if status in {"failure", "failed"}:
        return "\u2718", "failed"
    return "\u25fc", status.replace("_", " ") or "completed"


def _include_error_section(entry: ToolCallEntry) -> bool:
    status = (entry.status or "").lower()
    return status in {"failure", "failed"} or bool(_error_values(entry))


def _error_lines(entry: ToolCallEntry) -> list[str]:
    errors = _error_values(entry)
    if not errors:
        return ["No explicit error recorded."]
    return [_fenced("\n\n".join(errors), "text")]


def _error_values(entry: ToolCallEntry) -> list[str]:
    errors: list[str] = []
    if entry.error:
        errors.append(entry.error)
    response_error = entry.tool_response_summary.get("error")
    if response_error:
        errors.append(
            response_error
            if isinstance(response_error, str)
            else _json_dumps(response_error)
        )
    return errors


def _recorded_output_lines(entry: ToolCallEntry) -> list[str]:
    lines: list[str] = []
    truncated = False
    for key in _OUTPUT_KEYS:
        if key not in entry.tool_response_summary:
            continue
        value = entry.tool_response_summary[key]
        if value in (None, ""):
            continue
        text = value if isinstance(value, str) else _json_dumps(value)
        truncated = truncated or _looks_truncated(text)
        lines.extend((f"### {key}", "", _fenced(text, "text"), ""))

    if not lines:
        return ["No recorded output summary fields were available."]
    if truncated:
        lines.append(
            "Note: one or more recorded fields include truncation markers from "
            "the tool-call recorder."
        )
    return lines


def _transcript_lines(recovery: _TranscriptRecovery | None) -> list[str]:
    if recovery is None:
        return ["Not recovered: transcript scan not requested."]
    if recovery.text:
        return [recovery.note, "", _fenced(recovery.text, "text")]
    return [recovery.note]


def _provenance_lines(entry: ToolCallEntry) -> list[str]:
    artifact = entry.source_path or "unavailable"
    if entry.source_path and entry.line_number:
        artifact = f"{entry.source_path}:{entry.line_number}"
    return [
        f"- Artifact: {artifact}",
        f"- Artifact dir: {entry.artifact_dir or 'unavailable'}",
        f"- Transcript: {entry.transcript_path or 'unavailable'}",
    ]


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


def _format_local_timestamp(value: str | None) -> str:
    parsed = _parse_raw_timestamp(value)
    if parsed is None:
        return "unavailable"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=get_timezone())
    parsed = parsed.astimezone(get_timezone())
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


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


def _json_dumps(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, default=str)


def _fenced(value: str, language: str) -> str:
    fence = "```"
    if fence in value:
        fence = "````"
    return f"{fence}{language}\n{value}\n{fence}"


def _looks_truncated(value: str) -> bool:
    lowered = value.lower()
    return "...[" in value or "truncated" in lowered


def _walk_mappings(value: Any) -> Iterator[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk_mappings(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_mappings(child)


def _references_tool_use_id(mapping: dict[str, Any], tool_use_id: str) -> bool:
    for key in ("tool_use_id", "toolUseId", "tool_call_id", "toolCallId", "id"):
        if mapping.get(key) == tool_use_id:
            return True
    return False


def _extract_text_result_fields(mapping: dict[str, Any]) -> list[str]:
    parts: list[str] = []
    for key in _TEXT_RESULT_KEYS:
        if key in mapping:
            parts.extend(_text_values(mapping[key]))
    return parts


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        list_parts: list[str] = []
        for item in value:
            list_parts.extend(_text_values(item))
        return list_parts
    if isinstance(value, dict):
        dict_parts: list[str] = []
        for key in _TEXT_RESULT_KEYS:
            if key in value:
                dict_parts.extend(_text_values(value[key]))
        return dict_parts
    return []


__all__ = [
    "SlowToolCallReportSpec",
    "tool_call_report_path",
    "write_tool_call_report",
]
