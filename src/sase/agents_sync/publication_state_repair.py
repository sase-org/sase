"""Bounded report-and-apply repair for already-published agent-run states.

Preview reads the cached sidecar snapshot plus local marker evidence without
network, sidecar writes, audit writes, or checkpoint advancement. Apply
revalidates against a freshly pulled upstream snapshot under the existing
agents lock and publishes only state changes through the shared protection
and push-recovery path. Full sync, outbox drains, and prompt-archive
publishing never run as a side effect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import time
from pathlib import Path
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sase.agents_sync.publication_protection import PublicationProtectionScope

from sase.agents_sync import _commit_publication_support as publication_support
from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync import ensure_agents_clone
from sase.agents_sync.git_sync_ops import (
    agents_git_dir,
    bounded_agents_lock,
    configured_agents_lock_timeout,
)
from sase.agents_sync.inventory import (
    InventoryRun,
    ProjectHoodInventory,
    build_project_hood_inventory,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.v2_io import (
    MAX_PAYLOAD_BYTES,
    apply_payload_batched_atomic,
    content_digest,
    file_reference,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2OwnerManifest,
    V2ProjectIdentity,
    V2RunRecord,
    V2RunStatePayload,
    is_session_container,
)
from sase.agents_sync.v2_validation import MAX_JSON_BYTES
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity

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


def _default_inventory_loader(
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


def repair_agent_run_states(
    projects: tuple[str, ...] = (),
    *,
    apply: bool = False,
    state_limit: int | None = None,
    state_after: str | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
    inventory_loader: InventoryLoader | None = None,
    work_budget_seconds: float = STATE_REPAIR_WORK_BUDGET_SECONDS,
    payload_budget_bytes: int = MAX_PAYLOAD_BYTES,
) -> tuple[StateRepairReport, ...]:
    """Report (or apply) one bounded state window per selected project."""

    limit_error = _validate_limit(state_limit)
    if limit_error is not None:
        return (
            StateRepairReport(
                "", "", "apply" if apply else "preview", error=limit_error
            ),
        )
    selection = publication_support.resolve_sync_targets(tuple(projects))
    reports = [
        StateRepairReport(
            outcome.project_key,
            outcome.project,
            "apply" if apply else "preview",
            error=outcome.error,
            skip_reason=outcome.skip_reason,
            diagnostics=tuple(outcome.diagnostics),
        )
        for outcome in selection.outcomes
    ]
    try:
        owner = publication_support.require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        reports.extend(
            StateRepairReport(
                target.project_key,
                target.project,
                "apply" if apply else "preview",
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(reports, key=lambda item: item.project_key))
    limit = STATE_REPAIR_DEFAULT_LIMIT if state_limit is None else state_limit
    for target in selection.targets:
        try:
            reports.append(
                repair_project_run_states(
                    target,
                    owner,
                    apply=apply,
                    state_limit=limit,
                    state_after=state_after,
                    git_runner=git_runner,
                    lock_timeout_seconds=lock_timeout_seconds,
                    inventory_loader=inventory_loader,
                    work_budget_seconds=work_budget_seconds,
                    payload_budget_bytes=payload_budget_bytes,
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-project isolation contract
            reports.append(
                StateRepairReport(
                    target.project_key,
                    target.project,
                    "apply" if apply else "preview",
                    error=f"agents state repair failed: {exc}",
                )
            )
    return tuple(sorted(reports, key=lambda item: item.project_key))


def _validate_limit(state_limit: int | None) -> str | None:
    if state_limit is None:
        return None
    if not STATE_REPAIR_MIN_LIMIT <= state_limit <= STATE_REPAIR_MAX_LIMIT:
        return (
            "state limit must be between "
            f"{STATE_REPAIR_MIN_LIMIT} and {STATE_REPAIR_MAX_LIMIT}"
        )
    return None


def repair_project_run_states(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    apply: bool = False,
    state_limit: int = STATE_REPAIR_DEFAULT_LIMIT,
    state_after: str | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
    inventory_loader: InventoryLoader | None = None,
    work_budget_seconds: float = STATE_REPAIR_WORK_BUDGET_SECONDS,
    payload_budget_bytes: int = MAX_PAYLOAD_BYTES,
) -> StateRepairReport:
    """Repair one project's published run states in a bounded window."""

    limit_error = _validate_limit(state_limit)
    if limit_error is not None:
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply" if apply else "preview",
            error=limit_error,
        )
    loader = inventory_loader or _default_inventory_loader
    if not apply:
        return _preview_project(
            target,
            owner,
            state_limit=state_limit,
            state_after=state_after,
            inventory_loader=loader,
            work_budget_seconds=work_budget_seconds,
        )
    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    if not target.primary_checkout.is_dir():
        return StateRepairReport(
            target.project_key,
            target.project,
            "apply",
            error="primary checkout does not exist",
        )
    clone_error = ensure_agents_clone(
        target, git_runner=git_runner, lock_timeout_seconds=timeout
    )
    if clone_error is not None:
        if clone_error == "agents sync clone lock is busy":
            return StateRepairReport(
                target.project_key,
                target.project,
                "apply",
                skip_reason=clone_error,
            )
        return StateRepairReport(
            target.project_key, target.project, "apply", error=clone_error
        )
    lock_path = (
        agents_git_dir(target.sidecar_path, git_runner) / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return StateRepairReport(
                target.project_key,
                target.project,
                "apply",
                skip_reason="agents sync lock is busy",
            )
        return _apply_project_locked(
            target,
            owner,
            state_limit=state_limit,
            state_after=state_after,
            git_runner=git_runner,
            inventory_loader=loader,
            work_budget_seconds=work_budget_seconds,
            payload_budget_bytes=payload_budget_bytes,
        )


def _owner_token(owner: AgentOwnerIdentity) -> str:
    return f"{owner.username}@{owner.machine_name}"


def _preview_project(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    state_limit: int,
    state_after: str | None,
    inventory_loader: InventoryLoader,
    work_budget_seconds: float,
) -> StateRepairReport:
    mode = "preview"
    deadline = time.monotonic() + max(work_budget_seconds, 0.0)
    try:
        rows, snapshots, failed, bad_hoods, diagnostics = _collect_published_rows(
            target.sidecar_path, target, owner
        )
    except Exception as exc:  # noqa: BLE001 - preview never raises
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            error=f"state repair failed: {exc}",
        )
    selected, next_cursor, pass_complete, select_error = _select_window(
        target, owner, state_limit, state_after, rows
    )
    if select_error is not None:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            failed=len(rows),
            diagnostics=(*diagnostics, select_error),
            error=select_error,
        )
    window = tuple(StateRepairWindowRow(hood, run_id) for hood, run_id in selected)
    if not selected:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=0,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            diagnostics=tuple(diagnostics),
        )
    hoods = frozenset(hood for hood, _run_id in selected)
    try:
        inventory = inventory_loader(target, AgentIdentitySnapshot(owner), hoods)
    except Exception as exc:  # noqa: BLE001 - evidence failure is a diagnostic
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            failed=len(selected),
            window=window,
            next_cursor=None,
            pass_complete=False,
            diagnostics=(*diagnostics, f"could not load local evidence: {exc}"),
        )
    resolved = _resolve_selected(
        target,
        owner,
        snapshots,
        inventory,
        selected,
        deadline,
    )
    return StateRepairReport(
        target.project_key,
        target.project,
        mode,
        examined=len(selected),
        changed=len(resolved.changed),
        already_current=resolved.already_current,
        live=resolved.live,
        unresolved=resolved.unresolved,
        withheld=0,
        failed=failed + resolved.failed,
        affected=tuple(resolved.changed.values()),
        window=window,
        next_cursor=next_cursor,
        pass_complete=pass_complete,
        diagnostics=(*diagnostics, *resolved.diagnostics),
    )


