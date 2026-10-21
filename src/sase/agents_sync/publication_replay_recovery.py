"""Backup-first stale-replay recovery for unpublished sidecar commits.

This is a finite recovery helper, not a normal drain. It inventories unique
owner data outside the clone, classifies conflicting files through Rust,
regenerates browsing pages on current upstream, and reapplies preserved
owner snapshots through the existing sidecar transaction callback.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from json import loads
from pathlib import Path
import shutil
from typing import Any

from sase.agents_sync.git import GitRunner, run_git
from sase.agents_sync.git_sync_ops import (
    abort_agents_rebase,
    agents_ahead_count,
    agents_git_dir,
    agents_git_error,
    bounded_agents_lock,
    configured_agents_lock_timeout,
    ensure_agents_clone,
)
from sase.agents_sync.git_sync_transaction import sync_project_locked
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.inventory_models import InventoryRelationship
from sase.agents_sync.io import AgentsSyncFormatError, atomic_write_json
from sase.agents_sync.models import ExportCounts, ProjectTarget, SyncOutcome
from sase.agents_sync.prompt_archive.archive_objects import ARCHIVE_OBJECT_ROOT
from sase.agents_sync.publication_planning import plan_targeted_hoods
from sase.agents_sync.publication_validation import snapshot_path
from sase.agents_sync.targets import resolve_sync_targets
from sase.agents_sync.v2_io import apply_payload_atomic, read_hood_snapshot
from sase.agents_sync.v2_models import V2HoodSnapshot
from sase.agents_sync.v2_snapshot_io import decode_hood_snapshot
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
    REPLAY_APPLY_ACTION_ALREADY_COMPLETE,
    REPLAY_APPLY_ACTION_APPLY,
    REPLAY_APPLY_ACTION_REFUSE,
    REPLAY_APPLY_ACTION_REPORT,
    REPLAY_BYTES_KEEP_CURRENT,
    REPLAY_BYTES_KEEP_PREVIOUS,
    REPLAY_BYTES_REFUSE,
    REPLAY_HOOD_ACTION_MERGE,
    ReplayApplyDecision,
    ReplayByteDivergenceDecision,
    ReplayHoodMergeDecision,
    ReplayPathClassification,
    classify_replay_paths,
    decide_replay_apply,
    decide_replay_byte_divergence,
    decide_replay_hood_merge,
)
from sase.plan_chain import AGENT_SESSION_KEY, agent_session_value

PROGRESS_NAME = "progress.json"
CHECKSUMS_NAME = "checksums.json"
REVISIONS_NAME = "revisions.json"
BUNDLE_NAME = "unpublished.bundle"
PRESERVED_DIR = "preserved"
OBJECTS_DIR = "objects"
_MUTATION_STAGES = frozenset({"reset", "replaying"})
_COMPLETE_STAGE = "complete"
_VERIFIED_STAGE = "verified"


# symvision: tools/agents_publication_recover_replay
@dataclass(frozen=True, slots=True)
class ReplayRecoveryReport:
    """Preservation inventory and optional transaction outcome."""

    project_key: str
    observed_head: str
    expected_head: str
    upstream: str
    ahead: int
    behind: int
    stage: str
    action: str
    already_complete: bool
    apply: bool
    error: str | None
    browsing_paths: tuple[str, ...]
    owner_content_paths: tuple[str, ...]
    archive_object_paths: tuple[str, ...]
    unknown_paths: tuple[str, ...]
    preserved_hoods: tuple[str, ...]
    refused_divergences: tuple[str, ...]
    backup_dir: str
    outcome: SyncOutcome | None = None


# symvision: tools/agents_publication_recover_replay
def recover_stale_replay(
    *,
    expected_head: str,
    backup_dir: Path,
    project: str | None = None,
    target: ProjectTarget | None = None,
    apply: bool = False,
    owner: AgentOwnerIdentity | None = None,
    git_runner: GitRunner = run_git,
    lock_timeout_seconds: float | None = None,
) -> ReplayRecoveryReport:
    """Inventory, back up, and optionally replay one project's stale commit."""

    resolved_owner = owner or require_agent_owner_identity()
    resolved_target = target or _resolve_project_target(project)
    timeout = (
        configured_agents_lock_timeout()
        if lock_timeout_seconds is None
        else max(lock_timeout_seconds, 0.0)
    )
    backup_root = backup_dir.expanduser().resolve()
    backup_root.mkdir(parents=True, exist_ok=True)
    if not resolved_target.primary_checkout.is_dir():
        return _error_report(
            resolved_target,
            expected_head,
            backup_root,
            apply,
            "primary checkout does not exist",
        )
    clone_error = ensure_agents_clone(
        resolved_target, git_runner=git_runner, lock_timeout_seconds=timeout
    )
    if clone_error is not None:
        return _error_report(
            resolved_target, expected_head, backup_root, apply, clone_error
        )
    lock_path = (
        agents_git_dir(resolved_target.sidecar_path, git_runner)
        / "sase-agents-sync.lock"
    )
    with bounded_agents_lock(
        lock_path, timeout, operation="agents_sync.replay_recovery"
    ) as acquired:
        if not acquired:
            return _error_report(
                resolved_target,
                expected_head,
                backup_root,
                apply,
                "agents sync lock is busy",
            )
        return _recover_locked(
            resolved_target,
            resolved_owner,
            expected_head,
            backup_root,
            apply,
            git_runner,
        )


