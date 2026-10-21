"""Re-sign agents-sidecar hood snapshots whose payload has drifted out of band.

An out-of-band rewrite of an already-published payload file (for example a
direct edit to a published ``chat.md``) leaves its ``V2FileReference`` digest
stale inside the hood snapshot that signs it. ``load_validated_publication``
verifies referenced files for the hoods being actively published, so a
drifted file blocks publication of its own hood. The functions here trust the
on-disk payload as correct and re-sign just the stale references and the
owner-manifest digest that covers them, for hoods owned by the local
identity only.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync_ops import (
    agents_git_dir,
    bounded_agents_lock,
    configured_agents_lock_timeout,
    ensure_agents_clone,
)
from sase.agents_sync.git_sync_transaction import sync_project_locked
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import (
    ExportCounts,
    ProjectTarget,
    SyncOutcome,
)
from sase.agents_sync.publication_validation import (
    snapshot_path,
    verify_run_files,
)
from sase.agents_sync.targets import resolve_sync_targets
from sase.agents_sync.v2_io import (
    apply_payload_atomic,
    check_manifest_write_size,
    content_digest,
    file_reference,
    owner_hood_directory_names,
    owner_manifest_path,
    read_hood_snapshot,
    read_owner_manifest,
    v2_json_bytes,
)
from sase.agents_sync.v2_models import (
    V2HoodSnapshot,
    V2OwnerHoodEntry,
    V2ProjectIdentity,
)
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_session_manifest import (
    SESSION_MANIFEST_REPAIR_KEEP,
    SESSION_MANIFEST_REPAIR_NORMALIZE_SLIM,
    SessionManifestRepairDecision,
    repair_session_manifest_entry,
)

REPAIR_DIGESTS_COMMAND = "sase agent sync --repair-digests"
REPAIR_MANIFEST_COMMAND = "sase agent sync --repair-manifest"


def repair_owner_hood_digests(
    target: ProjectTarget,
    repo_root: Path,
    owner: AgentOwnerIdentity,
) -> tuple[dict[str, bytes], tuple[str, ...]]:
    """Re-derive stale file references in ``owner``'s hood snapshots.

    Trusts already-published payload bytes on disk and recomputes only the
    drifted ``V2FileReference`` entries plus the manifest digest that signs
    them. Reads and writes exactly one path family:
    ``users/{owner.username}/machines/{owner.machine_name}/...``; another
    owner's manifest or snapshots are never opened. Returns an empty payload
    and an empty report when nothing has drifted.
    """

    project = V2ProjectIdentity(target.project_key, target.project)
    manifest = read_owner_manifest(repo_root, owner, project)
    payload: dict[str, bytes] = {}
    resigned: list[str] = []
    updated_hoods: dict[str, V2OwnerHoodEntry] = {}
    for hood, entry in manifest.hoods:
        relative = snapshot_path(owner, hood)
        snapshot = read_hood_snapshot(repo_root / relative)
        repaired, drifted = _repair_snapshot(repo_root, snapshot)
        if not drifted:
            continue
        snapshot_bytes = v2_json_bytes(repaired.to_json_dict())
        payload[relative] = snapshot_bytes
        updated_hoods[hood] = replace(
            entry,
            digest=content_digest(snapshot_bytes),
            files=None,
        )
        resigned.extend(f"{hood}: {path}" for path in drifted)
    if not updated_hoods:
        return {}, ()
    new_manifest = replace(
        manifest,
        hoods=tuple(
            sorted(
                (hood, updated_hoods.get(hood, entry)) for hood, entry in manifest.hoods
            )
        ),
    )
    manifest_bytes = v2_json_bytes(new_manifest.to_json_dict())
    check_manifest_write_size(len(new_manifest.hoods), manifest_bytes)
    payload[owner_manifest_path(owner)] = manifest_bytes
    return payload, tuple(resigned)


def _repair_snapshot(
    repo_root: Path,
    snapshot: V2HoodSnapshot,
) -> tuple[V2HoodSnapshot, tuple[str, ...]]:
    drifted: list[str] = []
    new_runs = []
    for run in snapshot.runs:
        new_files = []
        for kind, reference in run.files:
            content = (repo_root / reference.path).read_bytes()
            actual = file_reference(reference.path, content)
            if actual != reference:
                drifted.append(reference.path)
            new_files.append((kind, actual))
        new_runs.append(replace(run, files=tuple(new_files)))
    if not drifted:
        return snapshot, ()
    return replace(snapshot, runs=tuple(new_runs)), tuple(drifted)


def _repair_owner_manifest(
    target: ProjectTarget,
    repo_root: Path,
    owner: AgentOwnerIdentity,
) -> tuple[dict[str, bytes], tuple[str, ...]]:
    """Repair stale explicit file lists and recover omitted hood entries.

    A stale explicit list is redundant, but it is normalized only after the
    snapshot digest and identity, path policy, and every referenced payload
    have been verified. Missing hood entries retain their recovery behavior.
    Corrupt or unsafe candidates are reported and left untouched. Reads and
    writes are confined to ``users/{owner.username}/machines/{owner.machine_name}/``;
    another owner's manifest or snapshots are never opened. Returns an empty
    payload when no valid candidate needs repair.
    """

    project = V2ProjectIdentity(target.project_key, target.project)
    manifest = read_owner_manifest(repo_root, owner, project)
    existing = manifest.by_hood()
    report: list[str] = []
    updated = dict(existing)
    for hood, entry in sorted(existing.items()):
        if entry.files is None:
            continue
        try:
            repaired = _repair_explicit_hood_entry(
                repo_root, owner, project, hood, entry
            )
        except (AgentsSyncFormatError, OSError, ValueError) as exc:
            report.append(f"{hood}: skipped explicit-list repair: {exc}")
            continue
        if repaired is not None:
            updated[hood] = repaired
            report.append(f"{hood}: repaired stale explicit file list")

    for hood in owner_hood_directory_names(repo_root, owner):
        if hood in existing:
            continue
        try:
            updated[hood] = _recovered_hood_entry(repo_root, owner, project, hood)
        except (AgentsSyncFormatError, OSError, ValueError) as exc:
            report.append(f"{hood}: skipped recovery: {exc}")
            continue
        report.append(f"{hood}: recovered")
    if updated == existing:
        return {}, tuple(report)
    new_manifest = replace(manifest, hoods=tuple(sorted(updated.items())))
    manifest_bytes = v2_json_bytes(new_manifest.to_json_dict())
    check_manifest_write_size(len(new_manifest.hoods), manifest_bytes)
    payload = {owner_manifest_path(owner): manifest_bytes}
    return payload, tuple(report)


def _recovered_hood_entry(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    hood: str,
) -> V2OwnerHoodEntry:
    relative = snapshot_path(owner, hood)
    snapshot_bytes = (repo_root / relative).read_bytes()
    snapshot = read_hood_snapshot(repo_root / relative)
    _require_repair_snapshot_identity(snapshot, owner, project, hood)
    decision = _manifest_repair_decision(snapshot, explicit_files=None)
    if decision.action != SESSION_MANIFEST_REPAIR_NORMALIZE_SLIM:
        raise AgentsSyncFormatError(
            f"hood {hood!r} snapshot cannot be normalized: {decision.reason}"
        )
    for run in snapshot.runs:
        verify_run_files(repo_root, run)
    decision = _manifest_repair_decision(snapshot, explicit_files=None)
    return V2OwnerHoodEntry(
        content_digest(snapshot_bytes),
        None,
        decision.run_count,
        decision.agent_session_count,
    )


def _repair_explicit_hood_entry(
    repo_root: Path,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    hood: str,
    entry: V2OwnerHoodEntry,
) -> V2OwnerHoodEntry | None:
    relative = snapshot_path(owner, hood)
    snapshot_bytes = (repo_root / relative).read_bytes()
    if content_digest(snapshot_bytes) != entry.digest:
        raise AgentsSyncFormatError(f"hood {hood!r} snapshot digest mismatch")
    snapshot = read_hood_snapshot(repo_root / relative)
    _require_repair_snapshot_identity(snapshot, owner, project, hood)
    decision = _manifest_repair_decision(snapshot, explicit_files=entry.files)
    if decision.action == SESSION_MANIFEST_REPAIR_KEEP:
        return None
    if decision.action != SESSION_MANIFEST_REPAIR_NORMALIZE_SLIM:
        raise AgentsSyncFormatError(
            f"explicit file list is unsafe to repair: {decision.reason}"
        )
    for run in snapshot.runs:
        verify_run_files(repo_root, run)
    decision = _manifest_repair_decision(snapshot, explicit_files=entry.files)
    if decision.action != SESSION_MANIFEST_REPAIR_NORMALIZE_SLIM:
        raise AgentsSyncFormatError(
            f"explicit file list changed during repair: {decision.reason}"
        )
    return V2OwnerHoodEntry(
        content_digest(snapshot_bytes),
        None,
        decision.run_count,
        decision.agent_session_count,
    )


def _manifest_repair_decision(
    snapshot: V2HoodSnapshot,
    *,
    explicit_files: tuple[str, ...] | None,
) -> SessionManifestRepairDecision:
    return repair_session_manifest_entry(
        owner_username=snapshot.owner.username,
        owner_machine=snapshot.owner.machine_name,
        local_hood=snapshot.local_hood,
        run_global_names=tuple(run.global_name for run in snapshot.runs),
        run_file_paths=tuple(
            reference.path for run in snapshot.runs for _kind, reference in run.files
        ),
        containers=tuple(
            (container.kind, container.global_name) for container in snapshot.containers
        ),
        explicit_files=explicit_files,
    )


def _require_repair_snapshot_identity(
    snapshot: V2HoodSnapshot,
    owner: AgentOwnerIdentity,
    project: V2ProjectIdentity,
    hood: str,
) -> None:
    if (
        snapshot.owner != owner
        or snapshot.project != project
        or snapshot.local_hood != hood
    ):
        raise AgentsSyncFormatError(f"hood {hood!r} snapshot identity mismatch")


def _repair_project_hood_digests(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> SyncOutcome:
    """Repair one project's locally owned hood-snapshot digests under lock."""

    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    if not target.primary_checkout.is_dir():
        return SyncOutcome(
            target.project_key,
            target.project,
            error="primary checkout does not exist",
        )
    clone_error = ensure_agents_clone(
        target, git_runner=git_runner, lock_timeout_seconds=timeout
    )
    if clone_error is not None:
        if clone_error == "agents sync clone lock is busy":
            return SyncOutcome(
                target.project_key, target.project, skip_reason=clone_error
            )
        return SyncOutcome(target.project_key, target.project, error=clone_error)

    lock_path = (
        agents_git_dir(target.sidecar_path, git_runner) / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return SyncOutcome(
                target.project_key,
                target.project,
                skip_reason="agents sync lock is busy",
            )
        return sync_project_locked(target, owner, git_runner, _repair_pass)


def _repair_project_owner_manifest(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> SyncOutcome:
    """Repair one project's owner-manifest coverage of on-disk hoods under lock."""

    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    if not target.primary_checkout.is_dir():
        return SyncOutcome(
            target.project_key,
            target.project,
            error="primary checkout does not exist",
        )
    clone_error = ensure_agents_clone(
        target, git_runner=git_runner, lock_timeout_seconds=timeout
    )
    if clone_error is not None:
        if clone_error == "agents sync clone lock is busy":
            return SyncOutcome(
                target.project_key, target.project, skip_reason=clone_error
            )
        return SyncOutcome(target.project_key, target.project, error=clone_error)

    lock_path = (
        agents_git_dir(target.sidecar_path, git_runner) / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(lock_path, timeout) as acquired:
        if not acquired:
            return SyncOutcome(
                target.project_key,
                target.project,
                skip_reason="agents sync lock is busy",
            )
        return sync_project_locked(target, owner, git_runner, _repair_manifest_pass)


def _repair_manifest_pass(
    target: ProjectTarget,
    repo: Path,
    owner: AgentOwnerIdentity,
    _git_runner: GitRunner,
) -> ExportCounts:
    payload, report = _repair_owner_manifest(target, repo, owner)
    if payload:
        apply_payload_atomic(repo, payload)
    return ExportCounts(diagnostics=report)


def repair_agent_owner_manifests(
    projects: tuple[str, ...] = (),
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> tuple[SyncOutcome, ...]:
    """Repair owner-manifest coverage of on-disk hoods across selected projects."""

    selection = resolve_sync_targets(projects)
    outcomes = list(selection.outcomes)
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        outcomes.extend(
            SyncOutcome(
                target.project_key,
                target.project,
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(outcomes, key=lambda item: item.project_key))

    for target in selection.targets:
        try:
            outcomes.append(
                _repair_project_owner_manifest(
                    target,
                    owner,
                    git_runner=git_runner,
                    lock_timeout_seconds=lock_timeout_seconds,
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-project isolation contract
            outcomes.append(
                SyncOutcome(
                    target.project_key,
                    target.project,
                    error=f"agents manifest repair failed: {exc}",
                )
            )
    return tuple(sorted(outcomes, key=lambda item: item.project_key))


def _repair_pass(
    target: ProjectTarget,
    repo: Path,
    owner: AgentOwnerIdentity,
    _git_runner: GitRunner,
) -> ExportCounts:
    payload, resigned = repair_owner_hood_digests(target, repo, owner)
    if payload:
        apply_payload_atomic(repo, payload)
    return ExportCounts(diagnostics=resigned)


def repair_agent_hood_digests(
    projects: tuple[str, ...] = (),
    *,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> tuple[SyncOutcome, ...]:
    """Repair locally owned hood-snapshot digests across selected projects."""

    selection = resolve_sync_targets(projects)
    outcomes = list(selection.outcomes)
    try:
        owner = require_agent_owner_identity()
    except (RuntimeError, ValueError) as exc:
        outcomes.extend(
            SyncOutcome(
                target.project_key,
                target.project,
                error=f"owner identity is not configured: {exc}",
            )
            for target in selection.targets
        )
        return tuple(sorted(outcomes, key=lambda item: item.project_key))

    for target in selection.targets:
        try:
            outcomes.append(
                _repair_project_hood_digests(
                    target,
                    owner,
                    git_runner=git_runner,
                    lock_timeout_seconds=lock_timeout_seconds,
                )
            )
        except Exception as exc:  # noqa: BLE001 - per-project isolation contract
            outcomes.append(
                SyncOutcome(
                    target.project_key,
                    target.project,
                    error=f"agents digest repair failed: {exc}",
                )
            )
    return tuple(sorted(outcomes, key=lambda item: item.project_key))


__all__ = [
    "REPAIR_DIGESTS_COMMAND",
    "REPAIR_MANIFEST_COMMAND",
    "repair_agent_hood_digests",
    "repair_agent_owner_manifests",
    "repair_owner_hood_digests",
]
