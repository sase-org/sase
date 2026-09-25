"""TUI adapter over the Command Line history store.

Loading and writes happen off-thread (callers use ``asyncio.to_thread`` or a
worker); this module holds the in-memory copy the panel walks with ``↑``/``↓``
and renders as ghost text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sase.core.time import generate_timestamp
from sase.history.command_line import (
    CommandLineHistoryEntry,
    ghost_for_prefix,
    load_command_line_history,
    locked_command_line_history,
    prefix_matches,
    record_command_line,
)


@dataclass
class CommandLineHistory:
    """In-memory history copy with a prefix-walk cursor."""

    entries: list[CommandLineHistoryEntry] = field(default_factory=list)
    cursor: int | None = None
    anchor: str = ""

    def refresh(self) -> None:
        """Reload entries from disk (call off-thread)."""
        self.entries = load_command_line_history()
        self.cursor = None

    def record(
        self,
        line: str,
        *,
        cwd: str = "",
        project: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Record one submission under the store lock (call off-thread)."""
        with locked_command_line_history():
            record_command_line(line, cwd=cwd, project=project, exit_code=exit_code)
        self.entries = load_command_line_history()
        self.cursor = None

    def remember(
        self,
        line: str,
        *,
        cwd: str = "",
        project: str | None = None,
        exit_code: int | None = None,
    ) -> None:
        """Upsert *line* in memory without touching disk (call on the loop).

        Mirrors the store's dedup: a repeat line bumps ``count`` and moves to
        the front instead of duplicating, so ghost text and ``RECENT`` see a
        submission at once while the store write lands off-thread.
        """
        text = line.strip()
        if not text:
            return
        now = generate_timestamp()
        for entry in self.entries:
            if entry.line == text:
                entry.count += 1
                entry.last_used = now
                entry.cwd = cwd or entry.cwd
                entry.project = project if project is not None else entry.project
                if exit_code is not None:
                    entry.last_exit = exit_code
                self.entries.remove(entry)
                self.entries.insert(0, entry)
                self.cursor = None
                return
        self.entries.insert(
            0,
            CommandLineHistoryEntry(
                line=text,
                cwd=cwd,
                project=project,
                last_exit=exit_code,
                last_used=now,
            ),
        )
        self.cursor = None

    def walk(self, typed: str, *, direction: int, cwd: str | None = None) -> str | None:
        """Step the ``↑``/``↓`` prefix walk; ``None`` restores the typed text."""
        if self.anchor != typed:
            self.anchor = typed
            self.cursor = None
        matches = prefix_matches(self.entries, typed, cwd=cwd)
        if not matches:
            self.cursor = None
            return None
        if self.cursor is None:
            index = 0 if direction > 0 else len(matches) - 1
        else:
            index = self.cursor + direction
            if index < 0 or index >= len(matches):
                self.cursor = None
                return None
        self.cursor = index
        return matches[index].line

    def ghost(self, typed: str, *, cwd: str | None = None) -> str:
        """Return ghost-text remainder for *typed*, else ``""``."""
        return ghost_for_prefix(self.entries, typed, cwd=cwd)

    def recent(self, *, limit: int = 5) -> list[CommandLineHistoryEntry]:
        """Return the most recent entries for the empty-state popup."""
        return list(self.entries[: max(0, limit)])


__all__ = ["CommandLineHistory"]