def _recover_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    expected_head: str,
    backup_root: Path,
    apply: bool,
    git_runner: GitRunner,
) -> ReplayRecoveryReport:
    repo = target.sidecar_path
    fetched = git_runner(repo, ["fetch"], network=True, op="agents_sync.replay_fetch")
    if fetched.returncode != 0:
        return _error_report(
            target,
            expected_head,
            backup_root,
            apply,
            agents_git_error(
                "could not fetch upstream before replay recovery", fetched
            ),
        )
    observed = _observe_clone(repo, git_runner)
    progress = _read_progress(backup_root)
    already_complete = (
        progress is not None
        and progress.get("stage") == _COMPLETE_STAGE
        and str(progress.get("expected_head", "")) == expected_head
    )
    mutation_started = bool(
        progress is not None and progress.get("stage") in _MUTATION_STAGES
    )
    classified: ReplayPathClassification | None = None
    refused: tuple[str, ...] = ()
    hoods: tuple[str, ...] = ()
    if not already_complete and mutation_started and progress is not None:
        classified, hoods = _classified_from_progress(progress)
        refused = tuple(str(item) for item in progress.get("refused") or ())
    elif not already_complete:
        paths = _collect_paths(repo, git_runner)
        classified = classify_replay_paths(paths)
        hoods = _owner_hoods(classified.owner_content, owner)
        refused = _refused_same_run_divergences(
            repo, owner, hoods, classified.owner_content, git_runner
        )
        try:
            _ensure_backup(
                repo,
                backup_root,
                expected_head,
                observed,
                classified,
                hoods,
                refused,
                git_runner,
            )
        except AgentsSyncFormatError as exc:
            return _error_report(
                target,
                expected_head,
                backup_root,
                apply,
                str(exc),
                observed=observed,
                classified=classified,
                hoods=hoods,
                refused=refused,
            )
        progress = _read_progress(backup_root)
    verified, verify_error = _verify_backup(backup_root)
    backup_complete = progress is not None and progress.get("stage") in {
        _VERIFIED_STAGE,
        *_MUTATION_STAGES,
        _COMPLETE_STAGE,
    }
    decision: ReplayApplyDecision = decide_replay_apply(
        apply=apply,
        observed_head=observed["head"],
        expected_head=expected_head,
        backup_complete=bool(backup_complete),
        backup_verified=verified,
        unreconcilable=bool(refused) or bool(classified and classified.unknown),
        already_complete=already_complete,
        mutation_started=mutation_started,
    )
    report = _report_from_state(
        target,
        expected_head,
        backup_root,
        apply,
        observed,
        progress,
        classified,
        hoods,
        refused,
        decision.action,
        None,
    )
    if decision.action == REPLAY_APPLY_ACTION_REFUSE:
        return replace(report, error=decision.reason)
    if decision.action == REPLAY_APPLY_ACTION_ALREADY_COMPLETE:
        return replace(report, already_complete=True, stage=_COMPLETE_STAGE)
    if decision.action == REPLAY_APPLY_ACTION_REPORT or not apply:
        return report
    if verify_error is not None:
        return replace(report, error=verify_error, action=REPLAY_APPLY_ACTION_REFUSE)
    if decision.action != REPLAY_APPLY_ACTION_APPLY:
        return replace(report, error=decision.reason)
    return _apply_replay(
        target,
        owner,
        expected_head,
        backup_root,
        observed,
        progress or {},
        hoods,
        classified,
        refused,
        git_runner,
        mutation_started,
    )


