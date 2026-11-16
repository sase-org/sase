"""Loaded presentation state for one terminal workspace-retention record."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from sase.workspace_provider.retention_record import (
    WorkspaceRetentionRecord,
    configured_held_claim_ttl_days,
    read_workspace_retention_record,
    workspace_retention_lines,
)


@dataclass(frozen=True, slots=True)
class AgentWorkspaceRetention:
    """Warm view data for a retained workspace, loaded outside render paths."""

    record: WorkspaceRetentionRecord
    held_claim_ttl_days: int | None

    @property
    def lines(self) -> tuple[str, ...]:
        return workspace_retention_lines(
            self.record,
            held_claim_ttl_days=self.held_claim_ttl_days,
        )


def load_agent_workspace_retention(
    artifacts_dir: str | None,
) -> AgentWorkspaceRetention | None:
    def load(
        held_claim_ttl_days: Callable[[], int | None],
    ) -> AgentWorkspaceRetention | None:
        record = read_workspace_retention_record(artifacts_dir)
        if record is None or not record.terminal or not record.unresolved:
            return None
        return AgentWorkspaceRetention(
            record=record,
            held_claim_ttl_days=held_claim_ttl_days(),
        )

    from ._loader_memos import current_agent_loader_memos

    memos = current_agent_loader_memos()
    if memos is None:
        return load(configured_held_claim_ttl_days)
    return memos.workspace_retention(artifacts_dir, load)


__all__ = ["AgentWorkspaceRetention", "load_agent_workspace_retention"]
