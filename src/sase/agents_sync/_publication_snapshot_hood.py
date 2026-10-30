"""Owner-sharded hood snapshot orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from sase.agents_sync._publication_snapshot_containers import (
    build_containers,
    build_relationships,
)
from sase.agents_sync._publication_snapshot_gating import (
    GatedRun,
    gate_run_files,
    merge_richer_run_files,
    resolve_preserved_run_state,
)
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.publication_validation import verify_run_files
from sase.agents_sync.v2_io import validate_snapshot
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2ProjectIdentity,
    V2RunRecord,
)
from sase.core.agent_identity_facade import (
    AgentOwnerIdentity,
    agent_name_ancestors,
    globalize_agent_name,
)

if TYPE_CHECKING:
    from sase.agents_sync.publication_protection import PublicationProtectionScope


@dataclass(frozen=True, slots=True)
class _HoodWithheld:
    """Structured outcome when every current run in a hood is withheld."""

    hood: str
    reason: str
    withheld_runs: tuple[tuple[str, str], ...]


class HoodWithheldError(Exception):
    """A hood has current runs, but none of them may be published.

    Does not subclass ``AgentsSyncFormatError``: the commit drain treats
    that error as a terminal hood failure. Callers skip the hood and keep
    planning the rest of the project.
    """

    def __init__(self, withheld: _HoodWithheld) -> None:
        self.withheld = withheld
        super().__init__(f"hood {withheld.hood!r} withheld: {withheld.reason}")


RUN_WITHHELD_BLOCKED = "run withheld by publication protection"
RUN_WITHHELD_UNVERIFIED = "run could not be verified for publication"
HOOD_WITHHELD_BLOCKED = "hood withheld by publication protection"
HOOD_WITHHELD_UNVERIFIED = "hood could not be verified for publication"


def settlement_error_for_withheld_request(
    *,
    global_agent: str,
    local_hood: str,
    withheld_runs: tuple[tuple[str, str], ...],
    withheld_hoods: tuple[tuple[str, str], ...],
) -> str | None:
    """Return the value-free park/retry error for a withheld request, if any."""

    reason = dict(withheld_runs).get(global_agent)
    if reason is not None:
        return RUN_WITHHELD_BLOCKED if reason == "blocked" else RUN_WITHHELD_UNVERIFIED
    reason = dict(withheld_hoods).get(local_hood)
    if reason is not None:
        return (
            HOOD_WITHHELD_BLOCKED if reason == "blocked" else HOOD_WITHHELD_UNVERIFIED
        )
    return None


def build_hood_snapshot(
    repo_root: Path,
    project: V2ProjectIdentity,
    owner: AgentOwnerIdentity,
    hood: str,
    inventory: ProjectHoodInventory,
    previous: V2HoodSnapshot | None,
    *,
    protection_scope: PublicationProtectionScope | None = None,
) -> tuple[
    V2HoodSnapshot, dict[str, bytes], tuple[str, ...], tuple[tuple[str, str], ...]
]:
    current = inventory.hood_runs(hood)
    agent_session_history = inventory.agent_session_lane_commits(hood)
    if not current and previous is None:
        from sase.agents_sync.io import AgentsSyncFormatError

        raise AgentsSyncFormatError(f"hood {hood!r} has no publishable runs")
    if protection_scope is None:
        # Deferred so the protection modules stay out of the TUI startup closure.
        from sase.agents_sync.publication_protection import PublicationProtectionScope

        scope = PublicationProtectionScope(
            project_key=project.key,
            repository_identity=project.key,
        )
    else:
        scope = protection_scope
    payload: dict[str, bytes] = {}
    previous_by_global = (
        {run.global_name: run for run in previous.runs} if previous is not None else {}
    )
    resolved_current: list[InventoryRun] = []
    resolve_notes: list[str] = []
    for run in current:
        resolved, note = resolve_preserved_run_state(
            run, previous_by_global.get(run.global_name), project, owner
        )
        resolved_current.append(resolved)
        if note is not None:
            resolve_notes.append(note)
    gated = tuple(
        gate_run_files(run, owner, project, payload, scope=scope)
        for run in resolved_current
    )
    notes: list[str] = []
    notes.extend(resolve_notes)
    withheld_globals: set[str] = set()
    withheld_pairs: list[tuple[str, str]] = []
    gated_records: list[GatedRun] = []
    for gated_run in gated:
        notes.extend(gated_run.notes)
        if gated_run.record is None:
            withheld_globals.add(gated_run.run.global_name)
            withheld_pairs.append(
                (
                    gated_run.run.global_name,
                    gated_run.withheld_reason or "unverified",
                )
            )
        else:
            gated_records.append(gated_run)
    if current and not gated_records:
        hood_reason = (
            "blocked"
            if all(gated_run.withheld_reason == "blocked" for gated_run in gated)
            else "unverified"
        )
        raise HoodWithheldError(
            _HoodWithheld(
                hood=hood,
                reason=hood_reason,
                withheld_runs=tuple(withheld_pairs),
            )
        )
    current_records: list[V2RunRecord] = []
    for gated_run in gated_records:
        assert gated_run.record is not None
        merged, merge_notes = merge_richer_run_files(
            gated_run.record,
            previous_by_global.get(gated_run.run.global_name),
            repo_root,
            payload,
            scope=scope,
            blocked_kinds=gated_run.blocked_kinds,
        )
        notes.extend(merge_notes)
        current_records.append(merged)
    current_ids = {run.source_run_id for run in current_records}
    current_globals = {run.global_name for run in current_records}
    prior_records = (
        tuple(
            run
            for run in previous.runs
            if run.source_run_id not in current_ids
            and run.global_name not in current_globals
            and run.global_name not in withheld_globals
        )
        if previous is not None
        else ()
    )
    for prior_run in prior_records:
        verify_run_files(repo_root, prior_run)
    combined = tuple(
        sorted((*prior_records, *current_records), key=lambda item: item.source_run_id)
    )
    containers = build_containers(
        combined,
        owner,
        agent_session_history,
        previous.containers if previous is not None else (),
    )
    publishable_current = tuple(
        run for run in current if run.global_name not in withheld_globals
    )
    relationships = build_relationships(
        publishable_current,
        combined,
        inventory,
        owner,
        previous,
        current_ids,
    )
    ancestors = tuple(
        sorted(
            {
                globalize_agent_name(ancestor, owner)
                for run in combined
                for ancestor in agent_name_ancestors(run.local_name)
            }
        )
    )
    snapshot = V2HoodSnapshot(
        owner=owner,
        project=project,
        local_hood=hood,
        global_hood=globalize_agent_name(hood, owner),
        structural_ancestors=ancestors,
        runs=combined,
        containers=containers,
        relationships=relationships,
    )
    validate_snapshot(snapshot)
    return snapshot, payload, tuple(notes), tuple(withheld_pairs)
