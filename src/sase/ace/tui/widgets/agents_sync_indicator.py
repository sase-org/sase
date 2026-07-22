"""Pure top-bar projection of agents-repository synchronization status."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.agents_sync.models import ProjectSyncStatus, SyncStatusSnapshot

from ..agents_sync_format import (
    agents_sync_status_detail,
    agents_sync_status_needs_attention,
)

_AGENTS_SYNC_ACCENT = "#5FD787"
_AGENTS_SYNC_GLYPH = "⇅"


class AgentsSyncIndicator(Static):
    """Actionable badge for enabled agents repositories needing attention."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(self._build_content(()), **kwargs)
        self._pending: tuple[ProjectSyncStatus, ...] = ()
        self.tooltip = self._build_tooltip(())

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    @property
    def pending_projects(self) -> tuple[ProjectSyncStatus, ...]:
        return self._pending

    def set_status(self, snapshot: SyncStatusSnapshot) -> None:
        """Project an immutable snapshot, updating only when display state changes."""
        pending = tuple(
            sorted(
                (
                    status
                    for status in snapshot.projects
                    if agents_sync_status_needs_attention(status)
                ),
                key=lambda status: status.project_key,
            )
        )
        if pending == self._pending:
            return
        self._pending = pending
        self.tooltip = self._build_tooltip(pending)
        if self.is_mounted:
            self.update(self._build_content(pending))

    async def on_click(self) -> None:
        """Submit the tracked agents-repository synchronization action."""
        await self.app.run_action("sync_agents")

    @staticmethod
    def _build_content(statuses: tuple[ProjectSyncStatus, ...]) -> Text:
        text = Text()
        if statuses:
            text.append(
                f" {_AGENTS_SYNC_GLYPH} {len(statuses)} ",
                style=f"bold #1a1a1a on {_AGENTS_SYNC_ACCENT}",
            )
        return text

    @staticmethod
    def _build_tooltip(statuses: tuple[ProjectSyncStatus, ...]) -> str:
        if not statuses:
            return "All enabled agents repositories are synchronized"
        lines = ["Agents repositories need synchronization:"]
        lines.extend(
            f"{status.project}: {agents_sync_status_detail(status)}"
            for status in statuses
        )
        lines.append(
            "Click to synchronize agents repositories. Press ,U for the "
            "comprehensive update."
        )
        return "\n".join(lines)


__all__ = ["AgentsSyncIndicator"]
