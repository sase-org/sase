"""Lock, classify, back up, and optionally apply stale-replay recovery."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from sase.agents_sync._publication_replay_recovery_apply import apply_replay
from sase.agents_sync._publication_replay_recovery_backup import (
    collect_paths,
    ensure_backup,
    observe_clone,
    refused_same_run_divergences,
    verify_backup,
)
from sase.agents_sync._publication_replay_recovery_types import (
    COMPLETE_STAGE,
    MUTATION_STAGES,
    REVISIONS_NAME,
    VERIFIED_STAGE,
    ReplayRecoveryReport,
    error_report,
    read_json,
    read_progress,
    report_from_state,
)
from sase.agents_sync.git import GitBytesRunner, GitRunner, run_git, run_git_bytes
from sase.agents_sync.git_sync_ops import (
    agents_git_dir,
    agents_git_error,
    bounded_agents_lock,
    configured_agents_lock_timeout,
    ensure_agents_clone,
)
from sase.agents_sync.io import AgentsSyncFormatError
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.targets import resolve_sync_targets
from sase.config import require_agent_owner_identity
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    PUBLICATION_RECOVERY_WIRE_SCHEMA_VERSION,
    REPLAY_APPLY_ACTION_ALREADY_COMPLETE,
    REPLAY_APPLY_ACTION_APPLY,
    REPLAY_APPLY_ACTION_REFUSE,
    REPLAY_APPLY_ACTION_REPORT,
    ReplayApplyDecision,
    ReplayPathClassification,
    classify_replay_paths,
    decide_replay_apply,
)


def recover_stale_replay(
    *,
    expected_head: str,
    backup_dir: Path,
    project: str | None = None,
    target: ProjectTarget | None = None,
    apply: bool = False,
    owner: AgentOwnerIdentity | None = None,
    git_runner: GitRunner = run_git,
    git_bytes_runner: GitBytesRunner = run_git_bytes,
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
        return error_report(
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
        return error_report(
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
            return error_report(
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
            git_bytes_runner,
        )


def _recover_locked(
    target: ProjectTarget,
    owner: AgentOwnerIdentity,
    expected_head: str,
    backup_root: Path,
    apply: bool,
    git_runner: GitRunner,
    git_bytes_runner: GitBytesRunner,
) -> ReplayRecoveryReport:
    repo = target.sidecar_path
    fetched = git_runner(repo, ["fetch"], network=True, op="agents_sync.replay_fetch")
    if fetched.returncode != 0:
        return error_report(
            target,
            expected_head,
            backup_root,
            apply,
            agents_git_error(
                "could not fetch upstream before replay recovery", fetched
            ),
        )
    observed = observe_clone(repo, git_runner)
    progress = read_progress(backup_root)
    merge_base = _replay_merge_base(repo, backup_root, progress, observed, git_runner)
    already_complete = (
        progress is not None
        and progress.get("stage") == COMPLETE_STAGE
        and str(progress.get("expected_head", "")) == expected_head
    )
    mutation_started = bool(
        progress is not None and progress.get("stage") in MUTATION_STAGES
    )
    classified: ReplayPathClassification | None = None
    refused: tuple[str, ...] = ()
    hoods: tuple[str, ...] = ()
    if not already_complete and mutation_started and progress is not None:
        classified, hoods = _classified_from_progress(progress)
        refused = tuple(str(item) for item in progress.get("refused") or ())
    elif not already_complete:
        paths = collect_paths(repo, git_runner)
        classified = classify_replay_paths(paths)
        hoods = _owner_hoods(classified.owner_content, owner)
        refused = refused_same_run_divergences(
            repo,
            owner,
            hoods,
            classified.owner_content,
            merge_base,
            git_bytes_runner,
        )
        try:
            ensure_backup(
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
            return error_report(
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
        progress = read_progress(backup_root)
    verified, verify_error = verify_backup(backup_root)
    backup_complete = progress is not None and progress.get("stage") in {
        VERIFIED_STAGE,
        *MUTATION_STAGES,
        COMPLETE_STAGE,
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
    report = report_from_state(
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
        return replace(report, already_complete=True, stage=COMPLETE_STAGE)
    if decision.action == REPLAY_APPLY_ACTION_REPORT or not apply:
        return report
    if verify_error is not None:
        return replace(report, error=verify_error, action=REPLAY_APPLY_ACTION_REFUSE)
    if decision.action != REPLAY_APPLY_ACTION_APPLY:
        return replace(report, error=decision.reason)
    return apply_replay(
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
        git_bytes_runner,
        merge_base,
        mutation_started,
    )


def _replay_merge_base(
    repo: Path,
    backup_root: Path,
    progress: dict[str, Any] | None,
    observed: dict[str, Any],
    git_runner: GitRunner,
) -> str | None:
    if progress is not None and "merge_base" in progress:
        value = progress["merge_base"]
        return value if isinstance(value, str) else None
    revisions_path = backup_root / REVISIONS_NAME
    revisions = read_json(revisions_path) if revisions_path.is_file() else None
    if isinstance(revisions, dict):
        head = revisions.get("head")
        upstream = revisions.get("upstream")
        if isinstance(head, str) and isinstance(upstream, str):
            result = git_runner(
                repo,
                ["merge-base", head, upstream],
                op="agents_sync.replay_merge_base_resume",
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
    value = observed.get("merge_base")
    return value if isinstance(value, str) else None


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
