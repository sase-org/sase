"""Machine-owned publication adapter for recovery activation and claims.

The Rust core owns local create-if-absent records. This adapter refreshes a
machine-writable beads store, publishes those records, and confirms the
published winner. A failed or uncertain publish never grants a launch
permit, and nothing here submits a proc or agent.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sase.bead._sync_publication import PushOutcome
from sase.core.recovery_facade import (
    RECOVERY_STATE_CREATED,
    RECOVERY_STATE_EXISTING,
    RecoveryActivation,
    RecoveryActivationInspect,
    RecoveryArmResult,
    RecoveryClaim,
    RecoveryClaimCreateResult,
    RecoveryClaimInspect,
    arm_recovery_activation,
    create_recovery_claim,
    inspect_recovery_activation,
    inspect_recovery_claim,
)

REASON_LOCAL_WINNER_PUBLISHED = "local_winner_published"
REASON_EXISTING_CLAIM = "existing_published_claim"
REASON_NOT_LOCAL_WINNER = "not_local_winner"
REASON_PUBLISH_UNCONFIRMED = "publish_unconfirmed"
REASON_PUBLISH_INTERRUPTED = "publish_interrupted"
REASON_REFRESH_FAILED = "refresh_failed"
REASON_ACTIVATION_DISABLED = "activation_disabled"
REASON_CLAIM_REFUSED = "claim_refused"
REASON_UNSUPPORTED_CORE = "unsupported_core_binding"


@dataclass(frozen=True, slots=True)
class RecoveryPublicationResult:
    """Verified claim or activation after a publication attempt.

    ``launch_permit`` is true only when this caller is the published winner.
    Callers must not start a process unless that flag is true.
    """

    launch_permit: bool
    reason: str
    published: bool
    local_winner: bool
    claim: RecoveryClaim | None = None
    activation: RecoveryActivation | None = None
    diagnostic: str | None = None
    claim_key: str = ""


def _no_permit(
    *,
    reason: str,
    local_winner: bool = False,
    published: bool = False,
    claim: RecoveryClaim | None = None,
    activation: RecoveryActivation | None = None,
    diagnostic: str | None = None,
    claim_key: str = "",
) -> RecoveryPublicationResult:
    return RecoveryPublicationResult(
        launch_permit=False,
        reason=reason,
        published=published,
        local_winner=local_winner,
        claim=claim,
        activation=activation,
        diagnostic=diagnostic,
        claim_key=claim_key,
    )


def _push_confirmed(outcome: PushOutcome, repo_root: Path | None) -> bool:
    if outcome.pushed or outcome.skipped_no_remote:
        return True
    if outcome.skipped_locked and repo_root is not None:
        from sase.bead._sync_publication import head_is_published

        return head_is_published(repo_root)
    return False


def _refresh_store(beads_dir: Path) -> None:
    from sase.bead.sync import refresh_bead_store

    refresh_bead_store(beads_dir)


def _default_push(beads_dir: Path) -> PushOutcome:
    from sase.bead.sync import push_bead_work_launch

    return push_bead_work_launch(beads_dir)


def _commit_records(beads_dir: Path, message: str, context: Any | None) -> bool:
    from sase.bead.sync import bead_store_write_lock, commit_recovery_records

    with bead_store_write_lock(beads_dir) as already_locked:
        return commit_recovery_records(
            beads_dir,
            message=message,
            already_locked=already_locked,
            mutation_origin="machine",
            operation_context=context,
        )


def _replay_recovery_publication(
    beads_dir: Path,
    *,
    cause: str,
) -> str | None:
    """Reset unpublished recovery commits onto the published winner.

    Returns ``None`` on success, or a diagnostic when the reset is uncertain.
    Uses the same ownership, sandbox, and store-lock guards as epic-graph
    conflict replay, then hard-resets to ``@{upstream}`` so competing writers
    keep only the published payload.
    """
    from sase.bead._sync_git import find_git_root
    from sase.sdd._git import run_sdd_git
    from sase.sdd._git_contention import store_git_write_lock
    from sase.workspace_provider.ownership import authorize_store_mutation

    repo_root = find_git_root(beads_dir)
    if repo_root is None:
        return f"{cause}: beads store has no git root"
    try:
        authorize_store_mutation(repo_root, mutation_origin="machine")
    except Exception as exc:
        return f"{cause}: workspace ownership guard refused the reset: {exc}"
    try:
        from sase.core.state_write_guard import assert_bead_store_write_sandboxed

        assert_bead_store_write_sandboxed(
            beads_dir, operation="recovery publication replay"
        )
    except Exception as exc:
        return f"{cause}: bead-store write sandbox refused the reset: {exc}"

    with store_git_write_lock(
        repo_root,
        op="bead.recovery_publication_replay",
        mutates_worktree=True,
    ) as acquired:
        if not acquired:
            return f"{cause}: could not acquire the beads store write lock"
        fetched = run_sdd_git(
            ["fetch"],
            cwd=repo_root,
            op="bead.recovery_publication_replay.fetch",
            check=False,
            capture_output=True,
            text=True,
        )
        if fetched.returncode != 0:
            return (
                f"{cause}: could not fetch the beads repo: "
                f"{(fetched.stderr or fetched.stdout or '').strip()}"
            )
        reset = run_sdd_git(
            ["reset", "--hard", "@{upstream}"],
            cwd=repo_root,
            op="bead.recovery_publication_replay.reset",
            check=False,
            capture_output=True,
            text=True,
        )
        if reset.returncode != 0:
            return (
                f"{cause}: could not reset to the published winner: "
                f"{(reset.stderr or reset.stdout or '').strip()}"
            )
    return None


def publish_recovery_activation_in_store(
    beads_dir: Path,
    request: Mapping[str, Any],
    *,
    refresh: Callable[[Path], None] | None = None,
    commit: Callable[[Path, str], bool] | None = None,
    push: Callable[[Path], PushOutcome] | None = None,
    replay: Callable[[Path], str | None] | None = None,
    operation_context: Any | None = None,
) -> RecoveryPublicationResult:
    """Arm create-if-absent and publish the activation cutoff."""
    commit_fn = commit or (
        lambda path, message: _commit_records(path, message, operation_context)
    )
    try:
        (refresh or _refresh_store)(beads_dir)
    except Exception as exc:  # noqa: BLE001 - uncertain refresh cannot arm.
        return _no_permit(reason=REASON_REFRESH_FAILED, diagnostic=str(exc))

    armed: RecoveryArmResult = arm_recovery_activation(str(beads_dir), request)
    if not armed.recovery_enabled:
        return _no_permit(
            reason=REASON_ACTIVATION_DISABLED,
            activation=armed.activation,
            diagnostic=armed.diagnostic,
        )
    if armed.state not in {RECOVERY_STATE_CREATED, RECOVERY_STATE_EXISTING}:
        return _no_permit(
            reason=REASON_ACTIVATION_DISABLED,
            activation=armed.activation,
            diagnostic=armed.diagnostic,
        )

    if armed.created:
        commit_fn(
            beads_dir,
            _activation_commit_message(request.get("project_id")),
        )
        outcome = (push or _default_push)(beads_dir)
        from sase.bead._sync_git import find_git_root

        repo_root = find_git_root(beads_dir)
        if not _push_confirmed(outcome, repo_root):
            if outcome.error or outcome.skipped_locked:
                replay_problem = (replay or _default_replay)(beads_dir)
                replayed: RecoveryActivationInspect = inspect_recovery_activation(
                    str(beads_dir), str(request.get("project_id") or "")
                )
                if replayed.recovery_enabled and replayed.activation is not None:
                    ours = armed.activation
                    winner = replayed.activation
                    if ours is not None and winner == ours:
                        return RecoveryPublicationResult(
                            launch_permit=True,
                            reason=REASON_LOCAL_WINNER_PUBLISHED,
                            published=True,
                            local_winner=True,
                            activation=winner,
                        )
                    return _no_permit(
                        reason=REASON_EXISTING_CLAIM
                        if winner != ours
                        else REASON_PUBLISH_UNCONFIRMED,
                        published=replayed.recovery_enabled,
                        activation=winner,
                        diagnostic=replay_problem or outcome.error,
                    )
                return _no_permit(
                    reason=REASON_PUBLISH_UNCONFIRMED
                    if replay_problem is None
                    else REASON_PUBLISH_INTERRUPTED,
                    activation=armed.activation,
                    diagnostic=replay_problem or outcome.error,
                )
            return _no_permit(
                reason=REASON_PUBLISH_UNCONFIRMED,
                local_winner=True,
                activation=armed.activation,
                diagnostic=outcome.error,
            )

    inspected: RecoveryActivationInspect = inspect_recovery_activation(
        str(beads_dir), str(request.get("project_id") or "")
    )
    if not inspected.recovery_enabled or inspected.activation is None:
        return _no_permit(
            reason=REASON_ACTIVATION_DISABLED,
            diagnostic=inspected.diagnostic,
        )
    return RecoveryPublicationResult(
        launch_permit=True,
        reason=REASON_LOCAL_WINNER_PUBLISHED,
        published=True,
        local_winner=True,
        activation=inspected.activation,
    )


def _publish_recovery_claim_in_store(
    beads_dir: Path,
    request: Mapping[str, Any],
    *,
    refresh: Callable[[Path], None] | None = None,
    commit: Callable[[Path, str], bool] | None = None,
    push: Callable[[Path], PushOutcome] | None = None,
    replay: Callable[[Path], str | None] | None = None,
    operation_context: Any | None = None,
) -> RecoveryPublicationResult:
    """Create-if-absent a claim, publish it, and confirm the winner.

    Only the published winner receives ``launch_permit=True``. This function
    never submits a proc or agent.
    """
    commit_fn = commit or (
        lambda path, message: _commit_records(path, message, operation_context)
    )
    try:
        (refresh or _refresh_store)(beads_dir)
    except Exception as exc:  # noqa: BLE001 - uncertain refresh cannot claim.
        return _no_permit(reason=REASON_REFRESH_FAILED, diagnostic=str(exc))

    created: RecoveryClaimCreateResult = create_recovery_claim(str(beads_dir), request)
    if created.state not in {RECOVERY_STATE_CREATED, RECOVERY_STATE_EXISTING}:
        reason = (
            REASON_UNSUPPORTED_CORE
            if created.diagnostic == "unsupported_core_binding"
            else REASON_CLAIM_REFUSED
        )
        return _no_permit(
            reason=reason,
            claim=created.claim,
            diagnostic=created.diagnostic,
            claim_key=created.claim_key,
        )
    if not created.local_winner:
        return _no_permit(
            reason=REASON_NOT_LOCAL_WINNER,
            published=created.state == RECOVERY_STATE_EXISTING,
            claim=created.claim,
            claim_key=created.claim_key,
            diagnostic=created.diagnostic,
        )

    commit_fn(
        beads_dir,
        _claim_commit_message(
            request.get("project_id"),
            request.get("epic_id"),
            created.claim_key,
        ),
    )
    outcome = (push or _default_push)(beads_dir)
    from sase.bead._sync_git import find_git_root

    repo_root = find_git_root(beads_dir)
    if not _push_confirmed(outcome, repo_root):
        replay_problem = (replay or _default_replay)(beads_dir)
        replayed: RecoveryClaimInspect = inspect_recovery_claim(
            str(beads_dir),
            {
                "project_id": request.get("project_id"),
                "epic_id": request.get("epic_id"),
                "close_token": request.get("close_token"),
            },
        )
        winner = replayed.claim
        if winner is not None and _claim_matches_request(winner, request):
            if replay_problem is not None and not outcome.pushed:
                return _no_permit(
                    reason=REASON_PUBLISH_INTERRUPTED,
                    local_winner=True,
                    claim=winner,
                    claim_key=created.claim_key,
                    diagnostic=replay_problem or outcome.error,
                )
            return RecoveryPublicationResult(
                launch_permit=True,
                reason=REASON_LOCAL_WINNER_PUBLISHED,
                published=True,
                local_winner=True,
                claim=winner,
                claim_key=created.claim_key,
            )
        return _no_permit(
            reason=REASON_EXISTING_CLAIM
            if winner is not None
            else REASON_PUBLISH_UNCONFIRMED,
            published=winner is not None,
            local_winner=False,
            claim=winner,
            claim_key=created.claim_key,
            diagnostic=replay_problem or outcome.error,
        )

    inspected: RecoveryClaimInspect = inspect_recovery_claim(
        str(beads_dir),
        {
            "project_id": request.get("project_id"),
            "epic_id": request.get("epic_id"),
            "close_token": request.get("close_token"),
        },
    )
    if inspected.claim is None or not _claim_matches_request(inspected.claim, request):
        return _no_permit(
            reason=REASON_NOT_LOCAL_WINNER,
            published=inspected.claim is not None,
            claim=inspected.claim,
            claim_key=created.claim_key,
            diagnostic=inspected.diagnostic,
        )
    return RecoveryPublicationResult(
        launch_permit=True,
        reason=REASON_LOCAL_WINNER_PUBLISHED,
        published=True,
        local_winner=True,
        claim=inspected.claim,
        claim_key=created.claim_key,
    )


def publish_recovery_claim(
    project: str,
    request: Mapping[str, Any],
    *,
    workflow: str = "epic_recovery_claim",
    holder: str = "epic-recovery",
) -> RecoveryPublicationResult:
    """Publish a recovery claim through a machine-owned writable store."""
    from sase.bead.background_store import (
        schedule_beads_sidecar_convergence,
        writable_bead_store_for_machine,
    )

    with writable_bead_store_for_machine(
        project,
        workflow=workflow,
        holder=holder,
        prefer_existing_claim=True,
    ) as store:
        result = _publish_recovery_claim_in_store(
            store.beads_dir,
            request,
            operation_context=store.context,
        )
        if result.published or result.local_winner:
            schedule_beads_sidecar_convergence(store.project)
        return result


def _default_replay(beads_dir: Path) -> str | None:
    return _replay_recovery_publication(beads_dir, cause="recovery-claim-publish")


def _activation_commit_message(project_id: object) -> str:
    identity = str(project_id or "project")
    return f"chore(beads): arm recovery activation for {identity}"


def _claim_commit_message(project_id: object, epic_id: object, claim_key: str) -> str:
    project = str(project_id or "project")
    epic = str(epic_id or "epic")
    suffix = claim_key[:12] if claim_key else "claim"
    return f"chore(beads): record recovery claim {project} {epic} {suffix}"


def _claim_matches_request(claim: RecoveryClaim, request: Mapping[str, Any]) -> bool:
    return (
        claim.project_id == str(request.get("project_id") or "")
        and claim.epic_id == str(request.get("epic_id") or "")
        and claim.close_token == str(request.get("close_token") or "")
        and claim.owner_machine == str(request.get("owner_machine") or "")
        and claim.proc_id == str(request.get("proc_id") or "")
        and claim.request_fingerprint == str(request.get("request_fingerprint") or "")
    )


__all__ = [
    "REASON_ACTIVATION_DISABLED",
    "REASON_CLAIM_REFUSED",
    "REASON_EXISTING_CLAIM",
    "REASON_LOCAL_WINNER_PUBLISHED",
    "REASON_NOT_LOCAL_WINNER",
    "REASON_PUBLISH_INTERRUPTED",
    "REASON_PUBLISH_UNCONFIRMED",
    "REASON_REFRESH_FAILED",
    "REASON_UNSUPPORTED_CORE",
    "RecoveryPublicationResult",
    "publish_recovery_activation_in_store",
    "publish_recovery_claim",
]
