"""Prepared detail and responsive rendering for slow tool-call rows."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import IntEnum
from typing import Any
from urllib.parse import urlsplit

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.padding import Padding
from rich.table import Table
from rich.text import Text

from sase.ace.tui.tools import ToolCallEntry
from sase.ace.tui.tools._entry import is_subagent_tool_call
from sase.ace.tui.tools.slow import SlowToolCall, format_long_duration

from ...models.fold_scale import FoldScale, fold_scale_position
from ...models.fold_state import FoldLevel
from .._tool_detail_language import (
    TOOL_DETAIL_GUTTER,
    TOOL_DETAIL_WRAP_INDENT,
    append_tool_detail_line,
    append_tool_multiline_detail,
)
from ._agent_context_common import format_local_hhmmss

_PRIMARY_INPUT_KEYS = (
    "file_path",
    "path",
    "url",
    "query",
    "pattern",
    "command",
    "prompt",
)
_PREVIEW_KEYS = (
    "stdout_preview",
    "stderr_preview",
    "output_preview",
    "content_preview",
    "result_preview",
    "preview",
)
_INHERITED_MORE_RE = re.compile(r"\.\.\.\[\d+\s+more\]\s*$")
_DETAIL_TARGET_STYLE = "#D7D7AF"


class SlowToolDetail(IntEnum):
    """Positional detail tiers owned by the slow-tool section."""

    COMPACT = 1
    DETAIL = 2
    FULL = 3


def slow_tool_detail_level(level: FoldLevel, scale: FoldScale) -> SlowToolDetail:
    """Resolve a sase-agent fold level to the positional slow-tool detail tier."""
    position, size = fold_scale_position(level, scale)
    if position == 1:
        return SlowToolDetail.COMPACT
    if position == size:
        return SlowToolDetail.FULL
    return SlowToolDetail.DETAIL


def digest_target(entry: ToolCallEntry, width: int = 44) -> str:
    """Return a short, marker-free target digest for one compact row."""
    summary = entry.tool_input_summary
    value = _path_digest(summary, "file_path") or _path_digest(summary, "path")
    if value is None:
        value = _url_digest(summary.get("url"))
    if value is None:
        value = _summary_string(summary, "pattern")
    if value is None:
        value = _summary_string(summary, "query")
    if value is None:
        value = _summary_string(summary, "description")
    if value is None:
        value = _command_head(summary.get("command"))
    if value is None:
        value = _summary_string(summary, "subagent_type")
    if value is None:
        value = _INHERITED_MORE_RE.sub("", entry.compact_target).rstrip()
    return _elide_digest(_collapse_whitespace(value), width)


def _path_digest(summary: Mapping[str, Any], key: str) -> str | None:
    value = _summary_string(summary, key)
    if value is None:
        return None
    parts = tuple(part for part in re.split(r"[\\/]+", value) if part)
    if not parts:
        return value
    digest = "/".join(parts[-2:])
    return f"…/{digest}" if len(parts) > 2 else digest


def _url_digest(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = urlsplit(value)
    if not parsed.hostname:
        return value
    first_segment = next(
        (segment for segment in parsed.path.split("/") if segment),
        None,
    )
    return f"{parsed.hostname}/{first_segment}" if first_segment else parsed.hostname


def _command_head(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value.replace("\r\n", "\n").replace("\r", "\n")
    return next((line for line in normalized.splitlines() if line.strip()), "")


def _collapse_whitespace(value: str) -> str:
    return " ".join(value.split())


def _elide_digest(value: str, width: int) -> str:
    if width <= 0:
        return ""
    if cell_len(value) <= width:
        return value
    if width == 1:
        return "…"

    raw_prefix = _cell_prefix(value, width - 1)
    prefix = raw_prefix.rstrip()
    if raw_prefix and not (raw_prefix[-1].isspace() or raw_prefix.endswith("/")):
        boundary = max(prefix.rfind(" "), prefix.rfind("/"))
        if boundary >= max(1, len(prefix) // 2):
            prefix = prefix[:boundary].rstrip()
    return f"{prefix}…"


def _cell_prefix(value: str, width: int) -> str:
    cells = 0
    output: list[str] = []
    for char in value:
        char_width = cell_len(char)
        if cells + char_width > width:
            break
        output.append(char)
        cells += char_width
    return "".join(output)


@dataclass(frozen=True)
class _SlowToolCallDetail:
    """Prepared, disk-free detail facts for one selected slow call."""

    primary_label: str | None
    primary_value: str | None
    timing_label: str
    timing_value: str
    error: str | None
    preview: str | None
    preview_style: str
    subagent: str | None
    share: str

    @property
    def has_hidden_primary(self) -> bool:
        """Return whether compact mode hides a primary command or target."""
        return self.primary_value is not None

    def append_logical(self, text: Text, level: SlowToolDetail) -> None:
        """Append the unwrapped logical detail block for this row."""
        if level < SlowToolDetail.DETAIL:
            return
        if self.primary_label is not None and self.primary_value is not None:
            append_tool_multiline_detail(
                text,
                self.primary_label,
                self.primary_value,
                style=_DETAIL_TARGET_STYLE,
            )
        append_tool_detail_line(
            text,
            self.timing_label,
            self.timing_value,
            style="dim",
        )
        if self.error:
            append_tool_detail_line(text, "error", self.error, style="bold red")
        if level >= SlowToolDetail.FULL:
            if self.preview:
                append_tool_detail_line(
                    text,
                    "output",
                    self.preview,
                    style=self.preview_style,
                )
            if self.subagent:
                append_tool_detail_line(
                    text,
                    "subagent",
                    self.subagent,
                    style="dim",
                )
            append_tool_detail_line(text, "", self.share, style="dim italic")


def prepare_slow_tool_call_details(
    calls: Sequence[SlowToolCall],
) -> tuple[_SlowToolCallDetail, ...]:
    """Prepare aligned detail models and relative slow-time shares."""
    total_duration = sum(call.effective_duration_ms for call in calls)
    ranked_indices = sorted(
        range(len(calls)),
        key=lambda index: (-calls[index].effective_duration_ms, index),
    )
    ranks = {
        call_index: rank for rank, call_index in enumerate(ranked_indices, start=1)
    }
    return tuple(
        _prepare_slow_tool_call_detail(
            call,
            rank=ranks[index],
            total_duration=total_duration,
        )
        for index, call in enumerate(calls)
    )


def _prepare_slow_tool_call_detail(
    call: SlowToolCall,
    *,
    rank: int,
    total_duration: int,
) -> _SlowToolCallDetail:
    entry = call.entry
    primary = _primary_target(entry)
    timing_label, timing_value = _timing_line(call)
    error = _entry_error(entry)
    preview, preview_style = _output_preview(entry)
    share_percent = (
        int((call.effective_duration_ms * 100 / total_duration) + 0.5)
        if total_duration
        else 0
    )
    return _SlowToolCallDetail(
        primary_label=primary[0] if primary is not None else None,
        primary_value=primary[1] if primary is not None else None,
        timing_label=timing_label,
        timing_value=timing_value,
        error=error,
        preview=preview,
        preview_style=preview_style,
        subagent=_subagent_summary(entry),
        share=f"#{rank} slowest · {share_percent}% of slow time",
    )


def _primary_target(entry: ToolCallEntry) -> tuple[str, str] | None:
    for key in _PRIMARY_INPUT_KEYS:
        value = entry.tool_input_summary.get(key)
        if isinstance(value, str) and value:
            return key.replace("_", " "), _normalize_multiline(value)
    return None


def _timing_line(call: SlowToolCall) -> tuple[str, str]:
    start = format_local_hhmmss(call.entry.recorded_at)
    duration = format_long_duration(call.effective_duration_ms)
    if call.is_running:
        return "started", f"{start} · running for {duration}"
    if call.did_not_complete:
        return "started", f"{start} · did not complete"

    end = _completed_at(call)
    parts = [f"{start} → {format_local_hhmmss(end.isoformat())}"]
    parts.extend(_outcome_parts(call.entry))
    timeout = _timeout_fact(call.entry.tool_input_summary.get("timeout"))
    if timeout:
        parts.append(timeout)
    return "ran", " · ".join(parts)


def _completed_at(call: SlowToolCall) -> datetime:
    parsed = _parse_timestamp(call.entry.completed_at)
    if parsed is not None:
        return parsed
    return call.started_at + timedelta(milliseconds=call.effective_duration_ms)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _outcome_parts(entry: ToolCallEntry) -> list[str]:
    summary = entry.tool_response_summary
    parts: list[str] = []
    exit_code = summary.get("exit_code")
    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        parts.append(f"exit {exit_code}")
    success = summary.get("success")
    if success is False or entry.status == "failure":
        parts.append("failed")
    if summary.get("interrupted") is True or entry.status == "interrupted":
        parts.append("interrupted")
    return list(dict.fromkeys(parts))


def _timeout_fact(value: object) -> str | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        rendered = f"{value:g}"
    elif isinstance(value, str) and value.strip():
        rendered = value.strip()
    else:
        return None
    return (
        f"timeout {rendered}"
        if rendered.endswith(("s", "m", "h"))
        else f"timeout {rendered}s"
    )


def _entry_error(entry: ToolCallEntry) -> str | None:
    error = entry.error
    response_error = entry.tool_response_summary.get("error")
    if not error and isinstance(response_error, str):
        error = response_error
    return _bounded_meaningful_line(error)


def _output_preview(entry: ToolCallEntry) -> tuple[str | None, str]:
    for key in _PREVIEW_KEYS:
        value = entry.tool_response_summary.get(key)
        preview = _bounded_meaningful_line(value)
        if preview:
            return preview, "#FF8787" if key == "stderr_preview" else "dim"
    return None, "dim"


def _bounded_meaningful_line(value: object) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = _normalize_multiline(value)
    line = next((line.strip() for line in normalized.splitlines() if line.strip()), "")
    return _elide_digest(_collapse_whitespace(line), 240) if line else None


def _subagent_summary(entry: ToolCallEntry) -> str | None:
    if not is_subagent_tool_call(entry.tool_name, entry.tool_response_summary):
        return None
    response = entry.tool_response_summary
    parts: list[str] = []
    agent_type = _summary_string(response, "agent_type") or _summary_string(
        entry.tool_input_summary,
        "subagent_type",
    )
    if agent_type:
        parts.append(agent_type)
    tool_uses = _summary_int(response, "total_tool_use_count")
    if tool_uses is not None:
        parts.append(f"{tool_uses:,} {'tool use' if tool_uses == 1 else 'tool uses'}")
    tokens = _summary_int(response, "total_tokens")
    if tokens is not None:
        parts.append(f"{tokens:,} tokens")
    return " · ".join(parts) or None


def _summary_string(summary: Mapping[str, Any], key: str) -> str | None:
    value = summary.get(key)
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


def _normalize_multiline(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n")


@dataclass(frozen=True)
class SlowToolSectionRow:
    """One compact row paired with its prepared expanded facts."""

    compact_line: Text
    detail: _SlowToolCallDetail


@dataclass(slots=True)
class ResponsiveSlowToolCallsSection:
    """Slow-call section whose detail lines reflow with hanging indents."""

    heading: Text
    rows: tuple[SlowToolSectionRow, ...]
    detail_level: SlowToolDetail
    hidden_tail: Text | None = None
    overflow_tail: Text | None = None

    @property
    def logical_text(self) -> Text:
        """Return the complete unwrapped section spliced into the header."""
        text = Text(end="")
        text.append_text(self.heading)
        for row in self.rows:
            text.append_text(row.compact_line)
            row.detail.append_logical(text, self.detail_level)
        if self.hidden_tail is not None:
            text.append_text(self.hidden_tail)
        if self.overflow_tail is not None:
            text.append_text(self.overflow_tail)
        return text

    def __rich_console__(
        self,
        _console: Console,
        _options: ConsoleOptions,
    ) -> RenderResult:
        yield self.heading
        for row in self.rows:
            yield row.compact_line
            if self.detail_level >= SlowToolDetail.DETAIL:
                yield from _responsive_detail_renderables(
                    row.detail,
                    self.detail_level,
                )
        if self.hidden_tail is not None:
            yield self.hidden_tail
        if self.overflow_tail is not None:
            yield self.overflow_tail


def _responsive_detail_renderables(
    detail: _SlowToolCallDetail,
    level: SlowToolDetail,
) -> RenderResult:
    if detail.primary_label is not None and detail.primary_value is not None:
        yield Text.assemble(
            (TOOL_DETAIL_GUTTER, "dim"),
            (detail.primary_label, "dim italic"),
            "\n",
            end="",
        )
        lines = detail.primary_value.splitlines() or [detail.primary_value]
        for line in lines[:6]:
            yield Padding(
                Text(
                    line or " ",
                    style=_DETAIL_TARGET_STYLE,
                    overflow="fold",
                    no_wrap=False,
                ),
                (0, 0, 0, cell_len(TOOL_DETAIL_WRAP_INDENT)),
                expand=False,
            )
        remaining = len(lines) - 6
        if remaining > 0:
            yield Padding(
                Text(
                    f"... (+{remaining} more lines)",
                    style="dim italic",
                ),
                (0, 0, 0, cell_len(TOOL_DETAIL_WRAP_INDENT)),
                expand=False,
            )

    yield _responsive_detail_line(
        detail.timing_label,
        detail.timing_value,
        style="dim",
    )
    if detail.error:
        yield _responsive_detail_line("error", detail.error, style="bold red")
    if level >= SlowToolDetail.FULL:
        if detail.preview:
            yield _responsive_detail_line(
                "output",
                detail.preview,
                style=detail.preview_style,
            )
        if detail.subagent:
            yield _responsive_detail_line(
                "subagent",
                detail.subagent,
                style="dim",
            )
        yield _responsive_detail_line("", detail.share, style="dim italic")


def _responsive_detail_line(label: str, value: str, *, style: str) -> Table:
    content = Text(overflow="fold", no_wrap=False)
    if label:
        content.append(f"{label} ", style="dim italic")
    content.append(value, style=style)
    table = Table.grid(padding=0)
    table.add_column(width=cell_len(TOOL_DETAIL_GUTTER), no_wrap=True)
    table.add_column(overflow="fold")
    table.add_row(Text(TOOL_DETAIL_GUTTER, style="dim"), content)
    return table


__all__ = [
    "ResponsiveSlowToolCallsSection",
    "SlowToolDetail",
    "SlowToolSectionRow",
    "digest_target",
    "prepare_slow_tool_call_details",
    "slow_tool_detail_level",
]