@dataclass
class _ResolvedWindow:
    changed: dict[tuple[str, str], StateRepairAffected]
    pending: dict[tuple[str, str], tuple[V2RunRecord, str | None, str | None]]
    already_current: int = 0
    live: int = 0
    unresolved: int = 0
    failed: int = 0
    diagnostics: list[str] = field(default_factory=list)


def _collect_published_rows(
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

    from sase.agents_sync.v2_io import owner_manifest_path, read_owner_manifest

    project = V2ProjectIdentity(target.project_key, target.project)
    try:
        manifest = read_owner_manifest(repo_root, owner, project)
    except AgentsSyncFormatError as exc:
        return [], {}, 0, frozenset(), [f"owner manifest is not readable: {exc}"]
    rows: list[tuple[str, str]] = []
    snapshots: dict[tuple[str, str], tuple[str, V2RunRecord]] = {}
    failed = 0
    bad_hoods: set[str] = set()
    diagnostics: list[str] = []
    for hood, _entry in sorted(manifest.hoods):
        try:
            snapshot = _read_validated_snapshot(repo_root, owner, hood, project)
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


def _read_validated_snapshot(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    hood: str,
    project: V2ProjectIdentity,
) -> V2HoodSnapshot:
    from sase.agents_sync.publication_validation import previous_snapshot
    from sase.agents_sync.v2_io import read_owner_manifest

    manifest = read_owner_manifest(repo_root, owner, project)
    entry = manifest.by_hood().get(hood)
    snapshot = previous_snapshot(repo_root, owner, hood, entry)
    if snapshot is None:
        raise AgentsSyncFormatError(f"hood {hood!r} has no published snapshot")
    return snapshot


def _select_window(
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
                owner=_owner_token(owner),
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
                owner=_owner_token(owner),
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


def _resolve_selected(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    snapshots: Mapping[tuple[str, str], tuple[str, V2RunRecord]],
    inventory: ProjectHoodInventory,
    selected: list[tuple[str, str]],
    deadline: float,
) -> _ResolvedWindow:
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
    resolved = _ResolvedWindow(changed={}, pending={})
    owner_token = _owner_token(owner)
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


def _apply_project_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    state_limit: int,
    state_after: str | None,
    git_runner: GitRunner,
    inventory_loader: InventoryLoader,
    work_budget_seconds: float,
    payload_budget_bytes: int,
) -> StateRepairReport:
    from sase.agents_sync.git_sync_ops import (
        abort_agents_rebase,
        clean_agents_payload_worktree,
        pull_agents_rebase,
    )

    mode = "apply"
    deadline = time.monotonic() + max(work_budget_seconds, 0.0)
    repo = target.sidecar_path
    cleanup_error = clean_agents_payload_worktree(repo, git_runner)
    if cleanup_error is not None:
        return StateRepairReport(
            target.project_key, target.project, mode, error=cleanup_error
        )
    pulled = pull_agents_rebase(repo, git_runner, "agents_state_repair.pull")
    if pulled.returncode != 0:
        from sase.agents_sync.git_sync_ops import agents_git_error

        cleanup = abort_agents_rebase(repo, git_runner)
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            error=agents_git_error("git pull --rebase failed", pulled, cleanup),
        )
    report = _plan_and_push_repair(
        target,
        owner,
        state_limit=state_limit,
        state_after=state_after,
        git_runner=git_runner,
        inventory_loader=inventory_loader,
        deadline=deadline,
        payload_budget_bytes=payload_budget_bytes,
        push_op="agents_state_repair.push",
        allow_retry=True,
    )
    cleanup_error = clean_agents_payload_worktree(repo, git_runner)
    if cleanup_error is not None and report.error is None:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=report.examined,
            changed=report.changed,
            already_current=report.already_current,
            live=report.live,
            unresolved=report.unresolved,
            withheld=report.withheld,
            failed=report.failed,
            affected=report.affected,
            window=report.window,
            next_cursor=report.next_cursor,
            pass_complete=report.pass_complete,
            committed=report.committed,
            pushed=report.pushed,
            push_attempts=report.push_attempts,
            error=cleanup_error,
            diagnostics=report.diagnostics,
        )
    return report


