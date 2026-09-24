"""Command Line panel history store.

Persists ``:`` Command Line submissions to
``<sase_home>/command_line_history.json`` with an ``fcntl`` lock and atomic
writes, following :mod:`sase.history.prompt_store`. Entries carry the fields
the panel needs for RECENT rows, prefix walks, and ghost text::

    {line, cwd, project, last_exit, count, last_used}

The store is capped at 1,000 entries by LRU. Loading and writes are plain
blocking calls; the TUI adapter in
:mod:`sase.ace.tui.command_line.history` runs them off-thread.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.core.paths import sase_home
from sase.core.time import generate_timestamp

_COMMAND_LINE_HISTORY_FILENAME = "command_line_history.json"
_COMMAND_LINE_HISTORY_LOCK_FILENAME = "command_line_history.lock"

#: Maximum entries kept; eviction is least-recently-used by ``last_used``.
COMMAND_LINE_HISTORY_LIMIT = 1000

_history_file_override: Path | None = None


@dataclass
class CommandLineHistoryEntry:
    """One recorded Command Line submission."""

    line: str
    cwd: str = ""
    project: str | None = None
    last_exit: int | None = None
    count: int = 1
    last_used: str = ""


def set_command_line_history_file(path: Path | None) -> None:
    """Override the store path (tests only)."""
    global _history_file_override
    _history_file_override = path


def command_line_history_file() -> Path:
    """Return the on-disk Command Line history path."""
    if _history_file_override is not None:
        return _history_file_override
    return sase_home() / _COMMAND_LINE_HISTORY_FILENAME


def _command_line_history_lock_file() -> Path:
    """Return the lock file path for Command Line history mutations."""
    return command_line_history_file().with_name(_COMMAND_LINE_HISTORY_LOCK_FILENAME)


@contextmanager
def locked_command_line_history():  # type: ignore[no-untyped-def]
    """Hold an exclusive lock for history read/modify/write cycles."""
    lock_file = _command_line_history_lock_file()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_file, "a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _entry_from_json(value: Any) -> CommandLineHistoryEntry | None:
    if not isinstance(value, dict):
        return None
    line = value.get("line")
    if not isinstance(line, str) or not line.strip():
        return None
    cwd = value.get("cwd", "")
    project = value.get("project")
    last_exit = value.get("last_exit")
    count = value.get("count", 1)
    last_used = value.get("last_used", "")
    return CommandLineHistoryEntry(
        line=line,
        cwd=cwd if isinstance(cwd, str) else "",
        project=project if isinstance(project, str) else None,
        last_exit=last_exit if isinstance(last_exit, int) else None,
        count=count if isinstance(count, int) and count > 0 else 1,
        last_used=last_used if isinstance(last_used, str) else "",
    )


def _entry_to_json(entry: CommandLineHistoryEntry) -> dict[str, Any]:
    return {
        "line": entry.line,
        "cwd": entry.cwd,
        "project": entry.project,
        "last_exit": entry.last_exit,
        "count": entry.count,
        "last_used": entry.last_used,
    }


def load_command_line_history() -> list[CommandLineHistoryEntry]:
    """Load history newest-first; corrupt files read as empty."""
    path = command_line_history_file()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        data = json.loads(raw)
    except ValueError:
        return []
    entries = data.get("entries", []) if isinstance(data, dict) else []
    if not isinstance(entries, list):
        return []
    parsed = [
        entry for entry in (_entry_from_json(v) for v in entries) if entry is not None
    ]
    parsed.sort(key=lambda e: e.last_used, reverse=True)
    return parsed


def save_command_line_history(entries: list[CommandLineHistoryEntry]) -> bool:
    """Atomically save history, enforcing the LRU cap. Never raises."""
    path = command_line_history_file()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        capped = sorted(entries, key=lambda e: e.last_used, reverse=True)[
            :COMMAND_LINE_HISTORY_LIMIT
        ]
        data = {"entries": [_entry_to_json(e) for e in capped]}
        fd, temp_name = tempfile.mkstemp(
            prefix=".command_line_history.",
            suffix=f".{os.getpid()}.tmp",
            dir=path.parent,
            text=True,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        except OSError:
            try:
                temp_path.unlink()
            except OSError:
                pass
            return False
        return True
    except OSError:
        return False


def record_command_line(
    line: str,
    *,
    cwd: str = "",
    project: str | None = None,
    exit_code: int | None = None,
) -> CommandLineHistoryEntry | None:
    """Record one submission; repeat lines bump ``count`` instead of duplicating.

    Returns the recorded entry, or ``None`` for a blank line. Callers must
    hold :func:`locked_command_line_history` across the read/modify/write.
    """
    text = line.strip()
    if not text:
        return None
    now = generate_timestamp()
    entries = load_command_line_history()
    for entry in entries:
        if entry.line == text:
            entry.count += 1
            entry.last_used = now
            entry.cwd = cwd or entry.cwd
            entry.project = project if project is not None else entry.project
            if exit_code is not None:
                entry.last_exit = exit_code
            save_command_line_history(entries)
            return entry
    recorded = CommandLineHistoryEntry(
        line=text,
        cwd=cwd,
        project=project,
        last_exit=exit_code,
        count=1,
        last_used=now,
    )
    entries.append(recorded)
    save_command_line_history(entries)
    return recorded


def prefix_matches(
    entries: list[CommandLineHistoryEntry],
    prefix: str,
    *,
    cwd: str | None = None,
) -> list[CommandLineHistoryEntry]:
    """Return entries starting with *prefix*, newest-first.

    Same-cwd matches rank before other-cwd matches; recency breaks ties.
    """
    needle = prefix.strip()
    if not needle:
        return []
    same: list[CommandLineHistoryEntry] = []
    other: list[CommandLineHistoryEntry] = []
    for entry in entries:
        if not entry.line.startswith(needle):
            continue
        if cwd is not None and entry.cwd and entry.cwd == cwd:
            same.append(entry)
        else:
            other.append(entry)
    return same + other


def ghost_for_prefix(
    entries: list[CommandLineHistoryEntry],
    prefix: str,
    *,
    cwd: str | None = None,
) -> str:
    """Return ghost-text remainder for the best prefix match, else ``""``."""
    matches = prefix_matches(entries, prefix, cwd=cwd)
    if not matches:
        return ""
    best = matches[0].line
    needle = prefix.strip()
    if best == needle:
        return ""
    return best[len(needle) :]


__all__ = [
    "COMMAND_LINE_HISTORY_LIMIT",
    "CommandLineHistoryEntry",
    "command_line_history_file",
    "ghost_for_prefix",
    "load_command_line_history",
    "locked_command_line_history",
    "prefix_matches",
    "record_command_line",
    "save_command_line_history",
    "set_command_line_history_file",
]
