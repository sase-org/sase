"""Regenerate deferred prompt archives inside an open sidecar transaction.

A prompt archive that could not be published while the primary commit was
landing is not lost.  The durable agent-hood publication request that carries
the hood carries its prompt too: both the commit-time drain and the full
``sase agent sync`` pass call in here while they already hold the agents lock,
so one lock acquisition -- and one durable retry -- covers both.
"""

from __future__ import annotations

from collections.abc import Callable
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
from sase.agents_sync.prompt_archive.source import prompt_source_dirs
from sase.agents_sync.publication_completion import snapshot_prompt_file_present
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.agents_sync.prompt_archive.terminal import (
    terminal_prompt_archive_reason,
)
from sase.core.agent_publication_recovery import (
    PROMPT_STATUS_UNAVAILABLE,
    PROMPT_STATUS_UNRECOVERABLE,
    DeferredPromptDecision,
    classify_deferred_prompt_obligation,
)
from sase.sase_agent import sase_agent_ref_for_turn
from sase.sdd.plan_header_block import PlanHeaderSectionKind, parse_plan_header_block

log = logging.getLogger(__name__)

# Young unresolved archives self-resolve; 30 minutes covers the worst observed case.
DEFERRED_PROMPT_GRACE_SECONDS = 1800
# Every deferred prompt restore failure recorded on an outbox row starts here.
DEFERRED_PROMPT_RESTORE_ERROR_PREFIX = "could not restore deferred prompt archive for "
UNRESOLVED_PROMPT_ARCHIVE_REASON = (
    "prompt archive is unresolved and a missing local source does not prove "
    "there was no prompt obligation"
)


@dataclass(frozen=True, slots=True)
class DeferredPromptRestoreFailure:
    """One restore failure, plus whether it is still inside the grace window."""

    message: str
    pending: bool = False
    terminal: bool = False


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
    from sase.legacy_xprompt_names import resolve_raw_prompt_path

    source_dirs = [
        Path(candidate)
        for candidate in _prompt_source_candidates(matching, request)
        if resolve_raw_prompt_path(Path(candidate)) is not None
    ]
    if not source_dirs:
        return _DeferredPromptPrepareResult(wrote=False)

    # A row can name a stale artifacts dir while the inventory run still
    # points at the live one, so every candidate with a prompt source is
    # tried in order: the row's dir and starter chain, then the run's source
    # label and starter chain. A candidate that raises is skipped in favor of
    # the next one; only the last candidate's error propagates.
    last_error: Exception | None = None
    for artifacts_dir in source_dirs:
        try:
            prepared = _prepare_prompt_archive_from_dir(
                target, request, artifacts_dir, git_runner
            )
        except PublicationDrainTimedOut:
            raise
        except Exception as exc:  # noqa: BLE001 - try the next source
            last_error = exc
            continue
        if prepared.protection_status is not None:
            return _DeferredPromptPrepareResult(
                wrote=False,
                protection_status=prepared.protection_status,
                prepared_archive=prepared,
            )
        return _DeferredPromptPrepareResult(wrote=True, prepared_archive=prepared)
    assert last_error is not None
    raise last_error