def _apply_replay(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    expected_head: str,
    backup_root: Path,
    observed: dict[str, Any],
    progress: dict[str, Any],
    hoods: tuple[str, ...],
    classified: ReplayPathClassification | None,
    refused: tuple[str, ...],
    git_runner: GitRunner,
    mutation_started: bool,
) -> ReplayRecoveryReport:
    repo = target.sidecar_path
    if not mutation_started:
        abort_agents_rebase(repo, git_runner)
        reset = git_runner(
            repo,
            ["reset", "--hard", "@{upstream}"],
            op="agents_sync.replay_reset",
        )
        if reset.returncode != 0:
            return _error_report(
                target,
                expected_head,
                backup_root,
                True,
                agents_git_error("could not reset unpublished replay", reset),
                observed=observed,
                classified=classified,
                hoods=hoods,
                refused=refused,
            )
        _write_progress(backup_root, {**progress, "stage": "reset"})
    _restore_pending_objects(repo, backup_root)
    _write_progress(
        backup_root,
        {**(_read_progress(backup_root) or progress), "stage": "replaying"},
    )
    preserved_runs = _runs_from_backup(backup_root, owner, hoods)

    def integrate_export_pass(
        pass_target: ProjectTarget,
        pass_repo: Path,
        pass_owner: AgentOwnerIdentity,
        pass_git_runner: GitRunner,
    ) -> ExportCounts:
        return _replay_export_pass(
            pass_target,
            pass_repo,
            pass_owner,
            pass_git_runner,
            backup_root=backup_root,
            hoods=hoods,
            preserved_runs=preserved_runs,
        )

    outcome = sync_project_locked(target, owner, git_runner, integrate_export_pass)
    if outcome.error:
        return _error_report(
            target,
            expected_head,
            backup_root,
            True,
            outcome.error,
            observed=observed,
            classified=classified,
            hoods=hoods,
            refused=refused,
            outcome=outcome,
        )
    completed_head = _git_text(repo, git_runner, ["rev-parse", "HEAD"], "replay_head")
    _write_progress(
        backup_root,
        {
            **(_read_progress(backup_root) or progress),
            "stage": _COMPLETE_STAGE,
            "completed_head": completed_head,
        },
    )
    return replace(
        _report_from_state(
            target,
            expected_head,
            backup_root,
            True,
            observed,
            _read_progress(backup_root),
            classified,
            hoods,
            refused,
            REPLAY_APPLY_ACTION_APPLY,
            outcome,
        ),
        stage=_COMPLETE_STAGE,
    )


