"""State contracts for TUI agent loading."""

from dataclasses import dataclass
from typing import Literal

from .agent import Agent


@dataclass(frozen=True)
class AgentLoadState:
    """Artifact-history completeness for one TUI agent load.

    Phase 1 of bead ``sase-3r`` (Fast Agents Tab Disk Loading) widens this
    contract so future phases can see exactly what the loader did without
    having to reproduce its branching logic. The added fields are
    measurement-only and intentionally do not change loader behavior:

    Attributes:
        tier: ``tier1`` for visibility-bounded refreshes; ``tier2`` for
            full-history reconciles.
        complete_history: Whether every artifact-backed agent is present
            in the result (Tier 2 / explicit full-history loads only).
        artifact_source: ``artifact_index`` when the snapshot came from
            the persistent index; ``source_scan`` when it came from the
            filesystem walk.
        used_artifact_index: Convenience flag mirroring
            ``artifact_source == "artifact_index"``.
        index_error: Stringified exception from the index query that
            triggered a source-scan fallback, or ``None`` on success.
        full_history: ``True`` when the caller asked for (or was forced
            into) a Tier 2 full-history load. Captured separately from
            ``complete_history`` so Phase 3 can demote "search forces
            full history" without rewriting every assertion.
        agent_search_active: ``True`` when the Agents-tab search query
            was non-empty at the time the loader was invoked. Today this
            implies ``full_history=True``; the contract test in
            ``tests/ace/tui/actions/test_agent_loader_phase1_guardrails.py``
            locks that in so Phase 3 must change it deliberately.
        snapshot_records: Number of ``AgentArtifactRecordWire`` rows in
            the underlying scan snapshot.
        loaded_agent_count: Number of agents the loader returned to the
            TUI (after dedup and status overrides).
        loaded_workflow_step_count: Number of workflow agent-step rows
            returned alongside the loader's agents list.
        artifact_dirs_visited: Snapshot ``stats.artifact_dirs_visited``
            when available, else ``None``.
        marker_files_parsed: Snapshot ``stats.marker_files_parsed`` when
            available, else ``None``.
        prompt_step_markers_parsed: Snapshot
            ``stats.prompt_step_markers_parsed`` when available, else
            ``None``.
        index_query_ms: Time spent in the sqlite-backed index query,
            including wire rehydration, for Tier 1 index loads.
        source_scan_ms: Time spent scanning source artifact directories
            for explicit Tier 2 or bounded fallback source scans.
        snapshot_hydration_ms: Time spent converting the artifact snapshot
            into Python ``Agent`` models before dedup/sort/fold.
        model_sort_ms: Time spent in Python filtering/dedup/status
            overrides/sort before handing rows to the apply boundary.
        index_row_count: Number of records returned by the index query
            when the load read sqlite.
        source_row_count: Number of records returned by a source scan
            when the load walked source artifacts.
        index_missing: Phase 3 of ``sase-3r``. ``True`` when the loader
            could not consult the persistent artifact index because the
            sqlite file was absent and the snapshot was returned empty
            instead of doing a fallback source scan. The apply layer uses
            this to schedule a one-off index rebuild rather than a Tier 2
            source scan.
    """

    tier: Literal["tier1", "tier2"]
    complete_history: bool
    artifact_source: Literal["artifact_index", "source_scan"]
    used_artifact_index: bool
    index_error: str | None = None
    full_history: bool = False
    agent_search_active: bool = False
    snapshot_records: int = 0
    loaded_agent_count: int = 0
    loaded_workflow_step_count: int = 0
    artifact_dirs_visited: int | None = None
    marker_files_parsed: int | None = None
    prompt_step_markers_parsed: int | None = None
    index_query_ms: float | None = None
    source_scan_ms: float | None = None
    snapshot_hydration_ms: float | None = None
    model_sort_ms: float | None = None
    index_row_count: int | None = None
    source_row_count: int | None = None
    index_missing: bool = False

    @property
    def needs_full_history_reconcile(self) -> bool:
        """Return whether the caller should schedule a Tier 2 refresh."""

        if self.complete_history:
            return False
        if self.index_missing:
            return False
        return self.artifact_source == "source_scan"

    def trace_fields(self) -> dict[str, object]:
        """Return a JSON-friendly mapping for ``tui_trace`` enrichment."""

        return {
            "tier": self.tier,
            "complete_history": self.complete_history,
            "artifact_source": self.artifact_source,
            "used_artifact_index": self.used_artifact_index,
            "index_error": self.index_error,
            "full_history": self.full_history,
            "agent_search_active": self.agent_search_active,
            "snapshot_records": self.snapshot_records,
            "loaded_agent_count": self.loaded_agent_count,
            "loaded_workflow_step_count": self.loaded_workflow_step_count,
            "artifact_dirs_visited": self.artifact_dirs_visited,
            "marker_files_parsed": self.marker_files_parsed,
            "prompt_step_markers_parsed": self.prompt_step_markers_parsed,
            "index_query_ms": self.index_query_ms,
            "source_scan_ms": self.source_scan_ms,
            "snapshot_hydration_ms": self.snapshot_hydration_ms,
            "model_sort_ms": self.model_sort_ms,
            "index_row_count": self.index_row_count,
            "source_row_count": self.source_row_count,
            "index_missing": self.index_missing,
        }


@dataclass(frozen=True)
class AgentLoadResult:
    """Agents plus metadata about the artifact-history tier used."""

    agents: list[Agent]
    workflow_agent_steps: list[Agent]
    state: AgentLoadState
