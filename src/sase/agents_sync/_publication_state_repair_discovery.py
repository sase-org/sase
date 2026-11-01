"""Bounded hood discovery for published-state repair."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_models import V2RunRecord
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_run_state_wire import (
    AGENT_RUN_STATE_HOOD_AVAILABLE,
    AGENT_RUN_STATE_HOOD_CORRUPT,
    AGENT_RUN_STATE_HOOD_EMPTY,
    AGENT_RUN_STATE_MANIFEST_VALID,
    AGENT_RUN_STATE_SCAN_COMPLETE,
    AGENT_RUN_STATE_WIRE_SCHEMA_VERSION,
    AgentRunStateDiscoveredHoodWire,
    AgentRunStateDiscoveryWindowRequestWire,
    AgentRunStateHoodWindowRequestWire,
)


def _owner_token(owner: AgentOwnerIdentity) -> str:
    return f"{owner.username}@{owner.machine_name}"


@dataclass
class DiscoveryResult:
    """One bounded discovery window over the current owner's snapshots."""

    selected: list[tuple[str, str]] = field(default_factory=list)
    snapshots: dict[tuple[str, str], tuple[str, V2RunRecord]] = field(
        default_factory=dict
    )
    failed: int = 0
    bad_hoods: frozenset[str] = field(default_factory=frozenset)
    diagnostics: list[str] = field(default_factory=list)
    next_cursor: str | None = None
    pass_complete: bool = False
    error: str | None = None


def discover_repair_window(
    repo_root: Path,
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    limit: int,
    after: str | None,
    deadline: float,
) -> DiscoveryResult:
    """Select a bounded window from the owner manifest without hydrating inventory."""

    from sase.agents_sync._publication_state_repair_evidence import (
        validated_snapshot_for_entry,
    )
    from sase.agents_sync.v2_io import read_owner_manifest
    from sase.agents_sync.v2_models import V2ProjectIdentity
    from sase.core.agent_run_state_facade import (
        agent_run_state_wire_schema_version,
        select_agent_run_state_discovery_window,
        select_agent_run_state_hoods,
    )

    if time.monotonic() >= deadline:
        return DiscoveryResult(
            error=(
                "state repair work budget exceeded before verification; "
                "retry the window with a smaller limit"
            ),
        )
    if agent_run_state_wire_schema_version() != AGENT_RUN_STATE_WIRE_SCHEMA_VERSION:
        return DiscoveryResult(
            error=(
                "agent run state wire schema mismatch: "
                "sase_core_rs is stale; update the core revision pin"
            ),
        )

    project = V2ProjectIdentity(target.project_key, target.project)
    try:
        manifest = read_owner_manifest(repo_root, owner, project)
    except AgentsSyncFormatError as exc:
        return DiscoveryResult(
            failed=1,
            diagnostics=[f"owner manifest is not readable: {exc}"],
            error=f"owner manifest is not readable: {exc}",
        )
    except OSError as exc:
        return DiscoveryResult(
            failed=1,
            diagnostics=[f"owner manifest is not readable: {exc}"],
            error=f"owner manifest is not readable: {exc}",
        )

    entries = manifest.by_hood()
    manifest_hoods = tuple(sorted(entries))
    if not manifest_hoods:
        return DiscoveryResult(pass_complete=True)

    owner_token = _owner_token(owner)
    try:
        hood_window = select_agent_run_state_hoods(
            AgentRunStateHoodWindowRequestWire(
                project=target.project_key,
                owner=owner_token,
                manifest_status=AGENT_RUN_STATE_MANIFEST_VALID,
                after=after,
                hoods=manifest_hoods,
            )
        )
    except (ValueError, RuntimeError) as exc:
        return DiscoveryResult(
            failed=len(manifest_hoods),
            diagnostics=[f"invalid state window: {exc}"],
            error=f"invalid state window: {exc}",
        )

    discovered: list[AgentRunStateDiscoveredHoodWire] = []
    snapshots: dict[tuple[str, str], tuple[str, V2RunRecord]] = {}
    failed = 0
    bad_hoods: set[str] = set()
    diagnostics: list[str] = []
    for hood in hood_window.selected_hoods:
        if time.monotonic() >= deadline:
            return DiscoveryResult(
                failed=failed + 1,
                bad_hoods=frozenset(bad_hoods),
                diagnostics=[
                    *diagnostics,
                    (
                        "state repair work budget exceeded before verification; "
                        "retry the window with a smaller limit"
                    ),
                ],
                error=(
                    "state repair work budget exceeded before verification; "
                    "retry the window with a smaller limit"
                ),
            )
        try:
            snapshot = validated_snapshot_for_entry(
                repo_root, owner, hood, entries.get(hood)
            )
        except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
            failed += 1
            bad_hoods.add(hood)
            diagnostics.append(f"hood {hood!r} is not repairable: {exc}")
            discovered.append(
                AgentRunStateDiscoveredHoodWire(
                    local_hood=hood, status=AGENT_RUN_STATE_HOOD_CORRUPT
                )
            )
            continue
        run_ids = tuple(run.source_run_id for run in snapshot.runs)
        if not run_ids:
            discovered.append(
                AgentRunStateDiscoveredHoodWire(
                    local_hood=hood, status=AGENT_RUN_STATE_HOOD_EMPTY
                )
            )
            continue
        discovered.append(
            AgentRunStateDiscoveredHoodWire(
                local_hood=hood,
                status=AGENT_RUN_STATE_HOOD_AVAILABLE,
                source_run_ids=run_ids,
            )
        )
        for run in snapshot.runs:
            snapshots[(hood, run.source_run_id)] = (run.global_name, run)

    try:
        window = select_agent_run_state_discovery_window(
            AgentRunStateDiscoveryWindowRequestWire(
                project=target.project_key,
                owner=owner_token,
                manifest_status=AGENT_RUN_STATE_MANIFEST_VALID,
                scan_status=AGENT_RUN_STATE_SCAN_COMPLETE,
                limit=limit,
                after=after,
                manifest_hoods=manifest_hoods,
                hoods=tuple(discovered),
            )
        )
    except (ValueError, RuntimeError) as exc:
        return DiscoveryResult(
            snapshots=snapshots,
            failed=failed,
            bad_hoods=frozenset(bad_hoods),
            diagnostics=[*diagnostics, f"invalid state window: {exc}"],
            error=f"invalid state window: {exc}",
        )

    selected = [(row.local_hood, row.source_run_id) for row in window.selected]
    selected_snapshots = {key: snapshots[key] for key in selected if key in snapshots}
    for item in window.diagnostics:
        if item.kind == "corrupt_hood" and item.local_hood not in bad_hoods:
            failed += 1
            bad_hoods.add(item.local_hood)
            diagnostics.append(f"hood {item.local_hood!r} is not repairable")
        elif item.kind == "empty_hood":
            diagnostics.append(f"hood {item.local_hood!r} is empty")
    return DiscoveryResult(
        selected=selected,
        snapshots=selected_snapshots,
        failed=failed,
        bad_hoods=frozenset(bad_hoods),
        diagnostics=diagnostics,
        next_cursor=window.next_cursor,
        pass_complete=window.pass_complete,
    )
