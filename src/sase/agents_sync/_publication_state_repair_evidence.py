"""Published state inventory and local-evidence resolution for state repair."""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path

from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2RunRecord,
)
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.agents_sync._publication_state_repair_types import (
    InventoryLoader,
    PlannedRepair,
    ResolvedWindow,
    StateRepairAffected,
)


def default_inventory_loader(
    target: ProjectTarget,
    identity: AgentIdentitySnapshot,
    hoods: frozenset[str],
) -> ProjectHoodInventory:
    """Return an empty inventory so repair reads exact-run observations instead.

    Historical callers passed this loader to hydrate prompts, chats, and
    commit history for every run in selected hoods. Repair now locates
    selected runs through the bounded artifact index and reads only their
    marker files.
    """

    del hoods
    from sase.agents_sync.inventory_scope import empty_project_hood_inventory

    return empty_project_hood_inventory(_target_owner(identity), target)


def _target_owner(identity: AgentIdentitySnapshot) -> AgentOwnerIdentity:
    owner = identity.owner
    if owner is None:
        raise RuntimeError("owner identity is required for state repair")
    return owner


def plan_repair_window(
    repo_root: Path,
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    limit: int,
    after: str | None,
    deadline: float,
    inventory_loader: InventoryLoader,
) -> PlannedRepair:
    """Discover a bounded window and resolve only the selected runs."""

    from sase.agents_sync._publication_state_repair_discovery import (
        discover_repair_window,
    )

    discovery = discover_repair_window(
        repo_root,
        target,
        owner,
        limit=limit,
        after=after,
        deadline=deadline,
    )
    if discovery.error is not None:
        return PlannedRepair(
            selected=discovery.selected,
            snapshots=discovery.snapshots,
            resolved=ResolvedWindow(changed={}, pending={}),
            failed=discovery.failed,
            bad_hoods=discovery.bad_hoods,
            diagnostics=list(discovery.diagnostics),
            next_cursor=None,
            pass_complete=False,
            error=discovery.error,
        )
    selected = discovery.selected
    if not selected:
        return PlannedRepair(
            selected=[],
            snapshots=discovery.snapshots,
            resolved=ResolvedWindow(changed={}, pending={}),
            failed=discovery.failed,
            bad_hoods=discovery.bad_hoods,
            diagnostics=list(discovery.diagnostics),
            next_cursor=discovery.next_cursor,
            pass_complete=discovery.pass_complete,
        )
    if time.monotonic() >= deadline:
        return PlannedRepair(
            selected=selected,
            snapshots=discovery.snapshots,
            resolved=ResolvedWindow(changed={}, pending={}, budget_exhausted=True),
            failed=discovery.failed + 1,
            bad_hoods=discovery.bad_hoods,
            diagnostics=[
                *discovery.diagnostics,
                (
                    "state repair work budget exceeded before verification; "
                    "retry the window with a smaller limit"
                ),
            ],
            next_cursor=None,
            pass_complete=False,
            error=(
                "state repair work budget exceeded before verification; "
                "retry the window with a smaller limit"
            ),
        )
    hoods = frozenset(hood for hood, _run_id in selected)
    try:
        inventory = inventory_loader(target, AgentIdentitySnapshot(owner), hoods)
    except Exception as exc:  # noqa: BLE001 - evidence failure is a diagnostic
        return PlannedRepair(
            selected=selected,
            snapshots=discovery.snapshots,
            resolved=ResolvedWindow(changed={}, pending={}),
            failed=discovery.failed + len(selected),
            bad_hoods=discovery.bad_hoods,
            diagnostics=[
                *discovery.diagnostics,
                f"could not load local evidence: {exc}",
            ],
            next_cursor=None,
            pass_complete=False,
        )
    injected = inventory_loader is not default_inventory_loader
    resolved = _resolve_selected(
        target,
        owner,
        discovery.snapshots,
        inventory if injected else None,
        selected,
        deadline,
    )
    next_cursor = discovery.next_cursor
    pass_complete = discovery.pass_complete
    error = None
    if resolved.budget_exhausted:
        next_cursor = None
        pass_complete = False
        error = (
            "state repair work budget exceeded before verification; "
            "retry the window with a smaller limit"
        )
    return PlannedRepair(
        selected=selected,
        snapshots=discovery.snapshots,
        resolved=resolved,
        failed=discovery.failed + resolved.failed,
        bad_hoods=discovery.bad_hoods,
        diagnostics=[*discovery.diagnostics, *resolved.diagnostics],
        next_cursor=next_cursor,
        pass_complete=pass_complete,
        error=error,
    )


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


def _resolve_selected(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    snapshots: Mapping[tuple[str, str], tuple[str, V2RunRecord]],
    inventory: ProjectHoodInventory | None,
    selected: list[tuple[str, str]],
    deadline: float,
) -> ResolvedWindow:
    from sase.agents_sync._publication_state_repair_observations import (
        filesystem_observations_for_run,
        is_live_reason,
        is_unresolved_reason,
        observations_from_inventory_run,
        resolve_observations,
    )

    inventory_by_source: dict[str, InventoryRun] = {}
    use_inventory = inventory is not None
    if inventory is not None:
        for run in inventory.runs:
            if run.source_run_id not in inventory_by_source:
                inventory_by_source[run.source_run_id] = run
    resolved = ResolvedWindow(changed={}, pending={})
    for hood, run_id in selected:
        if time.monotonic() >= deadline:
            resolved.failed += 1
            resolved.budget_exhausted = True
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
        local_run = inventory_by_source.get(run_id) if use_inventory else None
        if use_inventory:
            observations = (
                observations_from_inventory_run(local_run)
                if local_run is not None
                else observations_from_inventory_run(
                    InventoryRun(
                        run_id,
                        record.local_name,
                        global_name,
                        "active",
                        None,
                        None,
                        None,
                        (),
                        (),
                        None,
                        None,
                        None,
                        None,
                        (),
                        "",
                        source_label="primary commit history",
                    )
                )
            )
            lookup_error = None
        else:
            observations, lookup_error = filesystem_observations_for_run(
                target, owner, record
            )
        if lookup_error is not None:
            resolved.unresolved += 1
            resolved.diagnostics.append(
                f"{global_name}: {lookup_error}; preserved {record.state}"
            )
        try:
            response = resolve_observations(
                project=target.project_key,
                owner=owner,
                global_name=global_name,
                source_run_id=run_id,
                local_name=record.local_name,
                published_state=record.state,
                published_started_at=record.started_at,
                published_finished_at=record.finished_at,
                observations=observations,
            )
        except (ValueError, RuntimeError) as exc:
            resolved.failed += 1
            resolved.diagnostics.append(
                f"{global_name}: unresolved state evidence ({exc}); unchanged"
            )
            continue
        if is_live_reason(response.reason):
            resolved.live += 1
        elif is_unresolved_reason(response.reason):
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
    return resolved