def _push_ahead_convergence(
    target: ProjectTarget,
    git_runner: GitRunner,
    push_op: str,
) -> tuple[bool, str | None, int]:
    """Push unpushed repair commits on a verified no-write window.

    A failed push leaves this window's commit ahead of the remote; the retry
    after remediation lands here with nothing left to write, so the owed push
    is attempted to converge the remote. Returns ``(pushed, error, attempts)``;
    an error freezes the cursor exactly like a failed repair push.
    """

    from sase.agents_sync.git_sync_ops import agents_ahead_count

    try:
        ahead = agents_ahead_count(target.sidecar_path, git_runner)
    except Exception:  # noqa: BLE001 - no push without a readable count.
        return False, None, 0
    if ahead <= 0:
        return False, None, 0
    pushed = git_runner(target.sidecar_path, ["push"], network=True, op=push_op)
    if pushed.returncode == 0:
        return True, None, 1
    from sase.agents_sync.publication_recovery import (
        recover_publication_push,
        sanitized_push_error,
    )

    recovery = recover_publication_push(
        target.sidecar_path,
        git_runner,
        project_key=target.project_key,
        repository_identity=target.remote_url,
        returncode=pushed.returncode,
        stdout=pushed.stdout or "",
        stderr=pushed.stderr or "",
    )
    return (
        False,
        sanitized_push_error(
            "git push failed",
            recovery.rejection,
            blocked_paths=recovery.blocked_paths,
        ),
        1,
    )


