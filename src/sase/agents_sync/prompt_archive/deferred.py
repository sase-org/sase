"""Regenerate deferred prompt archives inside an open sidecar transaction.

A prompt archive that could not be published while the primary commit was
landing is not lost.  The durable agent-hood publication request that carries
the hood carries its prompt too: both the commit-time drain and the full
``sase agent sync`` pass call in here while they already hold the agents lock,
so one lock acquisition -- and one durable retry -- covers both.
"""

from __future__ import annotations

from pathlib import Path

from sase.agent_lanes import lane_ref_for_agent
from sase.agents_sync.git import GitRunner
from sase.agents_sync.inventory import ProjectHoodInventory
from sase.agents_sync.inventory_models import InventoryRun
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import AgentPublicationOutboxItem
from sase.core.agent_identity_facade import AgentIdentitySnapshot


def prompt_runs_by_request(
    inventory: ProjectHoodInventory,
    identity: AgentIdentitySnapshot,
) -> dict[tuple[str, str], InventoryRun]:
    """Index local runs by the (lane, revision) pair a request names."""

    indexed: dict[tuple[str, str], InventoryRun] = {}
    for run in inventory.runs:
        local_name = getattr(run, "local_name", None)
        if not isinstance(local_name, str):
            continue
        lane = lane_ref_for_agent(local_name, identity).local_name
        for commit in getattr(run, "commits", ()):
            sha = getattr(commit, "sha", None)
            if isinstance(sha, str):
                indexed.setdefault((lane, sha), run)
    return indexed


def prepare_deferred_prompt_archive(
    target: ProjectTarget,
    request: AgentPublicationOutboxItem,
    git_runner: GitRunner,
    *,
    prompt_runs: dict[tuple[str, str], InventoryRun],
) -> bool:
    """Regenerate one queued prompt archive in the active sidecar transaction.

    Returns whether an archive was written.  A request whose run is no longer
    in the local pool has no recoverable prompt bytes, so it is skipped rather
    than treated as a failure.
    """

    matching = prompt_runs.get((request.local_agent, request.primary_revision))
    if matching is None or matching.source_label is None:
        return False
    artifacts_dir = Path(matching.source_label)
    if not (artifacts_dir / "raw_xprompt.md").is_file():
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
    them.
    """

    if not requests:
        return {}
    prompt_runs = prompt_runs_by_request(inventory, identity)
    failures: dict[tuple[str, str], str] = {}
    for request in requests:
        try:
            prepare_deferred_prompt_archive(
                target,
                request,
                git_runner,
                prompt_runs=prompt_runs,
            )
        except Exception as exc:  # noqa: BLE001 - durable auxiliary boundary
            failures[request.logical_key] = (
                "could not restore deferred prompt archive for "
                f"{request.global_agent}@{request.primary_revision[:12]}: {exc}"
            )
    return failures


__all__ = [
    "prepare_deferred_prompt_archive",
    "prompt_runs_by_request",
    "restore_deferred_prompt_archives",
]
