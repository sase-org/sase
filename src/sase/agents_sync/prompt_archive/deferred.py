"""Regenerate deferred prompt archives inside an open sidecar transaction.

A prompt archive that could not be published while the primary commit was
landing is not lost.  The durable agent-hood publication request that carries
the hood carries its prompt too: both the commit-time drain and the full
``sase agent sync`` pass call in here while they already hold the agents lock,
so one lock acquisition -- and one durable retry -- covers both.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from pathlib import Path
import time

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.inventory_models import InventoryRun
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.paths import prompts_month_dir
from sase.agents_sync.prompt_archive.preparation import PreparedPromptArchive
from sase.agents_sync.publication_completion import snapshot_prompt_file_present
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    PROMPT_STATUS_UNAVAILABLE,
    DeferredPromptDecision,
    classify_deferred_prompt_obligation,
)
from sase.sase_agent import sase_agent_ref_for_turn
from sase.sdd.plan_header_block import PlanHeaderSectionKind, parse_plan_header_block

log = logging.getLogger(__name__)

# Young unresolved archives self-resolve; 30 minutes covers the worst observed case.
DEFERRED_PROMPT_GRACE_SECONDS = 1800
UNRESOLVED_PROMPT_ARCHIVE_REASON = (
    "prompt archive is unresolved and a missing local source does not prove "
    "there was no prompt obligation"
)


@dataclass(frozen=True, slots=True)
class DeferredPromptRestoreFailure:
    """One restore failure, plus whether it is still inside the grace window."""

    message: str
    pending: bool = False


@dataclass(frozen=True, slots=True)
class _DeferredPromptPrepareResult:
    """Whether a deferred restore wrote, and any protection withhold."""

    wrote: bool
    protection_status: str | None = None
    prepared_archive: PreparedPromptArchive | None = None


def prompt_runs_by_request(
    inventory: ProjectHoodInventory,
    identity: AgentIdentitySnapshot,
) -> dict[tuple[str, str], InventoryRun]:
    """Index local runs by the (sase-agent, revision) pair a request names."""

    indexed: dict[tuple[str, str], InventoryRun] = {}
    for run in inventory.runs:
        local_name = getattr(run, "local_name", None)
        if not isinstance(local_name, str):
            continue
        agent_name = sase_agent_ref_for_turn(local_name, identity).local_name
        for commit in getattr(run, "commits", ()):
            sha = getattr(commit, "sha", None)
            if isinstance(sha, str):
                indexed.setdefault((agent_name, sha), run)
    return indexed


def prepare_deferred_prompt_archive(
    target: ProjectTarget,
    request: AgentPublicationOutboxItem,
    git_runner: GitRunner,
    *,
    prompt_runs: dict[tuple[str, str], InventoryRun],
) -> _DeferredPromptPrepareResult:
    """Regenerate one queued prompt archive in the active sidecar transaction.

    Returns whether an archive was written. A missing local source is no longer
    treated as success; callers classify that case through the recovery policy.
    A blocked or unverified prompt is withheld without writing public bytes.
    """

    matching = prompt_runs.get((request.local_agent, request.primary_revision))
    source_label = request.artifacts_dir or (
        matching.source_label if matching is not None else None
    )
    if source_label is None:
        return _DeferredPromptPrepareResult(wrote=False)
    from sase.legacy_xprompt_names import resolve_raw_prompt_path

    artifacts_dir = Path(source_label)
    if resolve_raw_prompt_path(artifacts_dir) is None:
        return _DeferredPromptPrepareResult(wrote=False)
    from sase.agents_sync.prompt_archive.inputs import read_prompt_archive_inputs
    from sase.agents_sync.prompt_archive.protection import protection_scope_for_target
    from sase.agents_sync.prompt_archive.publish import prepare_prompt_archive

    # A planner archive is named after its plan, links to it, and carries the
    # plan snapshot as its body. Its approval recorded those inputs beside the
    # artifacts; rows without a record keep the default agent-derived archive.
    inputs = read_prompt_archive_inputs(
        artifacts_dir, primary_revision=request.primary_revision
    )
    prepared = prepare_prompt_archive(
        target=target,
        repo=target.sidecar_path,
        agent_name=request.local_agent,
        global_agent=request.global_agent,
        primary_revision=request.primary_revision,
        commit_cwd=(
            Path(request.commit_cwd)
            if request.commit_cwd is not None
            else target.primary_checkout
        ),
        agent_artifacts_dir=artifacts_dir,
        prompt_content=None if inputs is None else inputs.prompt_content,
        plan_ref=None if inputs is None else inputs.plan_ref,
        prompt_name=None if inputs is None else inputs.prompt_name,
        yyyymm=None if inputs is None else inputs.yyyymm,
        git_runner=git_runner,
        protection_scope=protection_scope_for_target(target),
    )
    if prepared.protection_status is not None:
        return _DeferredPromptPrepareResult(
            wrote=False,
            protection_status=prepared.protection_status,
            prepared_archive=prepared,
        )
    return _DeferredPromptPrepareResult(wrote=True, prepared_archive=prepared)


def _deferred_prompt_restore_is_pending(
    *,
    status: str,
    reason: str,
    restore_error: str | None,
    created_at: float,
    now: float,
    grace_seconds: float = DEFERRED_PROMPT_GRACE_SECONDS,
) -> bool:
    """Return whether an unavailable restore is still inside the grace window.

    Legacy rows with ``created_at == 0.0`` are always past grace. An explicit
    restore exception is never pending: only the conservative unavailable
    classification of a missing local source qualifies.
    """

    if restore_error is not None:
        return False
    if status != PROMPT_STATUS_UNAVAILABLE:
        return False
    if reason != UNRESOLVED_PROMPT_ARCHIVE_REASON:
        return False
    if created_at <= 0.0:
        return False
    return now - created_at < grace_seconds


def restore_deferred_prompt_archives(
    target: ProjectTarget,
    requests: tuple[AgentPublicationOutboxItem, ...],
    git_runner: GitRunner,
    *,
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
    prepared_archives: dict[tuple[str, str], PreparedPromptArchive] | None = None,
    now: float | None = None,
) -> dict[tuple[str, str], DeferredPromptRestoreFailure]:
    """Regenerate every queued prompt archive, reporting per-request failures.

    One unrecoverable request must not abort a whole-project sync, so a failure
    becomes an entry keyed by the request's logical key instead of an
    exception. Callers keep those requests queued rather than acknowledging
    them. A missing local source does not prove there was no prompt obligation.
    Young unavailable restores are marked ``pending`` so callers can skip
    digest errors and attempt charges during the grace window.
    """

    if not requests:
        return {}
    observed = time.time() if now is None else now
    prompt_runs = prompt_runs_by_request(inventory, identity)
    archived_agents = _prompt_archive_agents(target.sidecar_path, identity)
    failures: dict[tuple[str, str], DeferredPromptRestoreFailure] = {}
    owner = identity.owner
    for request in requests:
        restore_error: str | None = None
        wrote = False
        protection_status: str | None = None
        matching = prompt_runs.get((request.local_agent, request.primary_revision))
        local_source_present = _local_prompt_source_present(matching, request)
        try:
            prepared = prepare_deferred_prompt_archive(
                target,
                request,
                git_runner,
                prompt_runs=prompt_runs,
            )
            wrote = prepared.wrote
            protection_status = prepared.protection_status
            if (
                prepared_archives is not None
                and prepared.wrote
                and prepared.prepared_archive is not None
            ):
                prepared_archives[request.logical_key] = prepared.prepared_archive
        except PublicationDrainTimedOut:
            raise
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            restore_error = (
                "could not restore deferred prompt archive for "
                f"{request.global_agent}@{request.primary_revision[:12]}: {exc}"
            )
        if protection_status is not None:
            from sase.agents_sync.prompt_archive.protection import (
                protection_skip_reason,
            )

            failures[request.logical_key] = DeferredPromptRestoreFailure(
                message=protection_skip_reason(protection_status),
            )
            continue
        decision = classify_deferred_prompt_obligation(
            restore_wrote=wrote,
            restore_error=restore_error,
            local_source_present=local_source_present,
            archive_present=_prompt_archive_present(archived_agents, request, identity),
            prompt_file_in_snapshot=(
                snapshot_prompt_file_present(target, request, owner)
                if isinstance(owner, AgentOwnerIdentity)
                else None
            ),
        )
        if decision.blocks_acknowledgment:
            message = _prompt_restore_failure(request, restore_error, decision)
            pending = _deferred_prompt_restore_is_pending(
                status=decision.status,
                reason=decision.reason,
                restore_error=restore_error,
                created_at=request.created_at,
                now=observed,
            )
            if pending:
                log.info(
                    "deferred prompt archive restore still pending: %s",
                    message,
                )
            failures[request.logical_key] = DeferredPromptRestoreFailure(
                message=message,
                pending=pending,
            )
    return failures


def _prompt_restore_failure(
    request: AgentPublicationOutboxItem,
    restore_error: str | None,
    decision: DeferredPromptDecision,
) -> str:
    return restore_error or (
        "could not restore deferred prompt archive for "
        f"{request.global_agent}@{request.primary_revision[:12]}: "
        f"{decision.reason}"
    )


def _local_prompt_source_present(
    matching: InventoryRun | None,
    request: AgentPublicationOutboxItem,
) -> bool:
    source_label = request.artifacts_dir or (
        matching.source_label if matching is not None else None
    )
    if source_label is None:
        return False
    from sase.legacy_xprompt_names import resolve_raw_prompt_path

    return resolve_raw_prompt_path(Path(source_label)) is not None


def _prompt_archive_agents(
    repo: Path,
    identity: AgentIdentitySnapshot,
) -> set[str]:
    """Index the session names represented by existing prompt archives."""

    prompts_root = repo / "prompts"
    if not prompts_root.is_dir():
        return set()
    archived_agents: set[str] = set()
    for month_dir in sorted(path for path in prompts_root.iterdir() if path.is_dir()):
        try:
            prompts_month_dir(repo, month_dir.name)
        except ValueError:
            continue
        for path in month_dir.glob("*.md"):
            if path.name == "README.md":
                continue
            try:
                parsed = parse_plan_header_block(path.read_text(encoding="utf-8"))
            except PublicationDrainTimedOut:
                raise
            except Exception:
                continue
            archived_agents.update(
                sase_agent_ref_for_turn(entry.label, identity).local_name
                for section in parsed.sections
                if section.kind is PlanHeaderSectionKind.AGENTS
                for entry in section.entries
            )
    return archived_agents


def _prompt_archive_present(
    archived_agents: set[str],
    request: AgentPublicationOutboxItem,
    identity: AgentIdentitySnapshot,
) -> bool:
    """Whether an archive belongs to this request's agent session."""

    requested_agent = sase_agent_ref_for_turn(request.local_agent, identity).local_name
    return requested_agent in archived_agents


__all__ = [
    "DEFERRED_PROMPT_GRACE_SECONDS",
    "DeferredPromptRestoreFailure",
    "UNRESOLVED_PROMPT_ARCHIVE_REASON",
    "prepare_deferred_prompt_archive",
    "prompt_runs_by_request",
    "restore_deferred_prompt_archives",
]
