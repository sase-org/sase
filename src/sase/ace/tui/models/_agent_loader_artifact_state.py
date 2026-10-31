"""Load state and callable types shared by artifact loader modules."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Protocol

from sase.core.agent_scan_wire import (
    AgentArtifactIndexQueryWire,
    AgentArtifactScanOptionsWire,
    AgentArtifactScanWire,
)


LOCK_BUSY_SERVED_CACHED_REASON = "artifact_index_lock_busy_served_cached"
LOCK_BUSY_KEEP_ROSTER_REASON = "artifact_index_lock_busy_keep_roster"
LOCK_BUSY_BOUNDED_FALLBACK_REASON = "artifact_index_lock_busy_bounded_fallback"


@dataclass(frozen=True)
class AgentLoadState:
    """Artifact-history completeness for one TUI agent load."""

    tier: Literal["tier1", "tier2"]
    complete_history: bool
    artifact_source: Literal["artifact_index", "source_scan", "artifact_delta"]
    used_artifact_index: bool
    index_error: str | None = None
    complete_visible_inbox: bool = True
    repair_recommended: bool = False
    repair_reason: str | None = None
    truncated: bool = False
    deleted_artifact_dirs: frozenset[str] = field(default_factory=frozenset)
    record_count: int | None = None
    bounded_prefix: bool = False
    requested_limit: int | None = None
    returned_count: int | None = None
    has_more: bool = False
    query_incomplete: bool = False
    history_query_key: tuple[str, str] | None = None
    marker_signatures_checked: int = 0
    rows_repaired: int = 0
    rows_discovered: int = 0
    rows_removed: int = 0
    record_json_decoded: int = 0

    @property
    def needs_full_history_reconcile(self) -> bool:
        """Return whether the caller should schedule a Tier 2 refresh."""

        return (
            not self.complete_visible_inbox
            or self.repair_recommended
            or self.truncated
            or self.query_incomplete
            or (self.tier == "tier2" and not self.complete_history)
        )


class ArtifactScanner(Protocol):
    def __call__(
        self,
        options: AgentArtifactScanOptionsWire | None = None,
    ) -> AgentArtifactScanWire: ...


class ArtifactIndexQuery(Protocol):
    def __call__(
        self,
        index_path: Path,
        projects_root: Path,
        *,
        query: AgentArtifactIndexQueryWire,
        options: AgentArtifactScanOptionsWire,
    ) -> AgentArtifactScanWire | None: ...


def artifact_index_lock_busy_reason(reason: str | None) -> bool:
    """Return whether *reason* is an artifact-index lock-busy repair reason."""

    return isinstance(reason, str) and reason.startswith("artifact_index_lock_busy_")


def load_state_keeps_displayed_roster(state: AgentLoadState) -> bool:
    """Return whether this load must leave the displayed roster unchanged."""

    return state.repair_reason == LOCK_BUSY_KEEP_ROSTER_REASON


def slow_loader_load_state_fields(state: AgentLoadState | None) -> dict[str, object]:
    """Return slow-load telemetry fields when a load state is known."""

    if state is None:
        return {}
    return {
        "artifact_source": state.artifact_source,
        "repair_reason": state.repair_reason,
        "tier": state.tier,
        "complete_history": state.complete_history,
    }