def _replay_export_pass(
    target: ProjectTarget,
    repo: Path,
    owner: AgentOwnerIdentity,
    git_runner: GitRunner,
    *,
    backup_root: Path,
    hoods: tuple[str, ...],
    preserved_runs: tuple[InventoryRun, ...],
) -> ExportCounts:
    del git_runner
    live_runs: list[InventoryRun] = []
    for hood in hoods:
        snapshot_file = repo / snapshot_path(owner, hood)
        if not snapshot_file.is_file():
            continue
        live_runs.extend(_runs_from_snapshot(read_hood_snapshot(snapshot_file), repo))
    merged = _merge_runs(preserved_runs, tuple(live_runs), repo, backup_root)
    if not merged:
        return ExportCounts()
    inventory = ProjectHoodInventory(owner, target.project_key, merged)
    selected = hoods or inventory.eligible_hoods()
    payload, published = plan_targeted_hoods(target, repo, inventory, selected, owner)
    if payload:
        apply_payload_atomic(repo, payload)
    return ExportCounts(
        diagnostics=published.diagnostics,
        hoods_published=published.hoods_published,
        hoods_refreshed=published.hoods_refreshed,
        hoods_unchanged=published.hoods_unchanged,
        agent_sessions_published=published.agent_sessions_published,
        runs_published=published.runs_published,
    )


def _observe_clone(repo: Path, git_runner: GitRunner) -> dict[str, Any]:
    head = _git_text(repo, git_runner, ["rev-parse", "HEAD"], "replay_head")
    upstream = _git_text(
        repo, git_runner, ["rev-parse", "@{upstream}"], "replay_upstream"
    )
    behind_result = git_runner(
        repo,
        ["rev-list", "--count", "HEAD..@{upstream}"],
        op="agents_sync.replay_behind",
    )
    try:
        behind = (
            int(behind_result.stdout.strip()) if behind_result.returncode == 0 else 0
        )
    except ValueError:
        behind = 0
    unpublished = _git_lines(
        repo,
        git_runner,
        ["rev-list", "--reverse", "@{upstream}..HEAD"],
        "replay_unpublished",
    )
    return {
        "head": head,
        "upstream": upstream,
        "ahead": agents_ahead_count(repo, git_runner),
        "behind": behind,
        "unpublished": unpublished,
    }


def _collect_paths(repo: Path, git_runner: GitRunner) -> tuple[str, ...]:
    names: list[str] = []
    for args, op in (
        (["diff", "--name-only", "@{upstream}...HEAD"], "replay_commit_paths"),
        (["diff", "--name-only"], "replay_unstaged_paths"),
        (["diff", "--cached", "--name-only"], "replay_staged_paths"),
        (
            ["ls-files", "--others", "--exclude-standard"],
            "replay_untracked_paths",
        ),
    ):
        names.extend(_git_lines(repo, git_runner, args, op))
    return tuple(dict.fromkeys(names))


def _ensure_backup(
    repo: Path,
    backup_root: Path,
    expected_head: str,
    observed: dict[str, Any],
    classified: ReplayPathClassification,
    hoods: tuple[str, ...],
    refused: tuple[str, ...],
    git_runner: GitRunner,
) -> None:
    existing = _read_progress(backup_root)
    if existing is not None:
        if existing.get("expected_head") not in {expected_head, observed["head"]}:
            raise AgentsSyncFormatError(
                "backup directory belongs to a different HEAD; choose a new directory"
            )
        if existing.get("stage") in {
            _VERIFIED_STAGE,
            *_MUTATION_STAGES,
            _COMPLETE_STAGE,
        }:
            return
    if observed["ahead"] > 0:
        bundle = backup_root / BUNDLE_NAME
        created = git_runner(
            repo,
            ["bundle", "create", str(bundle), "@{upstream}..HEAD"],
            op="agents_sync.replay_bundle",
        )
        if created.returncode != 0:
            raise AgentsSyncFormatError(
                agents_git_error("could not create unpublished bundle", created)
            )
        verified = git_runner(
            repo,
            ["bundle", "verify", str(bundle)],
            op="agents_sync.replay_bundle_verify",
        )
        if verified.returncode != 0:
            raise AgentsSyncFormatError(
                agents_git_error("unpublished bundle failed verification", verified)
            )
    preserved_root = backup_root / PRESERVED_DIR
    objects_root = backup_root / OBJECTS_DIR
    for relative in classified.owner_content:
        _copy_repo_file(repo, preserved_root, relative)
    for relative in classified.archive_object:
        _copy_repo_file(repo, objects_root, relative)
    atomic_write_json(
        backup_root / REVISIONS_NAME,
        {
            "head": observed["head"],
            "upstream": observed["upstream"],
            "unpublished": list(observed["unpublished"]),
            "expected_head": expected_head,
        },
    )
    checksums = _checksum_tree(backup_root)
    atomic_write_json(backup_root / CHECKSUMS_NAME, checksums)
    _write_progress(
        backup_root,
        {
            "schema_version": 1,
            "stage": _VERIFIED_STAGE,
            "expected_head": expected_head,
            "observed_head": observed["head"],
            "upstream": observed["upstream"],
            "unpublished": list(observed["unpublished"]),
            "hoods": list(hoods),
            "browsing": list(classified.browsing),
            "owner_content": list(classified.owner_content),
            "archive_object": list(classified.archive_object),
            "unknown": list(classified.unknown),
            "refused": list(refused),
        },
    )


