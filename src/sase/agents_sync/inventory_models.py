"""Data models for project-scoped agent inventory."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sase.agents_sync.models import CommitRecord
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    agent_local_hood,
    agent_name_in_hood,
)


@dataclass(frozen=True, slots=True)
class InventoryRelationship:
    kind: str
    target: str
    target_kind: str
    required: bool = False


@dataclass(frozen=True, slots=True)
class InventoryRun:
    source_run_id: str
    local_name: str
    global_name: str
    state: str
    started_at: str | None
    finished_at: str | None
    dismissed_at: str | None
    metadata: tuple[tuple[str, Any], ...]
    commits: tuple[CommitRecord, ...]
    prompt_bytes: bytes | None
    chat_bytes: bytes | None
    family_name: str | None
    clan_name: str | None
    relationships: tuple[InventoryRelationship, ...]
    timestamp: str
    embedded_workflows_bytes: bytes | None = None
    prompt_steps_bytes: bytes | None = None


@dataclass(frozen=True, slots=True)
class ProjectHoodInventory:
    owner: AgentOwnerIdentity
    project_key: str
    runs: tuple[InventoryRun, ...]
    diagnostics: tuple[str, ...] = ()

    def hood_runs(self, hood: str) -> tuple[InventoryRun, ...]:
        return tuple(
            run for run in self.runs if agent_name_in_hood(run.local_name, hood)
        )

    def eligible_hoods(self) -> tuple[str, ...]:
        return tuple(
            sorted(
                {agent_local_hood(run.local_name) for run in self.runs if run.commits}
            )
        )