def _prepare_prompt_archive_from_dir(
    target: ProjectTarget,
    request: AgentPublicationOutboxItem,
    artifacts_dir: Path,
    git_runner: GitRunner,
) -> PreparedPromptArchive:
    """Prepare one prompt archive from one candidate source directory."""

    from sase.agents_sync.prompt_archive.inputs import read_prompt_archive_inputs
    from sase.agents_sync.prompt_archive.protection import protection_scope_for_target
    from sase.agents_sync.prompt_archive.publish import prepare_prompt_archive

    # A planner archive is named after its plan, links to it, and carries the
    # plan snapshot as its body. Its approval recorded those inputs beside the
    # artifacts; rows without a record keep the default agent-derived archive.
    inputs = read_prompt_archive_inputs(
        artifacts_dir, primary_revision=request.primary_revision
    )
    return prepare_prompt_archive(
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
                DEFERRED_PROMPT_RESTORE_ERROR_PREFIX
                + f"{request.global_agent}@{request.primary_revision[:12]}: {exc}"
            )
        if protection_status is not None:
            from sase.agents_sync.prompt_archive.protection import (
                protection_skip_reason,
            )

            failures[request.logical_key] = DeferredPromptRestoreFailure(
                message=protection_skip_reason(protection_status),
            )
            continue
        archive_present = _prompt_archive_present(archived_agents, request, identity)
        prompt_in_snapshot = (
            snapshot_prompt_file_present(target, request, owner)
            if isinstance(owner, AgentOwnerIdentity)
            else None
        )
        decision = classify_deferred_prompt_obligation(
            restore_wrote=wrote,
            restore_error=restore_error,
            local_source_present=local_source_present,
            archive_present=archive_present,
            prompt_file_in_snapshot=prompt_in_snapshot,
            past_grace_period=_past_grace_period(request, observed),
            attempts_exhausted=_attempts_exhausted(request),
        )
        if decision.blocks_acknowledgment:
            terminal = decision.status == PROMPT_STATUS_UNRECOVERABLE
            if terminal:
                message = _terminal_prompt_failure(
                    request,
                    matching=matching,
                    archive_present=archive_present,
                    prompt_in_snapshot=prompt_in_snapshot,
                )
            else:
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
            if terminal:
                log.warning(
                    "deferred prompt archive is unrecoverable: %s",
                    message,
                )
            failures[request.logical_key] = DeferredPromptRestoreFailure(
                message=message,
                pending=pending,
                terminal=terminal,
            )
    return failures


def classify_quarantined_prompt_archives(
    target: ProjectTarget,
    requests: tuple[AgentPublicationOutboxItem, ...],
    *,
    identity: AgentIdentitySnapshot,
    load_inventory: Callable[[], ProjectHoodInventory],
    now: float | None = None,
) -> dict[tuple[str, str], str]:
    """Return the terminal message for each request the classifier calls unrecoverable.

    This is the probe-only twin of :func:`restore_deferred_prompt_archives`
    for rows that left the active queue: it never regenerates or writes an
    archive. Each row goes through the same Rust classifier with the same
    probes -- the row's ``artifacts_dir`` and starter chain, the matching
    inventory run's ``source_label`` and starter chain, the sidecar's archived
    sessions, and the published snapshot. *load_inventory* runs at most once,
    and only when no row or starter has a prompt source: the run's source label
    can only add a source, never remove one, so skipping it then changes no
    classifier input.
    """

    if not requests:
        return {}
    observed = time.time() if now is None else now
    needs_runs = any(
        not _local_prompt_source_present(None, request) for request in requests
    )
    prompt_runs = (
        prompt_runs_by_request(load_inventory(), identity) if needs_runs else {}
    )
    archived_agents = _prompt_archive_agents(target.sidecar_path, identity)
    owner = identity.owner
    terminal: dict[tuple[str, str], str] = {}
    for request in requests:
        matching = prompt_runs.get((request.local_agent, request.primary_revision))
        archive_present = _prompt_archive_present(archived_agents, request, identity)
        prompt_in_snapshot = (
            snapshot_prompt_file_present(target, request, owner)
            if isinstance(owner, AgentOwnerIdentity)
            else None
        )
        decision = classify_deferred_prompt_obligation(
            restore_wrote=False,
            restore_error=None,
            local_source_present=_local_prompt_source_present(matching, request),
            archive_present=archive_present,
            prompt_file_in_snapshot=prompt_in_snapshot,
            past_grace_period=_past_grace_period(request, observed),
            attempts_exhausted=_attempts_exhausted(request),
        )
        if decision.status != PROMPT_STATUS_UNRECOVERABLE:
            continue
        terminal[request.logical_key] = _terminal_prompt_failure(
            request,
            matching=matching,
            archive_present=archive_present,
            prompt_in_snapshot=prompt_in_snapshot,
        )
    return terminal