def _verify_backup(backup_root: Path) -> tuple[bool, str | None]:
    checksums_path = backup_root / CHECKSUMS_NAME
    if not checksums_path.is_file():
        return False, "backup checksums are missing"
    recorded = _read_json(checksums_path)
    if not isinstance(recorded, dict):
        return False, "backup checksums are not an object"
    current = _checksum_tree(backup_root)
    for relative, digest in recorded.items():
        if not isinstance(relative, str) or not isinstance(digest, str):
            return False, "backup checksums are malformed"
        if relative in {PROGRESS_NAME, CHECKSUMS_NAME}:
            continue
        if current.get(relative) != digest:
            return False, f"backup checksum mismatch for {relative}"
    return True, None


def _restore_pending_objects(repo: Path, backup_root: Path) -> None:
    objects_root = backup_root / OBJECTS_DIR
    source = objects_root / ARCHIVE_OBJECT_ROOT
    if not source.is_dir():
        source = objects_root
    if not source.is_dir():
        return
    for path in source.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(objects_root).as_posix()
        if not relative.startswith(f"{ARCHIVE_OBJECT_ROOT}/"):
            relative = f"{ARCHIVE_OBJECT_ROOT}/{path.name}"
        destination = repo / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copy2(path, destination)


def _runs_from_backup(
    backup_root: Path,
    owner: AgentOwnerIdentity,
    hoods: tuple[str, ...],
) -> tuple[InventoryRun, ...]:
    preserved = backup_root / PRESERVED_DIR
    runs: list[InventoryRun] = []
    for hood in hoods:
        relative = snapshot_path(owner, hood)
        snapshot_file = preserved / relative
        if not snapshot_file.is_file():
            continue
        snapshot = read_hood_snapshot(snapshot_file)
        merge: ReplayHoodMergeDecision = decide_replay_hood_merge(
            local_owner_username=owner.username,
            local_owner_machine=owner.machine_name,
            local_hood=hood,
            upstream_owner_username=snapshot.owner.username,
            upstream_owner_machine=snapshot.owner.machine_name,
            upstream_hood=snapshot.local_hood,
        )
        if merge.action != REPLAY_HOOD_ACTION_MERGE:
            raise AgentsSyncFormatError(merge.reason)
        runs.extend(_runs_from_snapshot(snapshot, preserved))
    return tuple(runs)


def _runs_from_snapshot(
    snapshot: V2HoodSnapshot, payload_root: Path
) -> tuple[InventoryRun, ...]:
    runs: list[InventoryRun] = []
    for run in snapshot.runs:
        files = dict(run.files)
        runs.append(
            InventoryRun(
                run.source_run_id,
                run.local_name,
                run.global_name,
                run.state,
                run.started_at,
                run.finished_at,
                run.dismissed_at,
                run.metadata,
                run.commits,
                _payload_bytes(payload_root, files, "prompt"),
                _payload_bytes(payload_root, files, "chat"),
                _text(agent_session_value(dict(run.metadata)))
                or _text(dict(run.metadata).get(AGENT_SESSION_KEY)),
                _text(dict(run.metadata).get("agent_clan")),
                _relationships_for(snapshot, run.source_run_id),
                run.started_at or run.source_run_id,
                _payload_bytes(payload_root, files, "embedded_workflows"),
                _payload_bytes(payload_root, files, "prompt_steps"),
                "replay-backup",
            )
        )
    return tuple(runs)