def _plan_and_push_repair(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    state_limit: int,
    state_after: str | None,
    git_runner: GitRunner,
    inventory_loader: InventoryLoader,
    deadline: float,
    payload_budget_bytes: int,
    push_op: str,
    allow_retry: bool,
) -> StateRepairReport:
    from sase.agents_sync.git_sync_ops import (
        abort_agents_rebase,
        agents_ahead_count,
        agents_git_error,
        clean_agents_payload_worktree,
        commit_agents_payload_if_dirty,
        is_agents_non_fast_forward,
        pull_agents_rebase,
    )

    mode = "apply"
    try:
        rows, snapshots, collect_failed, bad_hoods, collect_diagnostics = (
            _collect_published_rows(target.sidecar_path, target, owner)
        )
    except Exception as exc:  # noqa: BLE001 - per-project isolation
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            error=f"state repair failed: {exc}",
        )
    selected, next_cursor, pass_complete, select_error = _select_window(
        target, owner, state_limit, state_after, rows
    )
    window = tuple(StateRepairWindowRow(hood, run_id) for hood, run_id in selected)
    if select_error is not None:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            failed=len(rows),
            diagnostics=(*collect_diagnostics, select_error),
            error=select_error,
        )
    if not selected:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=0,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            diagnostics=tuple(collect_diagnostics),
        )
    hoods = frozenset(row[0] for row in selected)
    try:
        inventory = inventory_loader(target, AgentIdentitySnapshot(owner), hoods)
    except Exception as exc:  # noqa: BLE001 - evidence failure is a diagnostic
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            failed=len(selected),
            window=window,
            diagnostics=(
                *collect_diagnostics,
                f"could not load local evidence: {exc}",
            ),
        )
    resolved = _resolve_selected(
        target, owner, snapshots, inventory, selected, deadline
    )
    if not resolved.changed:
        # Verified no-write window: the published snapshot already matches
        # local evidence. A previous attempt's unpushed repair commit still
        # converges here so a retry after remediation completes remotely.
        ahead_pushed, push_error, push_attempts = _push_ahead_convergence(
            target, git_runner, "agents_state_repair.push_ahead"
        )
        if push_error is not None:
            return StateRepairReport(
                target.project_key,
                target.project,
                mode,
                examined=len(selected),
                changed=0,
                already_current=resolved.already_current,
                live=resolved.live,
                unresolved=resolved.unresolved,
                withheld=0,
                failed=collect_failed + resolved.failed,
                affected=(),
                window=window,
                next_cursor=None,
                pass_complete=False,
                push_attempts=push_attempts,
                error=push_error,
                diagnostics=(*collect_diagnostics, *resolved.diagnostics),
            )
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=0,
            failed=collect_failed + resolved.failed,
            affected=(),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            pushed=ahead_pushed,
            push_attempts=push_attempts,
            diagnostics=(*collect_diagnostics, *resolved.diagnostics),
        )
    payload, updated, withheld, withheld_diags, plan_failed, plan_diags = (
        _plan_state_payload(
            target,
            owner,
            resolved,
            deadline,
            bad_hoods=bad_hoods,
        )
    )
    failed = collect_failed + resolved.failed + plan_failed
    diagnostics = (*collect_diagnostics, *resolved.diagnostics, *plan_diags)
    if not payload and not updated:
        # Every changed row was withheld or failed: nothing to publish, and
        # the cursor must not advance past unrepaired rows.
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    total_bytes = sum(len(value) for value in payload.values())
    if total_bytes > payload_budget_bytes:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed + len(updated),
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            diagnostics=(
                *diagnostics,
                *withheld_diags,
                f"state repair payload of {total_bytes} bytes exceeds the "
                f"{payload_budget_bytes} byte limit; retry with a smaller limit",
            ),
        )
    try:
        wrote = apply_payload_batched_atomic(
            target.sidecar_path, payload, batch_budget_bytes=payload_budget_bytes
        )
    except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
        clean_agents_payload_worktree(target.sidecar_path, git_runner)
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed + len(updated),
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            diagnostics=(
                *diagnostics,
                *withheld_diags,
                f"state repair failed: {exc}",
            ),
        )
    if not wrote:
        ahead_pushed, push_error, ahead_attempts = _push_ahead_convergence(
            target, git_runner, "agents_state_repair.push_ahead"
        )
        if push_error is not None:
            return StateRepairReport(
                target.project_key,
                target.project,
                mode,
                examined=len(selected),
                changed=0,
                already_current=resolved.already_current,
                live=resolved.live,
                unresolved=resolved.unresolved,
                withheld=withheld,
                failed=failed,
                affected=(),
                window=window,
                next_cursor=None,
                pass_complete=False,
                push_attempts=ahead_attempts,
                error=push_error,
                diagnostics=(*diagnostics, *withheld_diags),
            )
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current + len(resolved.changed),
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=(),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            pushed=ahead_pushed,
            push_attempts=ahead_attempts,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    scope = _protection_scope(target)
    committed = commit_agents_payload_if_dirty(
        target.sidecar_path, owner, git_runner, protection_scope=scope
    )
    if isinstance(committed, str):
        clean_agents_payload_worktree(target.sidecar_path, git_runner)
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed + len(updated),
            affected=(),
            window=window,
            next_cursor=None,
            pass_complete=False,
            error=committed,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    if not committed:
        no_change = len(resolved.changed) - withheld
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=0,
            already_current=resolved.already_current + max(no_change, 0),
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=(),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    should_push = committed or agents_ahead_count(target.sidecar_path, git_runner) > 0
    if not should_push:  # pragma: no cover - commit implies push
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=len(updated),
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=tuple(resolved.changed.values()),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            committed=True,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    pushed = git_runner(target.sidecar_path, ["push"], network=True, op=push_op)
    if pushed.returncode == 0:
        return StateRepairReport(
            target.project_key,
            target.project,
            mode,
            examined=len(selected),
            changed=len(updated),
            already_current=resolved.already_current,
            live=resolved.live,
            unresolved=resolved.unresolved,
            withheld=withheld,
            failed=failed,
            affected=tuple(
                item for key, item in resolved.changed.items() if key in updated
            ),
            window=window,
            next_cursor=next_cursor,
            pass_complete=pass_complete,
            committed=True,
            pushed=True,
            push_attempts=1,
            diagnostics=(*diagnostics, *withheld_diags),
        )
    from sase.agents_sync.publication_recovery import (
        RECOVERY_RETRY_DIVERGENCE,
        recover_publication_push,
    )

    recovery = recover_publication_push(
        target.sidecar_path,
        git_runner,
        project_key=target.project_key,
        repository_identity=target.remote_url,
        returncode=pushed.returncode,
        stdout=pushed.stdout or "",
        stderr=pushed.stderr or "",
    )
    if (
        allow_retry
        and recovery.action == RECOVERY_RETRY_DIVERGENCE
        and is_agents_non_fast_forward(pushed)
    ):
        dropped = git_runner(
            target.sidecar_path,
            ["reset", "--hard", "HEAD^"],
            op="agents_state_repair.retry_drop_commit",
        )
        if dropped.returncode != 0:
            return StateRepairReport(
                target.project_key,
                target.project,
                mode,
                examined=len(selected),
                changed=0,
                already_current=resolved.already_current,
                live=resolved.live,
                unresolved=resolved.unresolved,
                withheld=withheld,
                failed=failed + len(updated),
                affected=(),
                window=window,
                next_cursor=None,
                pass_complete=False,
                push_attempts=1,
                error=agents_git_error(
                    "could not prepare rejected state repair for retry", dropped
                ),
                diagnostics=(*diagnostics, *withheld_diags),
            )
        # Discard stale planning caches and recompute from the new upstream:
        # the retry never replays a stale precomputed state patch.
        cleanup_error = clean_agents_payload_worktree(target.sidecar_path, git_runner)
        if cleanup_error is not None:
            return StateRepairReport(
                target.project_key,
                target.project,
                mode,
                examined=len(selected),
                changed=0,
                already_current=resolved.already_current,
                live=resolved.live,
                unresolved=resolved.unresolved,
                withheld=withheld,
                failed=failed + len(updated),
                affected=(),
                window=window,
                next_cursor=None,
                pass_complete=False,
                push_attempts=1,
                error=cleanup_error,
                diagnostics=(*diagnostics, *withheld_diags),
            )
        from sase.agents_sync.publication_planning import (
            invalidate_shared_targeted_planning,
        )

        invalidate_shared_targeted_planning(target.sidecar_path)
        invalidate_shared_targeted_planning()
        repulled = pull_agents_rebase(
            target.sidecar_path, git_runner, "agents_state_repair.retry_pull"
        )
        if repulled.returncode != 0:
            cleanup = abort_agents_rebase(target.sidecar_path, git_runner)
            return StateRepairReport(
                target.project_key,
                target.project,
                mode,
                examined=len(selected),
                changed=0,
                already_current=resolved.already_current,
                live=resolved.live,
                unresolved=resolved.unresolved,
                withheld=withheld,
                failed=failed + len(updated),
                affected=(),
                window=window,
                next_cursor=None,
                pass_complete=False,
                push_attempts=1,
                error=agents_git_error(
                    "git pull --rebase retry failed", repulled, cleanup
                ),
                diagnostics=(*diagnostics, *withheld_diags),
            )
        retry = _plan_and_push_repair(
            target,
            owner,
            state_limit=state_limit,
            state_after=state_after,
            git_runner=git_runner,
            inventory_loader=inventory_loader,
            deadline=deadline,
            payload_budget_bytes=payload_budget_bytes,
            push_op="agents_state_repair.retry_push",
            allow_retry=False,
        )
        return StateRepairReport(
            retry.project_key,
            retry.project,
            retry.mode,
            examined=retry.examined,
            changed=retry.changed,
            already_current=retry.already_current,
            live=retry.live,
            unresolved=retry.unresolved,
            withheld=retry.withheld,
            failed=retry.failed,
            affected=retry.affected,
            window=retry.window,
            next_cursor=retry.next_cursor,
            pass_complete=retry.pass_complete,
            committed=retry.committed,
            pushed=retry.pushed,
            push_attempts=retry.push_attempts + 1,
            skip_reason=retry.skip_reason,
            error=retry.error,
            diagnostics=(*diagnostics, *withheld_diags, *retry.diagnostics),
        )
    from sase.agents_sync.publication_recovery import sanitized_push_error

    message = sanitized_push_error(
        "git push failed",
        recovery.rejection,
        blocked_paths=recovery.blocked_paths,
    )
    return StateRepairReport(
        target.project_key,
        target.project,
        mode,
        examined=len(selected),
        changed=0,
        already_current=resolved.already_current,
        live=resolved.live,
        unresolved=resolved.unresolved,
        withheld=withheld,
        failed=failed + len(updated),
        affected=(),
        window=window,
        next_cursor=None,
        pass_complete=False,
        push_attempts=1,
        error=message,
        diagnostics=(*diagnostics, *withheld_diags),
    )


