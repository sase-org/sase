"""Regenerate deferred prompt archives inside an open sidecar transaction.

A prompt archive that could not be published while the primary commit was
landing is not lost.  The durable agent-hood publication request that carries
the hood carries its prompt too: both the commit-time drain and the full
``sase agent sync`` pass call in here while they already hold the agents lock,
so one lock acquisition -- and one durable retry -- covers both.
"""

from __future__ import annotations

from pathlib import Path

from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.inventory_models import InventoryRun
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.prompt_archive.paths import prompts_month_dir
from sase.agents_sync.publication_completion import snapshot_prompt_file_present
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentIdentitySnapshot, AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    DeferredPromptDecision,
    classify_deferred_prompt_obligation,
)
from sase.sase_agent import sase_agent_ref_for_turn
from sase.sdd.plan_header_block import PlanHeaderSectionKind, parse_plan_header_block


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
) -> bool:
    """Regenerate one queued prompt archive in the active sidecar transaction.

    Returns whether an archive was written. A missing local source is no longer
    treated as success; callers classify that case through the recovery policy.
    """

    matching = prompt_runs.get((request.local_agent, request.primary_revision))
    if matching is None or matching.source_label is None:
        return False
    from sase.legacy_xprompt_names import resolve_raw_prompt_path

    artifacts_dir = Path(matching.source_label)
    if resolve_raw_prompt_path(artifacts_dir) is None:
        return False
    from sase.agents_sync.prompt_archive.publish import prepare_prompt_archive

    prepare_prompt_archive(
        target=target,
        repo=target.sidecar_path,
        agent_name=matching.local_name,
        global_agent=matching.global_name,
        primary_revision=request.primary_revision,
        commit_cwd=target.primary_checkout,
        agent_artifacts_dir=artifacts_dir,
        git_runner=git_runner,
    )
    return True


def restore_deferred_prompt_archives(
    target: ProjectTarget,
    requests: tuple[AgentPublicationOutboxItem, ...],
    git_runner: GitRunner,
    *,
    identity: AgentIdentitySnapshot,
    inventory: ProjectHoodInventory,
) -> dict[tuple[str, str], str]:
    """Regenerate every queued prompt archive, reporting per-request failures.

    One unrecoverable request must not abort a whole-project sync, so a failure
    becomes an entry keyed by the request's logical key instead of an
    exception. Callers keep those requests queued rather than acknowledging
    them. A missing local source does not prove there was no prompt obligation.
    """

    if not requests:
        return {}
    prompt_runs = prompt_runs_by_request(inventory, identity)
    failures: dict[tuple[str, str], str] = {}
    owner = identity.owner
    for request in requests:
        restore_error: str | None = None
        wrote = False
        matching = prompt_runs.get((request.local_agent, request.primary_revision))
        local_source_present = _local_prompt_source_present(matching)
        try:
            wrote = prepare_deferred_prompt_archive(
                target,
                request,
                git_runner,
                prompt_runs=prompt_runs,
            )
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            restore_error = (
                "could not restore deferred prompt archive for "
                f"{request.global_agent}@{request.primary_revision[:12]}: {exc}"
            )
        decision = classify_deferred_prompt_obligation(
            restore_wrote=wrote,
            restore_error=restore_error,
            local_source_present=local_source_present,
            archive_present=_prompt_archive_present(target.sidecar_path, request),
            prompt_file_in_snapshot=(
                snapshot_prompt_file_present(target, request, owner)
                if isinstance(owner, AgentOwnerIdentity)
                else None
            ),
        )
        if decision.blocks_acknowledgment:
            failures[request.logical_key] = _prompt_restore_failure(
                request, restore_error, decision
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


def _local_prompt_source_present(matching: InventoryRun | None) -> bool:
    if matching is None or matching.source_label is None:
        return False
    from sase.legacy_xprompt_names import resolve_raw_prompt_path

    return resolve_raw_prompt_path(Path(matching.source_label)) is not None


def _prompt_archive_present(
    repo: Path,
    request: AgentPublicationOutboxItem,
) -> bool:
    prompts_root = repo / "prompts"
    if not prompts_root.is_dir():
        return False
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
            except Exception:
                continue
            if any(
                entry.label in {request.global_agent, request.local_agent}
                for section in parsed.sections
                if section.kind is PlanHeaderSectionKind.AGENTS
                for entry in section.entries
            ):
                return True
    return False


__all__ = [
    "prepare_deferred_prompt_archive",
    "prompt_runs_by_request",
    "restore_deferred_prompt_archives",
]