def _merge_runs(
    preserved: tuple[InventoryRun, ...],
    live: tuple[InventoryRun, ...],
    repo: Path,
    backup_root: Path,
) -> tuple[InventoryRun, ...]:
    by_id: dict[str, InventoryRun] = {run.source_run_id: run for run in live}
    for run in preserved:
        existing = by_id.get(run.source_run_id)
        if existing is None:
            by_id[run.source_run_id] = run
            continue
        chosen = _choose_run_bytes(existing, run, repo, backup_root)
        by_id[run.source_run_id] = chosen
    return tuple(by_id.values())


def _choose_run_bytes(
    current: InventoryRun,
    previous: InventoryRun,
    repo: Path,
    backup_root: Path,
) -> InventoryRun:
    del repo, backup_root
    return replace(
        current,
        prompt_bytes=_choose_payload_bytes(
            current.prompt_bytes,
            previous.prompt_bytes,
            current.global_name,
            "prompt_bytes",
        ),
        chat_bytes=_choose_payload_bytes(
            current.chat_bytes,
            previous.chat_bytes,
            current.global_name,
            "chat_bytes",
        ),
        embedded_workflows_bytes=_choose_payload_bytes(
            current.embedded_workflows_bytes,
            previous.embedded_workflows_bytes,
            current.global_name,
            "embedded_workflows_bytes",
        ),
        prompt_steps_bytes=_choose_payload_bytes(
            current.prompt_steps_bytes,
            previous.prompt_steps_bytes,
            current.global_name,
            "prompt_steps_bytes",
        ),
    )


def _choose_payload_bytes(
    current_bytes: bytes | None,
    previous_bytes: bytes | None,
    run_name: str,
    field: str,
) -> bytes | None:
    if current_bytes is None and previous_bytes is None:
        return None
    decision: ReplayByteDivergenceDecision = decide_replay_byte_divergence(
        current_bytes or b"", previous_bytes or b""
    )
    if decision.action == REPLAY_BYTES_REFUSE:
        raise AgentsSyncFormatError(f"{run_name} {field} {decision.reason}")
    if decision.action == REPLAY_BYTES_KEEP_PREVIOUS:
        return previous_bytes
    return current_bytes


def _refused_same_run_divergences(
    repo: Path,
    owner: AgentOwnerIdentity,
    hoods: tuple[str, ...],
    owner_content: tuple[str, ...],
    git_runner: GitRunner,
) -> tuple[str, ...]:
    del owner_content
    refused: list[str] = []
    for hood in hoods:
        relative = snapshot_path(owner, hood)
        local = repo / relative
        if not local.is_file():
            continue
        upstream_bytes = _git_optional_bytes(
            repo,
            git_runner,
            ["show", f"@{{upstream}}:{relative}"],
            "replay_upstream_snap",
        )
        if upstream_bytes is None:
            continue
        try:
            upstream_snapshot = decode_hood_snapshot(loads(upstream_bytes.decode()))
        except (OSError, UnicodeDecodeError, AgentsSyncFormatError, ValueError):
            continue
        merge: ReplayHoodMergeDecision = decide_replay_hood_merge(
            local_owner_username=owner.username,
            local_owner_machine=owner.machine_name,
            local_hood=hood,
            upstream_owner_username=upstream_snapshot.owner.username,
            upstream_owner_machine=upstream_snapshot.owner.machine_name,
            upstream_hood=upstream_snapshot.local_hood,
        )
        if merge.action != REPLAY_HOOD_ACTION_MERGE:
            refused.append(f"{hood}: {merge.reason}")
            continue
        local_snapshot = read_hood_snapshot(local)
        local_runs = {run.global_name: run for run in local_snapshot.runs}
        for run in upstream_snapshot.runs:
            local_run = local_runs.get(run.global_name)
            if local_run is None:
                continue
            for kind, current_ref in dict(local_run.files).items():
                previous_ref = dict(run.files).get(kind)
                if previous_ref is None:
                    continue
                current_bytes = _file_bytes(repo / current_ref.path)
                previous_bytes = _git_optional_bytes(
                    repo,
                    git_runner,
                    ["show", f"@{{upstream}}:{previous_ref.path}"],
                    "replay_upstream_run",
                )
                if current_bytes is None or previous_bytes is None:
                    continue
                run_decision: ReplayByteDivergenceDecision = (
                    decide_replay_byte_divergence(current_bytes, previous_bytes)
                )
                if run_decision.action == REPLAY_BYTES_REFUSE:
                    refused.append(f"{run.global_name}:{kind}: {run_decision.reason}")
    return tuple(refused)