def _plan_state_payload(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    resolved: _ResolvedWindow,
    deadline: float,
    *,
    bad_hoods: frozenset[str] = frozenset(),
) -> tuple[
    dict[str, bytes],
    dict[tuple[str, str], StateRepairAffected],
    int,
    tuple[str, ...],
    int,
    tuple[str, ...],
]:
    from sase.agents_sync.publication_protection import PublicationProtectionScope

    scope = PublicationProtectionScope(
        project_key=target.project_key,
        repository_identity=target.remote_url,
    )
    by_hood: dict[str, list[tuple[str, StateRepairAffected]]] = {}
    for key, affected in resolved.changed.items():
        by_hood.setdefault(key[0], []).append((key[1], affected))
    payload: dict[str, bytes] = {}
    updated: dict[tuple[str, str], StateRepairAffected] = {}
    withheld = 0
    withheld_diags: list[str] = []
    failed = 0
    diagnostics: list[str] = []
    changed_snapshots: dict[tuple[str, str, str], V2HoodSnapshot] = {}
    for hood in sorted(by_hood):
        if time.monotonic() > deadline:
            failed += len(by_hood[hood])
            diagnostics.append(
                f"hood {hood!r}: state repair work budget exceeded; "
                "retry the window with a smaller limit"
            )
            continue
        try:
            snapshot = _read_validated_snapshot(
                target.sidecar_path,
                owner,
                hood,
                V2ProjectIdentity(target.project_key, target.project),
            )
        except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
            failed += len(by_hood[hood])
            diagnostics.append(f"hood {hood!r} is not repairable: {exc}")
            continue
        by_id = {run.source_run_id: run for run in snapshot.runs}
        replacements: dict[str, V2RunRecord] = {}
        hood_ok = True
        for run_id, affected in sorted(by_hood[hood]):
            pending = resolved.pending.get((hood, run_id))
            current = by_id.get(run_id)
            if pending is None or current is None:  # pragma: no cover - defensive
                failed += 1
                diagnostics.append(
                    f"{affected.global_name}: published run is no longer present"
                )
                hood_ok = False
                continue
            _record, started_at, finished_at = pending
            if affected.selected_state == "dismissed":
                dismissed_at = current.dismissed_at or finished_at
            else:
                dismissed_at = None
            state_payload = V2RunStatePayload(
                run_id,
                affected.selected_state,  # type: ignore[arg-type]
                started_at,
                finished_at,
                dismissed_at,
            )
            try:
                state_bytes = v2_json_bytes(state_payload.to_json_dict())
            except (TypeError, ValueError) as exc:
                failed += 1
                diagnostics.append(
                    f"{affected.global_name}: state payload is not encodable: {exc}"
                )
                continue
            if len(state_bytes) > scope.max_bytes:
                withheld += 1
                withheld_diags.append(
                    f"{affected.global_name}: state payload exceeds the "
                    "publication byte bound; withheld"
                )
                continue
            if not _state_bytes_publishable(
                state_bytes,
                f"agents/{affected.global_name}/state.json",
                scope,
                target,
                withheld_diags,
                affected.global_name,
            ):
                withheld += 1
                continue
            reference = file_reference(
                f"agents/{affected.global_name}/state.json", state_bytes
            )
            files = tuple(
                (kind, reference if kind == "state" else ref)
                for kind, ref in current.files
            )
            if "state" not in {kind for kind, _ref in files}:
                files = (*files, ("state", reference))
            replacements[run_id] = V2RunRecord(
                current.source_run_id,
                current.local_name,
                current.global_name,
                affected.selected_state,  # type: ignore[arg-type]
                started_at,
                finished_at,
                dismissed_at,
                current.metadata,
                current.commits,
                files,
                current.capabilities,
            )
            payload[f"agents/{affected.global_name}/state.json"] = state_bytes
        if not replacements:
            continue
        runs = tuple(replacements.get(run.source_run_id, run) for run in snapshot.runs)
        runs = tuple(sorted(runs, key=lambda item: item.source_run_id))
        updated_snapshot = V2HoodSnapshot(
            snapshot.owner,
            snapshot.project,
            snapshot.local_hood,
            snapshot.global_hood,
            snapshot.structural_ancestors,
            runs,
            snapshot.containers,
            snapshot.relationships,
        )
        try:
            from sase.agents_sync.v2_io import validate_snapshot

            validate_snapshot(updated_snapshot)
            snapshot_bytes = v2_json_bytes(updated_snapshot.to_json_dict())
        except (AgentsSyncFormatError, RuntimeError, ValueError) as exc:
            failed += len(replacements)
            diagnostics.append(f"hood {hood!r} repair snapshot is not valid: {exc}")
            for run_id in replacements:
                payload.pop(f"agents/{by_id[run_id].global_name}/state.json", None)
            continue
        if len(snapshot_bytes) > MAX_JSON_BYTES:
            failed += len(replacements)
            diagnostics.append(
                f"hood {hood!r} repair snapshot exceeds the JSON byte limit"
            )
            for run_id in replacements:
                payload.pop(f"agents/{by_id[run_id].global_name}/state.json", None)
            continue
        from sase.agents_sync.publication_validation import snapshot_path

        payload[snapshot_path(owner, hood)] = snapshot_bytes
        changed_snapshots[(owner.username, owner.machine_name, hood)] = updated_snapshot
        for run_id, affected in by_hood[hood]:
            if run_id in replacements:
                updated[(hood, run_id)] = affected
        if not hood_ok:
            diagnostics.append(f"hood {hood!r}: partially repaired")
    if not changed_snapshots:
        return (
            payload,
            updated,
            withheld,
            tuple(withheld_diags),
            failed,
            tuple(diagnostics),
        )
    try:
        manifest_payload, manifest_diags = _plan_manifest_and_pages(
            target, owner, changed_snapshots, payload, skip_hoods=bad_hoods
        )
    except (AgentsSyncFormatError, OSError, RuntimeError, ValueError) as exc:
        return (
            {},
            {},
            withheld,
            tuple(withheld_diags),
            failed + len(updated),
            (
                *diagnostics,
                f"state repair manifest is not writable: {exc}",
            ),
        )
    payload.update(manifest_payload)
    diagnostics.extend(manifest_diags)
    return payload, updated, withheld, tuple(withheld_diags), failed, tuple(diagnostics)


