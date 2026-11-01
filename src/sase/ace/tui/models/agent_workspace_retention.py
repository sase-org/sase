"""Loaded presentation state for one terminal workspace-retention record."""

from __future__ import annotations

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
    record = read_workspace_retention_record(artifacts_dir)
    if record is None or not record.terminal or not record.unresolved:
        return None
    return AgentWorkspaceRetention(
        record=record,
        held_claim_ttl_days=configured_held_claim_ttl_days(),
    )


__all__ = ["AgentWorkspaceRetention", "load_agent_workspace_retention"]
