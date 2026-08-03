"""Toast-history rendering helpers for the Logs pane."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from rich.text import Text

from sase.core.time import format_local, parse_local
from sase.logs import ToastRecord

_CYAN = "#87D7FF"
_GOLD = "#FFD700"
_INFO_GLYPH = "·"
_WARNING_GLYPH = "⚠"
_ERROR_GLYPH = "✖"
_MESSAGE_INDENT = " " * 12


@dataclass(frozen=True)
class _CollapsedToast:
    record: ToastRecord
    count: int


def render_toast_detail_body(
    records: list[ToastRecord],
    current_session_id: str,
) -> Text:
    """Render toast records grouped by session, newest first."""
    text = Text()
    for idx, group in enumerate(_session_groups(records)):
        if idx:
            text.append("\n")
        header = _session_header(group[0], current_session_id)
        text.append_text(header)
        text.append("\n")
        for collapsed in _collapse_consecutive(group):
            _append_toast_row(text, collapsed)
    return text


def _session_groups(records: list[ToastRecord]) -> list[list[ToastRecord]]:
    indexed = list(enumerate(records))
    newest_first = sorted(
        indexed,
        key=lambda item: (_timestamp_key(item[1].timestamp), item[0]),
        reverse=True,
    )
    grouped: defaultdict[str, list[ToastRecord]] = defaultdict(list)
    order: list[str] = []
    for _idx, record in newest_first:
        if record.session_id not in grouped:
            order.append(record.session_id)
        grouped[record.session_id].append(record)
    return [grouped[session_id] for session_id in order]


def _collapse_consecutive(records: list[ToastRecord]) -> list[_CollapsedToast]:
    collapsed: list[_CollapsedToast] = []
    for record in records:
        key = _dedupe_key(record)
        if collapsed and _dedupe_key(collapsed[-1].record) == key:
            previous = collapsed[-1]
            collapsed[-1] = _CollapsedToast(
                record=previous.record,
                count=previous.count + 1,
            )
            continue
        collapsed.append(_CollapsedToast(record=record, count=1))
    return collapsed


def _append_toast_row(text: Text, collapsed: _CollapsedToast) -> None:
    record = collapsed.record
    severity_style = _severity_style(record.severity)
    text.append(" ")
    text.append(_toast_timestamp(record), style=_CYAN)
    text.append("  ")
    text.append(_severity_glyph(record.severity), style=severity_style or "dim")
    text.append("  ")

    lines = record.message.splitlines() or [""]
    if record.title:
        title_style = f"bold {severity_style}" if severity_style else "bold"
        text.append(record.title, style=title_style)
        text.append(" · ", style="dim")
    text.append(lines[0], style=severity_style)
    if collapsed.count > 1:
        text.append(f"  ×{collapsed.count}", style="dim")
    text.append("\n")
    for line in lines[1:]:
        text.append(_MESSAGE_INDENT)
        text.append(line, style=severity_style)
        text.append("\n")


def _session_header(record: ToastRecord, current_session_id: str) -> Text:
    current = record.session_id == current_session_id
    label = "This session" if current else "Session"
    header_style = f"bold {_GOLD}" if current else "dim"
    text = Text(style=header_style)
    text.append("━━ ")
    text.append(label)
    text.append(" · started ")
    text.append(_format_session_started_at(record.session_started_at))
    text.append(f" · pid {record.pid} ")
    text.append("━" * 24)
    return text


def _format_session_started_at(value: str) -> str:
    return format_local(value, "%Y-%m-%d %H:%M %Z", default=value)


def _toast_timestamp(record: ToastRecord) -> str:
    timestamp = parse_local(record.timestamp)
    session_start = parse_local(record.session_started_at)
    if timestamp is None:
        return record.timestamp
    if session_start is not None and timestamp.date() != session_start.date():
        return timestamp.strftime("%m-%d %H:%M:%S")
    return timestamp.strftime("%H:%M:%S")


def _timestamp_key(value: str) -> datetime:
    parsed = _parse_timestamp(value)
    if parsed is None:
        return datetime.min.replace(tzinfo=UTC)
    return parsed


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _dedupe_key(record: ToastRecord) -> tuple[str, str, str]:
    return (record.severity, record.title, record.message)


def _severity_glyph(severity: str) -> str:
    if severity == "warning":
        return _WARNING_GLYPH
    if severity == "error":
        return _ERROR_GLYPH
    return _INFO_GLYPH


def _severity_style(severity: str) -> str | None:
    if severity == "warning":
        return _GOLD
    if severity == "error":
        return "red"
    return None


__all__ = ["render_toast_detail_body"]
