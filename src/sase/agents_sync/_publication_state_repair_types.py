"""Types shared by bounded agent run state repair components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_models import V2RunRecord
from sase.core.agent_identity_facade import AgentIdentitySnapshot

STATE_REPAIR_DEFAULT_LIMIT = 100
STATE_REPAIR_MAX_HOODS = 5
STATE_REPAIR_MIN_LIMIT = 1
STATE_REPAIR_MAX_LIMIT = 500
STATE_REPAIR_WORK_BUDGET_SECONDS = 90.0
STATE_REPAIR_SCHEMA_VERSION = 1

REPAIR_STATES_COMMAND = "sase agent sync --repair-states"
REPAIR_STATES_APPLY_COMMAND = "sase agent sync --repair-states --apply"


InventoryLoader = Callable[
    [ProjectTarget, AgentIdentitySnapshot, frozenset[str]], ProjectHoodInventory
]


@dataclass(frozen=True, slots=True)
class StateRepairWindowRow:
    """One examined published run, ordered by (local_hood, source_run_id)."""

    local_hood: str
    source_run_id: str

    def to_json_dict(self) -> dict[str, object]:
        return {"local_hood": self.local_hood, "source_run_id": self.source_run_id}


@dataclass(frozen=True, slots=True)
class StateRepairAffected:
    """One run whose published state converges to local evidence."""

    local_hood: str
    source_run_id: str
    global_name: str
    selected_state: str

    def to_json_dict(self) -> dict[str, object]:
        return {
            "local_hood": self.local_hood,
            "source_run_id": self.source_run_id,
            "global_name": self.global_name,
            "selected_state": self.selected_state,
        }


@dataclass(frozen=True, slots=True)
class StateRepairReport:
    """Bounded repair outcome for one project."""

    project_key: str
    project: str
    mode: str
    examined: int = 0
    changed: int = 0
    already_current: int = 0
    live: int = 0
    unresolved: int = 0
    withheld: int = 0
    failed: int = 0
    affected: tuple[StateRepairAffected, ...] = ()
    window: tuple[StateRepairWindowRow, ...] = ()
    next_cursor: str | None = None
    pass_complete: bool = False
    committed: bool = False
    pushed: bool = False
    push_attempts: int = 0
    skip_reason: str | None = None
    error: str | None = None
    diagnostics: tuple[str, ...] = ()
    schema_version: int = STATE_REPAIR_SCHEMA_VERSION

    def to_json_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "mode": self.mode,
            "project_key": self.project_key,
            "project": self.project,
            "examined": self.examined,
            "changed": self.changed,
            "already_current": self.already_current,
            "live": self.live,
            "unresolved": self.unresolved,
            "withheld": self.withheld,
            "failed": self.failed,
            "affected": [item.to_json_dict() for item in self.affected],
            "window": [item.to_json_dict() for item in self.window],
            "next_cursor": self.next_cursor,
            "pass_complete": self.pass_complete,
            "committed": self.committed,
            "pushed": self.pushed,
            "push_attempts": self.push_attempts,
            "skip_reason": self.skip_reason,
            "error": self.error,
            "diagnostics": list(self.diagnostics),
        }


@dataclass
class ResolvedWindow:
    changed: dict[tuple[str, str], StateRepairAffected]
    pending: dict[tuple[str, str], tuple[V2RunRecord, str | None, str | None]]
    already_current: int = 0
    live: int = 0
    unresolved: int = 0
    failed: int = 0
    diagnostics: list[str] = field(default_factory=list)
