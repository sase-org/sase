"""Data models for project-scoped agent inventory."""

from __future__ import annotations

from dataclasses import dataclass, field
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
    source_label: str | None = None


@dataclass(frozen=True, slots=True)
class ProjectHoodInventory:
    owner: AgentOwnerIdentity
    project_key: str
    runs: tuple[InventoryRun, ...]
    diagnostics: tuple[str, ...] = ()
    primary_remote_url: str | None = None
    primary_repo_name: str | None = None
    _selection_exclusions: frozenset[str] = field(
        default_factory=frozenset,
        init=False,
        compare=False,
        repr=False,
    )

    def hood_runs(self, hood: str) -> tuple[InventoryRun, ...]:
        selected: list[InventoryRun] = []
        for run in self.runs:
            if run.source_run_id in self._selection_exclusions:
                continue
            try:
                in_hood = agent_name_in_hood(run.local_name, hood)
            except Exception as exc:  # noqa: BLE001 - defensive history boundary.
                self._record_selection_exclusion(run, exc)
                continue
            if in_hood:
                selected.append(run)
        return tuple(selected)

    def eligible_hoods(self) -> tuple[str, ...]:
        hoods: set[str] = set()
        for run in self.runs:
            if not run.commits or run.source_run_id in self._selection_exclusions:
                continue
            try:
                hoods.add(agent_local_hood(run.local_name))
            except Exception as exc:  # noqa: BLE001 - defensive history boundary.
                self._record_selection_exclusion(run, exc)
        return tuple(sorted(hoods))

    def _record_selection_exclusion(self, run: InventoryRun, exc: Exception) -> None:
        source = run.source_label or run.source_run_id
        reason = str(exc) or type(exc).__name__
        diagnostic = f"{source}: excluded from agent hood inventory: {reason}"
        object.__setattr__(
            self,
            "_selection_exclusions",
            self._selection_exclusions | {run.source_run_id},
        )
        if diagnostic in self.diagnostics:
            return
        object.__setattr__(
            self,
            "diagnostics",
            tuple(dict.fromkeys((*self.diagnostics, diagnostic))),
        )