def _state_bytes_publishable(
    state_bytes: bytes,
    destination: str,
    scope: PublicationProtectionScope,
    target: ProjectTarget,
    withheld_diags: list[str],
    global_name: str,
) -> bool:
    from sase.agents_sync.publication_protection import (
        lookup_publication_content_record,
        record_publication_bytes_scan,
        scan_publication_bytes,
    )

    import hashlib

    try:
        record = lookup_publication_content_record(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=destination,
            sha256=hashlib.sha256(state_bytes).hexdigest(),
        )
    except Exception:  # noqa: BLE001 - a failed lookup never authorizes publish.
        record = None
    if isinstance(record, dict) and record.get("status") == "blocked":
        withheld_diags.append(f"{global_name}: state payload is blocked; withheld")
        return False
    verdict = scan_publication_bytes(state_bytes, max_bytes=scope.max_bytes)
    try:
        record_publication_bytes_scan(
            scope.project_key,
            repository_identity=scope.repository_identity,
            relative_destination=destination,
            verdict=verdict,
        )
    except Exception:  # noqa: BLE001 - the scan verdict still withholds.
        withheld_diags.append(
            f"protection ledger unavailable for {global_name}; "
            "withholding on the scan verdict alone"
        )
    if not verdict.is_publishable:
        status = verdict.disposition.get("status") if verdict.disposition else None
        reason = "blocked" if status == "blocked" else "unverified"
        withheld_diags.append(f"{global_name}: state payload {reason}; withheld")
        return False
    return True


