"""Log-source registry — the backend↔UI contract for the Logs tab.

A single source of truth for *what logs exist* and *how to read them*,
decoupled from *how the panel renders them*. The canonical paths come from
:mod:`sase.logs` so there is exactly one definition of each file's location.

Tail reading reuses the efficient ``read_tail_seek`` seek-from-end helper in
:mod:`sase.axe.state` (``O(tail)``, not ``O(file)``), so the panel stays
responsive even on multi-megabyte logs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from sase.axe.state import read_tail_seek
from sase.logs import (
    events_log_path,
    launch_failures_log_path,
    runs_log_path,
    tui_agent_loads_jsonl_path,
    tui_external_tools_jsonl_path,
    tui_git_ops_jsonl_path,
    tui_launch_timing_jsonl_path,
    tui_log_path,
    tui_stalls_jsonl_path,
    tui_toasts_jsonl_path,
)

RenderMode = Literal["text", "jsonl", "toasts"]

# Per-record fields shown in the human-readable header rather than as trailing
# ``key=value`` pairs, plus noisy fields omitted from the compact line.
_JSONL_HEAD_KEYS = ("timestamp", "kind", "event")
_JSONL_OMIT_KEYS = frozenset({*_JSONL_HEAD_KEYS, "traceback"})
_JSONL_VALUE_LIMIT = 120


@dataclass(frozen=True)
class LogSource:
    """A single readable log file surfaced by the Logs tab."""

    id: str
    title: str
    description: str
    path: Path
    render: RenderMode

    def exists(self) -> bool:
        """Whether the file is present and non-empty."""
        try:
            return self.path.is_file() and self.path.stat().st_size > 0
        except OSError:
            return False

    def line_count(self) -> int:
        """Total number of lines in the file (0 if missing)."""
        if not self.path.exists():
            return 0
        try:
            with open(self.path, "rb") as f:
                return sum(1 for _ in f)
        except OSError:
            return 0

    def read_tail(self, max_lines: int) -> str:
        """Return up to *max_lines* trailing raw lines (``""`` if missing)."""
        if not self.path.exists():
            return ""
        return read_tail_seek(self.path, max_lines)

    def read_rendered_tail(self, max_lines: int) -> str:
        """Return the tail ready for display.

        For ``jsonl`` sources each record is pretty-rendered to one compact,
        readable line; ``text`` sources are returned verbatim. Empty/missing
        files render as ``""`` (the panel supplies the empty-state copy).
        """
        raw = self.read_tail(max_lines)
        if not raw:
            return ""
        if self.render in {"jsonl", "toasts"}:
            return _render_jsonl_tail(raw)
        return raw


def log_sources() -> list[LogSource]:
    """Build the ordered registry against the current canonical paths.

    Rebuilt per call so test path overrides (and any future relocation) are
    honoured. ``launch_failures`` is first so it is the panel's default.
    """
    return [
        LogSource(
            id="launch_failures",
            title="Launch & Fan-out Failures",
            description="Every launch/fan-out/workflow/chop failure, with traceback",
            path=launch_failures_log_path(),
            render="text",
        ),
        LogSource(
            id="tui",
            title="TUI Diagnostics",
            description="Catch-all warnings and errors from the ace TUI",
            path=tui_log_path(),
            render="text",
        ),
        LogSource(
            id="tui_toasts",
            title="TUI Toasts",
            description="Toast notifications shown in this and previous TUI sessions",
            path=tui_toasts_jsonl_path(),
            render="toasts",
        ),
        LogSource(
            id="tui_stalls",
            title="TUI Stalls",
            description="Event-loop stall stack captures",
            path=tui_stalls_jsonl_path(),
            render="jsonl",
        ),
        LogSource(
            id="tui_agent_loads",
            title="Agent Load Timing",
            description="Slow Agents-tab loader and cleanup stage timings",
            path=tui_agent_loads_jsonl_path(),
            render="jsonl",
        ),
        LogSource(
            id="tui_external_tools",
            title="TUI External Tools",
            description="Intentional editor/viewer terminal handoff waits",
            path=tui_external_tools_jsonl_path(),
            render="jsonl",
        ),
        LogSource(
            id="tui_git_ops",
            title="TUI Git Operations",
            description="Slow, failed, and push/fetch git timing records",
            path=tui_git_ops_jsonl_path(),
            render="jsonl",
        ),
        LogSource(
            id="tui_launch_timing",
            title="Launch Timing",
            description="Agent launch timing summaries with per-stage durations",
            path=tui_launch_timing_jsonl_path(),
            render="jsonl",
        ),
        LogSource(
            id="runs",
            title="Agent Runs",
            description="Recent agent runs, for context",
            path=runs_log_path(),
            render="jsonl",
        ),
        LogSource(
            id="events",
            title="Events",
            description="Recent commits, revives, and other events",
            path=events_log_path(),
            render="jsonl",
        ),
    ]


# Convenience snapshot against the default (non-overridden) paths. Prefer
# :func:`log_sources` where path overrides may be in effect (e.g. tests).
LOG_SOURCES: list[LogSource] = log_sources()


def _render_jsonl_tail(raw: str) -> str:
    """Pretty-render JSONL text as one compact line per record."""
    lines: list[str] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            lines.append(line)  # surface malformed lines rather than hide them
            continue
        if isinstance(record, dict):
            lines.append(_render_jsonl_record(record))
        else:
            lines.append(str(record))
    return "\n".join(lines)


def _render_jsonl_record(record: dict[str, Any]) -> str:
    """Render one JSONL record dict as a compact, readable line."""
    head: list[str] = []
    for key in _JSONL_HEAD_KEYS:
        value = record.get(key)
        if value is not None and value != "":
            head.append(str(value))
    tail: list[str] = []
    for key, value in record.items():
        if key in _JSONL_OMIT_KEYS:
            continue
        text = str(value).replace("\n", " ")
        if len(text) > _JSONL_VALUE_LIMIT:
            text = text[: _JSONL_VALUE_LIMIT - 3] + "..."
        tail.append(f"{key}={text}")
    return "  ".join(head + tail)
