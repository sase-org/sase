"""Pure top-bar projection of agents-repository synchronization status."""

from __future__ import annotations

from typing import Any

from rich.text import Text
from textual.widgets import Static

from sase.agents_sync.models import (
    CapturedIncomingHood,
    ProjectSyncStatus,
    SyncStatusSnapshot,
)

from ..agents_sync_format import (
    agents_sync_status_needs_attention,
    captured_agent_hood_label,
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
        return sum(status.pending_foreign_count for status in self._pending)

    @property
    def pending_projects(self) -> tuple[ProjectSyncStatus, ...]:
        return self._pending

    @property
    def pending_updates(self) -> tuple[CapturedIncomingHood, ...]:
        """Return exactly the immutable cache items represented by the badge."""
        return tuple(
            item
            for status in self._pending
            for item in sorted(
                status.pending_updates,
                key=lambda row: (
                    row.source_username or "",
                    row.source_machine,
                    row.top_hood,
                    row.cache_id,
                ),
            )
        )

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
        """Import the currently displayed cached updates without a fetch."""
        await self.app.run_action("integrate_cached_agents")

    @staticmethod
    def _build_content(statuses: tuple[ProjectSyncStatus, ...]) -> Text:
        text = Text()
        if statuses:
            count = sum(status.pending_foreign_count for status in statuses)
            text.append(
                f" {_AGENTS_SYNC_GLYPH} {count} ",
                style=f"bold #1a1a1a on {_AGENTS_SYNC_ACCENT}",
            )
        return text

    @staticmethod
    def _build_tooltip(statuses: tuple[ProjectSyncStatus, ...]) -> str:
        if not statuses:
            return "No cached foreign agent updates are waiting to be imported"
        lines = ["Cached foreign agent updates ready to import:"]
        for status in statuses:
            lines.append(f"{status.project}:")
            for item in sorted(
                status.pending_updates,
                key=lambda row: (
                    row.source_username or "",
                    row.source_machine,
                    row.top_hood,
                    row.cache_id,
                ),
            ):
                run_noun = "run" if item.run_count == 1 else "runs"
                family_noun = "family" if item.family_count == 1 else "families"
                lines.append(
                    f"  {captured_agent_hood_label(item)} — "
                    f"{item.run_count} {run_noun}, "
                    f"{item.family_count} {family_noun}"
                )
        lines.append(
            "Click to import this captured cache without fetching. Press ,U "
            "for the comprehensive cached update."
        )
        return "\n".join(lines)


__all__ = ["AgentsSyncIndicator"]