def _plan_manifest_and_pages(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    changed_snapshots: dict[tuple[str, str, str], V2HoodSnapshot],
    payload: dict[str, bytes],
    *,
    skip_hoods: frozenset[str] = frozenset(),
) -> tuple[dict[str, bytes], tuple[str, ...]]:
    from sase.agents_sync.bead_links import build_bead_page_links
    from sase.agents_sync.publication_validation import load_validated_publication
    from sase.agents_sync.rendering import render_targeted_browsing_payload
    from sase.agents_sync.v2_io import (
        check_manifest_write_size,
        owner_manifest_path,
        read_owner_manifest,
        v2_schema_document,
    )

    project = V2ProjectIdentity(target.project_key, target.project)
    previous_manifest = read_owner_manifest(target.sidecar_path, owner, project)
    entries = dict(previous_manifest.by_hood())
    for (username, machine, hood), snapshot in changed_snapshots.items():
        assert (username, machine) == (owner.username, owner.machine_name)
        snapshot_bytes = payload[
            f"users/{username}/machines/{machine}/hoods/{hood}/snapshot.json"
        ]
        entries[hood] = V2OwnerHoodEntry(
            content_digest(snapshot_bytes),
            None,
            len(snapshot.runs),
            sum(is_session_container(item.kind) for item in snapshot.containers),
        )
    manifest = V2OwnerManifest(owner, project, tuple(sorted(entries.items())))
    manifest_bytes = v2_json_bytes(manifest.to_json_dict())
    check_manifest_write_size(len(manifest.hoods), manifest_bytes)
    extra: dict[str, bytes] = {
        "schema.json": v2_json_bytes(v2_schema_document()),
        "agents/.gitkeep": b"",
        "families/.gitkeep": b"",
        "sessions/.gitkeep": b"",
        owner_manifest_path(owner): manifest_bytes,
    }
    if skip_hoods:
        return _plan_manifest_and_pages_degraded(
            target,
            owner,
            project,
            manifest,
            changed_snapshots,
            {**payload, **extra},
            skip_hoods,
        )
    manifests, snapshots, diagnostics = load_validated_publication(
        target.sidecar_path,
        override_manifest=manifest,
        override_snapshots=dict(changed_snapshots),
        override_payload={**payload, **extra},
    )
    selected_keys = frozenset(changed_snapshots)
    bead_links, bead_diagnostics = build_bead_page_links(
        tuple(snapshots[key] for key in sorted(selected_keys) if key in snapshots),
        primary_root=target.primary_checkout,
        project=target.project,
    )
    # Targeted rendering keeps complete manifests but writes only affected
    # hood, agent, session, and index pages; unrelated pages are omitted.
    pages = render_targeted_browsing_payload(
        manifests,
        snapshots,
        selected_keys,
        bead_links=bead_links,
    )
    return {**extra, **pages}, (*diagnostics, *bead_diagnostics)


