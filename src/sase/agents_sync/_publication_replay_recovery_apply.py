"""Reset unpublished replay and republish preserved owner snapshots."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import shutil
from typing import Any

from sase.agents_sync._publication_replay_recovery_support import file_bytes, git_text
from sase.agents_sync._publication_replay_recovery_types import (
    COMPLETE_STAGE,
    OBJECTS_DIR,
    PRESERVED_DIR,
    ReplayRecoveryReport,
    error_report,
    read_progress,
    report_from_state,
    write_progress,
)
from sase.agents_sync.git import GitRunner
from sase.agents_sync.git_sync_ops import abort_agents_rebase, agents_git_error
from sase.agents_sync.git_sync_transaction import sync_project_locked
from sase.agents_sync.inventory import InventoryRun, ProjectHoodInventory
from sase.agents_sync.inventory_models import InventoryRelationship
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ExportCounts, ProjectTarget
from sase.agents_sync.prompt_archive.archive_objects import ARCHIVE_OBJECT_ROOT
from sase.agents_sync.publication_planning import plan_targeted_hoods
from sase.agents_sync.publication_validation import snapshot_path
from sase.agents_sync.v2_io import apply_payload_atomic, read_hood_snapshot
from sase.agents_sync.v2_models import V2HoodSnapshot
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    REPLAY_APPLY_ACTION_APPLY,
    REPLAY_BYTES_KEEP_PREVIOUS,
    REPLAY_BYTES_REFUSE,
    REPLAY_HOOD_ACTION_MERGE,
    ReplayByteDivergenceDecision,
    ReplayHoodMergeDecision,
    ReplayPathClassification,
    decide_replay_byte_divergence,
    decide_replay_hood_merge,
)
from sase.plan_chain import AGENT_SESSION_KEY, agent_session_value


def apply_replay(
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
            return error_report(
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
        write_progress(backup_root, {**progress, "stage": "reset"})
    _restore_pending_objects(repo, backup_root)
    write_progress(
        backup_root,
        {**(read_progress(backup_root) or progress), "stage": "replaying"},
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
        return error_report(
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
    completed_head = git_text(repo, git_runner, ["rev-parse", "HEAD"], "replay_head")
    write_progress(
        backup_root,
        {
            **(read_progress(backup_root) or progress),
            "stage": COMPLETE_STAGE,
            "completed_head": completed_head,
        },
    )
    return replace(
        report_from_state(
            target,
            expected_head,
            backup_root,
            True,
            observed,
            read_progress(backup_root),
            classified,
            hoods,
            refused,
            REPLAY_APPLY_ACTION_APPLY,
            outcome,
        ),
        stage=COMPLETE_STAGE,
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


def _payload_bytes(root: Path, files: dict[str, Any], kind: str) -> bytes | None:
    reference = files.get(kind)
    if reference is None:
        return None
    return file_bytes(root / reference.path)


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


def _text(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