def _classified_from_progress(
    progress: dict[str, Any],
) -> tuple[ReplayPathClassification, tuple[str, ...]]:
    classified_state = ReplayPathClassification(
        schema_version=PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
        entries=(),
        browsing=tuple(str(item) for item in progress.get("browsing") or ()),
        owner_content=tuple(str(item) for item in progress.get("owner_content") or ()),
        archive_object=tuple(
            str(item) for item in progress.get("archive_object") or ()
        ),
        unknown=tuple(str(item) for item in progress.get("unknown") or ()),
    )
    hoods = tuple(str(item) for item in progress.get("hoods") or ())
    return classified_state, hoods


def _owner_hoods(
    owner_content: tuple[str, ...], owner: AgentOwnerIdentity
) -> tuple[str, ...]:
    hoods: list[str] = []
    for path in owner_content:
        parts = Path(path).parts
        if (
            len(parts) == 7
            and parts[0] == "users"
            and parts[1] == owner.username
            and parts[2] == "machines"
            and parts[3] == owner.machine_name
            and parts[4] == "hoods"
            and parts[6] == "snapshot.json"
        ):
            hoods.append(parts[5])
    return tuple(dict.fromkeys(hoods))


def _payload_bytes(root: Path, files: dict[str, Any], kind: str) -> bytes | None:
    reference = files.get(kind)
    if reference is None:
        return None
    return _file_bytes(root / reference.path)


def _file_bytes(path: Path) -> bytes | None:
    if not path.is_file():
        return None
    return path.read_bytes()


def _relationships_for(
    snapshot: V2HoodSnapshot, source_run_id: str
) -> tuple[InventoryRelationship, ...]:
    items: list[InventoryRelationship] = []
    for relationship in snapshot.relationships:
        if relationship.source_run_id != source_run_id:
            continue
        target = relationship.target
        name = target.global_name or target.source_run_id or ""
        items.append(
            InventoryRelationship(
                relationship.kind, name, target.kind, relationship.required
            )
        )
    return tuple(items)


def _copy_repo_file(repo: Path, destination_root: Path, relative: str) -> None:
    source = repo / relative
    if not source.is_file():
        return
    destination = destination_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _checksum_tree(root: Path) -> dict[str, str]:
    checksums: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in {PROGRESS_NAME, CHECKSUMS_NAME}:
            continue
        checksums[relative] = sha256(path.read_bytes()).hexdigest()
    return checksums


def _write_progress(backup_root: Path, payload: dict[str, Any]) -> None:
    atomic_write_json(backup_root / PROGRESS_NAME, payload)


def _read_progress(backup_root: Path) -> dict[str, Any] | None:
    path = backup_root / PROGRESS_NAME
    if not path.is_file():
        return None
    value = _read_json(path)
    return value if isinstance(value, dict) else None


def _read_json(path: Path) -> Any:
    return loads(path.read_text(encoding="utf-8"))


def _resolve_project_target(project: str | None) -> ProjectTarget:
    selector = project
    if not selector:
        from sase.workflows.utils import get_project_from_workspace

        selector = get_project_from_workspace()
    if not selector:
        raise AgentsSyncFormatError("pass --project to name the sidecar to recover")
    selection = resolve_sync_targets((selector,))
    if len(selection.targets) != 1:
        outcome = selection.outcomes[0] if selection.outcomes else None
        detail = (
            (outcome.skip_reason or outcome.error) if outcome is not None else None
        ) or "agents target is unavailable"
        raise AgentsSyncFormatError(detail)
    return selection.targets[0]