def _plan_manifest_and_pages_degraded(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    manifest: V2OwnerManifest,
    changed_snapshots: dict[tuple[str, str, str], V2HoodSnapshot],
    payload: dict[str, bytes],
    skip_hoods: frozenset[str],
) -> tuple[dict[str, bytes], tuple[str, ...]]:
    """Render repair pages while unreadable sibling hoods stay preserved.

    The written manifest keeps every entry (skipped hoods byte-for-byte), but
    derived browsing pages can only cover readable hoods, so rendering uses a
    filtered manifest. Skipped units stay explicitly failed with their own
    diagnostic; the next full sync restores complete pages.
    """

    from sase.agents_sync.bead_links import build_bead_page_links
    from sase.agents_sync.publication_validation import verify_run_files
    from sase.agents_sync.rendering import render_targeted_browsing_payload
    from sase.agents_sync.v2_io import (
        owner_manifest_from_bytes,
        read_all_owner_manifests_lenient,
        v2_json_bytes,
    )

    from sase.agents_sync.v2_io import validate_snapshot

    for snapshot in changed_snapshots.values():
        validate_snapshot(snapshot)
        for run in snapshot.runs:
            verify_run_files(target.sidecar_path, run, payload)
    owner_manifest_from_bytes(v2_json_bytes(manifest.to_json_dict()))
    healthy: dict[tuple[str, str, str], V2HoodSnapshot] = dict(changed_snapshots)
    for hood, _entry in manifest.hoods:
        key = (owner.username, owner.machine_name, hood)
        if key in healthy or hood in skip_hoods:
            continue
        healthy[key] = _read_validated_snapshot(
            target.sidecar_path, owner, hood, project
        )
    render_manifest = V2OwnerManifest(
        owner,
        project,
        tuple(
            (hood, entry) for hood, entry in manifest.hoods if hood not in skip_hoods
        ),
    )
    other_manifests, lenient_diagnostics = read_all_owner_manifests_lenient(
        target.sidecar_path
    )
    manifests = tuple(
        item
        for item in other_manifests
        if (item.owner.username, item.owner.machine_name)
        != (owner.username, owner.machine_name)
    ) + (render_manifest,)
    snapshots = {
        key: snapshot
        for key, snapshot in healthy.items()
        if key
        not in {(owner.username, owner.machine_name, hood) for hood in skip_hoods}
    }
    selected_keys = frozenset(changed_snapshots)
    bead_links, bead_diagnostics = build_bead_page_links(
        tuple(snapshots[key] for key in sorted(selected_keys) if key in snapshots),
        primary_root=target.primary_checkout,
        project=target.project,
    )
    pages = render_targeted_browsing_payload(
        manifests,
        snapshots,
        selected_keys,
        bead_links=bead_links,
    )
    skipped = ", ".join(sorted(skip_hoods))
    return {**payload, **pages}, (
        *lenient_diagnostics,
        *bead_diagnostics,
        f"browsing pages exclude unreadable hood(s) {skipped}; "
        "manifest entries preserved",
    )


def _protection_scope(target: ProjectTarget) -> PublicationProtectionScope:
    from sase.agents_sync.publication_protection import PublicationProtectionScope

    return PublicationProtectionScope(
        project_key=target.project_key,
        repository_identity=target.remote_url,
    )


__all__ = [
    "REPAIR_STATES_APPLY_COMMAND",
    "REPAIR_STATES_COMMAND",
    "STATE_REPAIR_DEFAULT_LIMIT",
    "STATE_REPAIR_MAX_HOODS",
    "STATE_REPAIR_MAX_LIMIT",
    "STATE_REPAIR_MIN_LIMIT",
    "STATE_REPAIR_SCHEMA_VERSION",
    "STATE_REPAIR_WORK_BUDGET_SECONDS",
    "StateRepairAffected",
    "StateRepairReport",
    "StateRepairWindowRow",
    "repair_agent_run_states",
    "repair_project_run_states",
]
