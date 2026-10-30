"""Published state inventory and local-evidence resolution for state repair."""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from sase.agents_sync.inventory import (
    InventoryRun,
    ProjectHoodInventory,
    build_project_hood_inventory,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2ProjectIdentity,
    V2RunRecord,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.agents_sync._publication_state_repair_types import (
    ResolvedWindow,
    STATE_REPAIR_MAX_HOODS,
    StateRepairAffected,
)


def default_inventory_loader(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    hoods: frozenset[str],
) -> ProjectHoodInventory:
    from sase.agent.names._registry import name_registry_load_session

    with name_registry_load_session():
        return build_project_hood_inventory(
            target,
            identity,
            requested_hoods=hoods,
        )


def _owner_identity_token(owner: AgentOwnerIdentity) -> str:
    return f"{owner.username}@{owner.machine_name}"


def collect_published_rows(
    repo_root: Path,
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
) -> tuple[
    list[tuple[str, str]],
    dict[tuple[str, str], tuple[str, V2RunRecord]],
    int,
    frozenset[str],
    list[str],
]:
    """List current-owner published runs ordered by (hood, run id).

    Oversized or corrupt hoods are diagnosed and skipped so other units can
    still progress; their names are returned for degraded page rendering.
    """

    from sase.agents_sync.v2_io import read_owner_manifest

    project = V2ProjectIdentity(target.project_key, target.project)
    try:
        manifest = read_owner_manifest(repo_root, owner, project)
    except AgentsSyncFormatError as exc:
        return [], {}, 0, frozenset(), [f"owner manifest is not readable: {exc}"]
    entries = manifest.by_hood()
    rows: list[tuple[str, str]] = []
    snapshots: dict[tuple[str, str], tuple[str, V2RunRecord]] = {}
    failed = 0
    bad_hoods: set[str] = set()
    diagnostics: list[str] = []
    for hood in sorted(entries):
        try:
            snapshot = validated_snapshot_for_entry(
                repo_root, owner, hood, entries.get(hood)
            )
        except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
            failed += 1
            bad_hoods.add(hood)
            diagnostics.append(f"hood {hood!r} is not repairable: {exc}")
            continue
        for run in snapshot.runs:
            rows.append((hood, run.source_run_id))
            snapshots[(hood, run.source_run_id)] = (run.global_name, run)
    rows.sort()
    return rows, snapshots, failed, frozenset(bad_hoods), diagnostics


def validated_snapshot_for_entry(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    hood: str,
    entry: V2OwnerHoodEntry | None,
) -> V2HoodSnapshot:
    from sase.agents_sync.publication_validation import previous_snapshot

    snapshot = previous_snapshot(repo_root, owner, hood, entry)
    if snapshot is None:
        raise AgentsSyncFormatError(f"hood {hood!r} has no published snapshot")
    return snapshot


def select_window(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    limit: int,
    after: str | None,
    rows: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], str | None, bool, str | None]:
    from sase.core.agent_run_state_facade import (
        agent_run_state_wire_schema_version,
        select_agent_run_state_window,
    )
    from sase.core.agent_run_state_wire import (
        AGENT_RUN_STATE_WIRE_SCHEMA_VERSION,
        AgentRunStateWindowRequestWire,
        AgentRunStateWindowRowWire,
    )

    if agent_run_state_wire_schema_version() != AGENT_RUN_STATE_WIRE_SCHEMA_VERSION:
        return (
            [],
            None,
            False,
            (
                "agent run state wire schema mismatch: "
                "sase_core_rs is stale; update the core revision pin"
            ),
        )
    wire_rows = tuple(
        AgentRunStateWindowRowWire(local_hood=hood, source_run_id=run_id)
        for hood, run_id in rows
    )
    try:
        response = select_agent_run_state_window(
            AgentRunStateWindowRequestWire(
                project=target.project_key,
                owner=_owner_identity_token(owner),
                limit=limit,
                after=after,
                rows=wire_rows,
            )
        )
    except (ValueError, RuntimeError) as exc:
        return [], None, False, f"invalid state window: {exc}"
    selected = [(row.local_hood, row.source_run_id) for row in response.selected]
    hoods = [hood for hood, _run_id in selected]
    if len(dict.fromkeys(hoods)) <= STATE_REPAIR_MAX_HOODS:
        return selected, response.next_cursor, response.pass_complete, None
    capped_hoods = list(dict.fromkeys(hoods))[:STATE_REPAIR_MAX_HOODS]
    capped = [(hood, run_id) for hood, run_id in selected if hood in set(capped_hoods)]
    try:
        capped_response = select_agent_run_state_window(
            AgentRunStateWindowRequestWire(
                project=target.project_key,
                owner=_owner_identity_token(owner),
                limit=len(capped),
                after=after,
                rows=wire_rows,
            )
        )
    except (ValueError, RuntimeError) as exc:  # pragma: no cover - defensive
        return [], None, False, f"invalid state window: {exc}"
    capped_selected = [
        (row.local_hood, row.source_run_id) for row in capped_response.selected
    ]
    return capped_selected, capped_response.next_cursor, False, None