def _git_text(repo: Path, git_runner: GitRunner, args: list[str], op: str) -> str:
    result = git_runner(repo, args, op=f"agents_sync.{op}")
    if result.returncode != 0:
        raise AgentsSyncFormatError(
            agents_git_error(f"git {' '.join(args)} failed", result)
        )
    return result.stdout.strip()


def _git_lines(
    repo: Path, git_runner: GitRunner, args: list[str], op: str
) -> tuple[str, ...]:
    result = git_runner(repo, args, op=f"agents_sync.{op}")
    if result.returncode != 0:
        return ()
    return tuple(line for line in result.stdout.splitlines() if line)


def _git_optional_bytes(
    repo: Path, git_runner: GitRunner, args: list[str], op: str
) -> bytes | None:
    result = git_runner(repo, args, op=f"agents_sync.{op}")
    if result.returncode != 0:
        return None
    return result.stdout.encode()


def _text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _report_from_state(
    target: ProjectTarget,
    expected_head: str,
    backup_root: Path,
    apply: bool,
    observed: dict[str, Any],
    progress: dict[str, Any] | None,
    classified: ReplayPathClassification | None,
    hoods: tuple[str, ...],
    refused: tuple[str, ...],
    action: str,
    outcome: SyncOutcome | None,
) -> ReplayRecoveryReport:
    browsing = (
        tuple(classified.browsing)
        if classified is not None
        else tuple(progress.get("browsing", ()) if progress else ())
    )
    owner_content = (
        tuple(classified.owner_content)
        if classified is not None
        else tuple(progress.get("owner_content", ()) if progress else ())
    )
    archive_object = (
        tuple(classified.archive_object)
        if classified is not None
        else tuple(progress.get("archive_object", ()) if progress else ())
    )
    unknown = (
        tuple(classified.unknown)
        if classified is not None
        else tuple(progress.get("unknown", ()) if progress else ())
    )
    return ReplayRecoveryReport(
        project_key=target.project_key,
        observed_head=str(observed["head"]),
        expected_head=expected_head,
        upstream=str(observed["upstream"]),
        ahead=int(observed["ahead"]),
        behind=int(observed["behind"]),
        stage=str((progress or {}).get("stage") or "inventory"),
        action=action,
        already_complete=str((progress or {}).get("stage")) == _COMPLETE_STAGE,
        apply=apply,
        error=None,
        browsing_paths=tuple(str(item) for item in browsing),
        owner_content_paths=tuple(str(item) for item in owner_content),
        archive_object_paths=tuple(str(item) for item in archive_object),
        unknown_paths=tuple(str(item) for item in unknown),
        preserved_hoods=hoods or tuple(progress.get("hoods", ()) if progress else ()),
        refused_divergences=refused,
        backup_dir=str(backup_root),
        outcome=outcome,
    )


def _error_report(
    target: ProjectTarget,
    expected_head: str,
    backup_root: Path,
    apply: bool,
    error: str,
    *,
    observed: dict[str, Any] | None = None,
    classified: ReplayPathClassification | None = None,
    hoods: tuple[str, ...] = (),
    refused: tuple[str, ...] = (),
    outcome: SyncOutcome | None = None,
) -> ReplayRecoveryReport:
    observed = observed or {
        "head": "",
        "upstream": "",
        "ahead": 0,
        "behind": 0,
        "unpublished": (),
    }
    return replace(
        _report_from_state(
            target,
            expected_head,
            backup_root,
            apply,
            observed,
            _read_progress(backup_root),
            classified,
            hoods,
            refused,
            REPLAY_APPLY_ACTION_REFUSE,
            outcome,
        ),
        error=error,
    )


__all__ = [
    "ReplayRecoveryReport",
    "recover_stale_replay",
]
