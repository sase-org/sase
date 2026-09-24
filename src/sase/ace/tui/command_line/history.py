"""TUI adapter over the Command Line history store.

Loading and writes happen off-thread (callers use ``asyncio.to_thread`` or a
worker); this module holds the in-memory copy the panel walks with ``↑``/``↓``
and renders as ghost text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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