def _prompt_restore_failure(
    request: AgentPublicationOutboxItem,
    restore_error: str | None,
    decision: DeferredPromptDecision,
) -> str:
    return restore_error or (
        DEFERRED_PROMPT_RESTORE_ERROR_PREFIX
        + f"{request.global_agent}@{request.primary_revision[:12]}: "
        f"{decision.reason}"
    )


def _prompt_source_candidates(
    matching: InventoryRun | None,
    request: AgentPublicationOutboxItem,
) -> list[str]:
    """Return every known local directory that could hold the prompt source.

    The row's ``artifacts_dir`` and the inventory run's ``source_label`` can
    disagree when the row was queued against a stale directory, so both are
    probed along with each directory's monitor-starter chain.
    """

    source_candidates: list[str] = []
    if request.artifacts_dir:
        source_candidates.append(request.artifacts_dir)
    source_label = getattr(matching, "source_label", None)
    if isinstance(source_label, str) and source_label:
        source_candidates.append(source_label)

    candidates: list[str] = []
    seen: set[Path] = set()
    for candidate in source_candidates:
        for directory in prompt_source_dirs(candidate):
            if directory in seen:
                continue
            seen.add(directory)
            candidates.append(str(directory))
    return candidates


def _dir_has_prompt_source(directory: str) -> bool:
    from sase.legacy_xprompt_names import resolve_raw_prompt_path

    return resolve_raw_prompt_path(Path(directory)) is not None


def _local_prompt_source_present(
    matching: InventoryRun | None,
    request: AgentPublicationOutboxItem,
) -> bool:
    return any(
        _dir_has_prompt_source(candidate)
        for candidate in _prompt_source_candidates(matching, request)
    )


def _past_grace_period(
    request: AgentPublicationOutboxItem,
    now: float,
) -> bool:
    """Return whether *request* is past the deferred-prompt grace period."""

    if request.created_at <= 0.0:
        return True
    return now - request.created_at >= DEFERRED_PROMPT_GRACE_SECONDS


def _attempts_exhausted(request: AgentPublicationOutboxItem) -> bool:
    """Return whether *request* has no prompt retries left.

    The row is exhausted when it is already quarantined, or when this failure
    would consume its final attempt (``attempts + 1 >= max``). The terminal
    transition then retires the row over the next two passes — first recording
    the deterministic terminal message without quarantining, then retiring
    once the recorded error matches — instead of quarantining it forever.
    Anything unreadable fails closed to ``False``: a row never goes terminal
    on uncertain accounting.
    """

    if request.quarantined:
        return True
    try:
        from sase.agents_sync.publication_outbox import (
            configured_publication_max_attempts,
        )
    except Exception:
        return False
    try:
        max_attempts = configured_publication_max_attempts()
    except Exception:
        return False
    return request.attempts + 1 >= max_attempts


def _terminal_prompt_failure(
    request: AgentPublicationOutboxItem,
    *,
    matching: InventoryRun | None,
    archive_present: bool,
    prompt_in_snapshot: bool | None,
) -> str:
    """Render the terminal ``prompt_archive_unrecoverable`` failure message."""

    # The evidence is intentionally deterministic: the retiring update only
    # turns terminal when the recorded error already equals this message, so
    # per-pass numbers (attempts, age) would delay retirement by a pass each
    # time. Attempt counts live in the outbox row and the audit record.
    probed = _prompt_source_candidates(matching, request)
    evidence = (
        f"no local source in {probed or ['<no candidate dirs>']}; "
        f"sidecar archive present={archive_present}; "
        f"snapshot prompt file={prompt_in_snapshot}; "
        f"quarantined={request.quarantined}"
    )
    return (
        DEFERRED_PROMPT_RESTORE_ERROR_PREFIX
        + f"{request.global_agent}@{request.primary_revision[:12]}: "
        f"{terminal_prompt_archive_reason(evidence)}"
    )


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
    "DEFERRED_PROMPT_RESTORE_ERROR_PREFIX",
    "DeferredPromptRestoreFailure",
    "UNRESOLVED_PROMPT_ARCHIVE_REASON",
    "classify_quarantined_prompt_archives",
    "prepare_deferred_prompt_archive",
    "prompt_runs_by_request",
    "restore_deferred_prompt_archives",
]