def resolve_selected(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    snapshots: Mapping[tuple[str, str], tuple[str, V2RunRecord]],
    inventory: ProjectHoodInventory,
    selected: list[tuple[str, str]],
    deadline: float,
) -> ResolvedWindow:
    from sase.core.agent_run_state_facade import resolve_agent_run_state
    from sase.core.agent_run_state_wire import (
        AGENT_RUN_STATE_EVIDENCE_DISMISSED,
        AGENT_RUN_STATE_EVIDENCE_IDENTITY_CONFLICT,
        AGENT_RUN_STATE_EVIDENCE_MALFORMED,
        AGENT_RUN_STATE_EVIDENCE_MISSING,
        AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER,
        AGENT_RUN_STATE_EVIDENCE_UNFINISHED,
        AGENT_RUN_STATE_REASON_CONFLICTING_TERMINAL,
        AGENT_RUN_STATE_REASON_IDENTITY_CONFLICT,
        AGENT_RUN_STATE_REASON_LIVE_EVIDENCE,
        AGENT_RUN_STATE_REASON_MALFORMED_EVIDENCE,
        AGENT_RUN_STATE_REASON_MISSING_EVIDENCE,
        AGENT_RUN_STATE_REASON_UNCHANGED,
        AgentRunIdentityWire,
        AgentRunStateResolveRequestWire,
    )

    by_source: dict[str, list[tuple[str, str]]] = {}
    for hood, run_id in selected:
        by_source.setdefault(run_id, []).append((hood, run_id))
    inventory_by_source: dict[str, InventoryRun] = {}
    for run in inventory.runs:
        existing = inventory_by_source.get(run.source_run_id)
        if existing is None:
            inventory_by_source[run.source_run_id] = run
    resolved = ResolvedWindow(changed={}, pending={})
    owner_token = _owner_identity_token(owner)
    for hood, run_id in selected:
        if time.monotonic() > deadline:
            resolved.failed += 1
            resolved.diagnostics.append(
                f"{hood}/{run_id}: state repair work budget exceeded; "
                "retry the window with a smaller limit"
            )
            continue
        published = snapshots.get((hood, run_id))
        if published is None:  # pragma: no cover - rows came from snapshots
            resolved.failed += 1
            resolved.diagnostics.append(
                f"{hood}/{run_id}: published run is no longer present"
            )
            continue
        global_name, record = published
        local_run = inventory_by_source.get(run_id)
        source_label = (
            str(local_run.source_label or "") if local_run is not None else ""
        )
        if source_label.startswith(
            ("primary commit history", "synthesized publication")
        ):
            local_run = None
        if local_run is None:
            evidence_kind = AGENT_RUN_STATE_EVIDENCE_MISSING
            evidence_identity = None
            evidence_state = None
            evidence_started = None
            evidence_finished = None
        elif local_run.global_name != global_name:
            evidence_kind = AGENT_RUN_STATE_EVIDENCE_IDENTITY_CONFLICT
            evidence_identity = AgentRunIdentityWire(
                project=target.project_key,
                owner=owner_token,
                global_name=local_run.global_name,
                source_run_id=run_id,
            )
            evidence_state = None
            evidence_started = None
            evidence_finished = None
        elif local_run.state in ("completed", "failed", "stopped"):
            evidence_kind = AGENT_RUN_STATE_EVIDENCE_TERMINAL_MARKER
            evidence_identity = AgentRunIdentityWire(
                project=target.project_key,
                owner=owner_token,
                global_name=global_name,
                source_run_id=run_id,
            )
            evidence_state = local_run.state
            evidence_started = local_run.started_at
            evidence_finished = local_run.finished_at
        elif local_run.state == "dismissed":
            evidence_kind = AGENT_RUN_STATE_EVIDENCE_DISMISSED
            evidence_identity = AgentRunIdentityWire(
                project=target.project_key,
                owner=owner_token,
                global_name=global_name,
                source_run_id=run_id,
            )
            evidence_state = "dismissed"
            evidence_started = local_run.started_at
            evidence_finished = local_run.finished_at
        elif local_run.state in ("active", "waiting"):
            evidence_kind = AGENT_RUN_STATE_EVIDENCE_UNFINISHED
            evidence_identity = AgentRunIdentityWire(
                project=target.project_key,
                owner=owner_token,
                global_name=global_name,
                source_run_id=run_id,
            )
            evidence_state = None
            evidence_started = local_run.started_at
            evidence_finished = local_run.finished_at
        else:
            evidence_kind = AGENT_RUN_STATE_EVIDENCE_MALFORMED
            evidence_identity = None
            evidence_state = None
            evidence_started = None
            evidence_finished = None
        # A reused name with a different run identity never borrows terminal
        # state: the source_run_id match above is the only borrow path, and a
        # global-name mismatch is an identity conflict, not evidence.
        # Commit-only placeholders are already treated as missing evidence.
        request = AgentRunStateResolveRequestWire(
            identity=AgentRunIdentityWire(
                project=target.project_key,
                owner=owner_token,
                global_name=global_name,
                source_run_id=run_id,
            ),
            published_state=record.state,
            published_started_at=record.started_at,
            published_finished_at=record.finished_at,
            evidence_kind=evidence_kind,
            evidence_identity=evidence_identity,
            evidence_state=evidence_state,
            evidence_started_at=evidence_started,
            evidence_finished_at=evidence_finished,
        )
        try:
            response = resolve_agent_run_state(request)
        except (ValueError, RuntimeError) as exc:
            resolved.failed += 1
            resolved.diagnostics.append(
                f"{global_name}: unresolved state evidence ({exc}); unchanged"
            )
            continue
        if response.reason == AGENT_RUN_STATE_REASON_LIVE_EVIDENCE:
            resolved.live += 1
        elif response.reason in (
            AGENT_RUN_STATE_REASON_MISSING_EVIDENCE,
            AGENT_RUN_STATE_REASON_MALFORMED_EVIDENCE,
            AGENT_RUN_STATE_REASON_IDENTITY_CONFLICT,
            AGENT_RUN_STATE_REASON_CONFLICTING_TERMINAL,
        ):
            resolved.unresolved += 1
            resolved.diagnostics.append(
                f"{global_name}: {response.reason}; preserved {record.state}"
            )
        elif not response.changed:
            resolved.already_current += 1
        else:
            resolved.changed[(hood, run_id)] = StateRepairAffected(
                hood, run_id, global_name, response.selected_state
            )
            resolved.pending[(hood, run_id)] = (
                record,
                response.selected_started_at,
                response.selected_finished_at,
            )
            if response.reason == AGENT_RUN_STATE_REASON_UNCHANGED:  # pragma: no cover
                resolved.already_current += 1
    return resolved
