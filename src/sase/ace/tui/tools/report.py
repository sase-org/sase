"""Markdown reports for slow tool-call hints."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sase.core.paths import ensure_sase_directory, sase_subdir
from sase.core.time import get_timezone
from sase.llm_provider._tool_call_common import (
    COMMAND_OUTPUT_MIN_TAIL_LINES,
    command_output_omission_marker,
    command_output_tail_start,
    tail_command_output,
)

from ._entry import ToolCallEntry, is_subagent_tool_call
from .slow import format_long_duration

_REPORT_SUBDIR = "tool_call_reports"
_REPORT_KEEP_COUNT = 50
_MAX_TRANSCRIPT_BYTES = 16 * 1024 * 1024
_MAX_RECOVERED_OUTPUT_CHARS = 64 * 1024
_RECOVERED_OUTPUT_SEPARATOR = "\n\n---\n\n"

_OUTPUT_KEYS = (
    "exit_code",
    "stderr_preview",
    "stdout_preview",
    "output_preview",
    "content_preview",
    "result_preview",
    "preview",
)
_COMMAND_OUTPUT_PREVIEW_KEYS = frozenset(
    {"stderr_preview", "stdout_preview", "output_preview"}
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
_HEAD_TRUNCATION_MARKER_RE = re.compile(
    r"\.\.\.\[truncated \d+ chars\]\s*$",
    re.IGNORECASE,
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


@dataclass
class _RecoveredOutputTail:
    """Incrementally retain only the useful tail of recovered result text."""

    text: str = ""
    omitted_chars: int = 0
    omitted_lines: int = 0
    omission_is_line_aligned: bool = False

    def append(self, value: str) -> None:
        normalized = value.replace("\r\n", "\n").replace("\r", "\n")
        combined = (
            f"{self.text}{_RECOVERED_OUTPUT_SEPARATOR}{normalized}"
            if self.text
            else normalized
        )
        retain_from = command_output_tail_start(
            combined,
            _MAX_RECOVERED_OUTPUT_CHARS,
            COMMAND_OUTPUT_MIN_TAIL_LINES,
        )
        if retain_from > 0:
            omitted = combined[:retain_from]
            self.omitted_chars += retain_from
            self.omitted_lines += omitted.count("\n")
            self.omission_is_line_aligned = omitted.endswith("\n")
            combined = combined[retain_from:]
        self.text = combined

    def render(self) -> str:
        if self.omitted_chars == 0:
            return self.text
        omitted_lines = self.omitted_lines if self.omission_is_line_aligned else None
        marker = command_output_omission_marker(
            self.omitted_chars,
            omitted_lines,
        )
        return f"{marker}\n{self.text}"


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
    subagent_lines = _subagent_lines(entry)
    if subagent_lines:
        lines.extend(
            (
                "## Subagent",
                "",
                *subagent_lines,
                "",
            )
        )
    if _include_error_section(entry):
        lines.extend(
            (
                "## Error",
                "",
                *_error_lines(entry),
                "",
            )
        )
    if not _is_subagent_entry(entry):
        lines.extend(
            [
                "## Recorded Output",
                "",
                *_recorded_output_lines(entry),
                "",
            ]
        )
    lines.extend(
        [
            _full_output_heading(entry),
            "",
            *_full_output_lines(entry, transcript_recovery),
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
        transcript_recovery = (
            None
            if _has_captured_subagent_output(spec.entry)
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

    recovered = _RecoveredOutputTail()
    seen: set[str] = set()
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
                        recovered.append(text)
    except OSError:
        return _TranscriptRecovery(None, "Not recovered: transcript read failed.")

    if not recovered.text:
        return _TranscriptRecovery(
            None,
            "Not recovered: no matching result text found in transcript.",
        )

    if recovered.omitted_chars:
        return _TranscriptRecovery(
            recovered.render(),
            "Recovered from transcript; output from the beginning was omitted "
            "while the tail was preserved (64 KiB soft cap).",
        )
    return _TranscriptRecovery(recovered.text, "Recovered from transcript.")


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


def _subagent_lines(entry: ToolCallEntry) -> list[str]:
    if not _is_subagent_entry(entry):
        return []
    summary = entry.tool_response_summary
    if not _has_subagent_metadata(summary):
        return []

    identity_parts: list[str] = []
    agent_type = _summary_string(summary, "agent_type")
    if agent_type is None:
        agent_type = _input_string(entry, "subagent_type")
    if agent_type:
        identity_parts.append(f"**Type**: {agent_type}")
    model = _summary_string(summary, "resolved_model")
    if model:
        identity_parts.append(f"**Model**: {model}")
    status = _summary_string(summary, "agent_status")
    if status:
        identity_parts.append(f"**Status**: {status}")

    effort_parts: list[str] = []
    duration_ms = _summary_int(summary, "total_duration_ms")
    if duration_ms is not None:
        effort_parts.append(f"**Duration**: {format_long_duration(duration_ms)}")
    tokens = _summary_int(summary, "total_tokens")
    if tokens is not None:
        effort_parts.append(f"**Tokens**: {tokens:,}")
    tool_uses = _summary_int(summary, "total_tool_use_count")
    if tool_uses is not None:
        effort_parts.append(f"**Tool uses**: {tool_uses:,}")

    lines: list[str] = []
    if identity_parts:
        lines.append("- " + " | ".join(identity_parts))
    if effort_parts:
        lines.append("- " + " | ".join(effort_parts))

    tool_stats = _subagent_tool_stats_text(summary.get("tool_stats"))
    if tool_stats:
        lines.append(f"- **Tool stats**: {tool_stats}")
    return lines


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
    head_truncated = False
    tail_truncated = False
    other_truncated = False
    for key in _OUTPUT_KEYS:
        if key not in entry.tool_response_summary:
            continue
        value = entry.tool_response_summary[key]
        if value in (None, ""):
            continue
        text = value if isinstance(value, str) else _json_dumps(value)
        field_head_truncated = _looks_head_truncated(text)
        if (
            key in _COMMAND_OUTPUT_PREVIEW_KEYS
            and isinstance(value, str)
            and not field_head_truncated
        ):
            text = tail_command_output(text, _MAX_RECOVERED_OUTPUT_CHARS)
        head_truncated = head_truncated or field_head_truncated
        tail_truncated = tail_truncated or _looks_tail_truncated(text)
        other_truncated = other_truncated or (
            _looks_truncated(text)
            and not field_head_truncated
            and not _looks_tail_truncated(text)
        )
        lines.extend((f"### {key}", "", _fenced(text, "text"), ""))

    if not lines:
        return ["No recorded output summary fields were available."]
    if head_truncated:
        lines.append(
            "Note: one or more recorded fields were truncated at the end by "
            "the tool-call recorder. Their missing tails cannot be recovered "
            "without a transcript."
        )
    if tail_truncated:
        lines.append(
            "Note: one or more recorded command-output fields omit content "
            "from the beginning and preserve the captured tail."
        )
    if other_truncated:
        lines.append(
            "Note: one or more recorded fields include truncation markers from "
            "the tool-call recorder."
        )
    return lines


def _full_output_heading(entry: ToolCallEntry) -> str:
    if _is_subagent_entry(entry):
        return "## Full Output"
    return "## Full Output (transcript)"


def _full_output_lines(
    entry: ToolCallEntry,
    recovery: _TranscriptRecovery | None,
) -> list[str]:
    if _is_subagent_entry(entry):
        content = _subagent_content_full(entry)
        if content:
            note = "Subagent final message captured from the tool result."
            if _looks_truncated(content):
                note = f"{note} It includes the recorder's truncation marker."
            return [note, "", _fenced(content, "text")]
    return _transcript_lines(recovery)


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


def _looks_head_truncated(value: str) -> bool:
    return _HEAD_TRUNCATION_MARKER_RE.search(value) is not None


def _looks_tail_truncated(value: str) -> bool:
    first_line, _, _ = value.partition("\n")
    return first_line.startswith("...[truncated ") and first_line.endswith(
        " from the beginning]"
    )


def _is_subagent_entry(entry: ToolCallEntry) -> bool:
    return is_subagent_tool_call(entry.tool_name, entry.tool_response_summary)


def _has_captured_subagent_output(entry: ToolCallEntry) -> bool:
    return _is_subagent_entry(entry) and _subagent_content_full(entry) is not None


def _subagent_content_full(entry: ToolCallEntry) -> str | None:
    value = entry.tool_response_summary.get("content_full")
    return value if isinstance(value, str) and value else None


def _has_subagent_metadata(summary: Mapping[str, Any]) -> bool:
    return any(
        key in summary
        for key in (
            "agent_type",
            "agent_status",
            "resolved_model",
            "total_duration_ms",
            "total_tokens",
            "total_tool_use_count",
            "tool_stats",
        )
    )


def _summary_string(summary: Mapping[str, Any], key: str) -> str | None:
    value = summary.get(key)
    return value if isinstance(value, str) and value else None


def _input_string(entry: ToolCallEntry, key: str) -> str | None:
    value = entry.tool_input_summary.get(key)
    return value if isinstance(value, str) and value else None


def _summary_int(summary: Mapping[str, Any], key: str) -> int | None:
    value = summary.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _subagent_tool_stats_text(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    pieces: list[str] = []
    for key, singular, plural in (
        ("read_count", "read", "reads"),
        ("search_count", "search", "searches"),
        ("bash_count", "bash", "bash"),
        ("edit_count", "edit", "edits"),
    ):
        count = _stat_int(value, key)
        if count is not None:
            pieces.append(f"{count:,} {_plural(count, singular, plural)}")

    lines_added = _stat_int(value, "lines_added")
    lines_removed = _stat_int(value, "lines_removed")
    if lines_added is not None or lines_removed is not None:
        pieces.append(f"(+{lines_added or 0:,} / -{lines_removed or 0:,} lines)")
    return " | ".join(pieces)


def _stat_int(summary: Mapping[str, Any], key: str) -> int | None:
    value = summary.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


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
