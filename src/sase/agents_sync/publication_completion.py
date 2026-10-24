"""Observe published sidecar state and decide whether a request is fulfilled."""

from __future__ import annotations

from pathlib import Path

from sase._interruptions import PublicationDrainTimedOut
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox_models import (
    PUBLICATION_SCOPE_REVISION,
    AgentPublicationOutboxItem,
)
from sase.agents_sync.publication_validation import snapshot_path
from sase.agents_sync.v2_io import read_hood_snapshot
from sase.agents_sync.v2_models import SESSION_CONTAINER_KINDS, V2HoodSnapshot
from sase.core.agent_identity_facade import AgentOwnerIdentity
from sase.core.agent_publication_recovery import (
    PublicationCompletionDecision,
    decide_publication_request_completion,
)
from sase.sase_agent import agent_session_page_path


def publication_request_fulfilled(
    target: ProjectTarget,
    item: AgentPublicationOutboxItem,
    owner: AgentOwnerIdentity,
) -> bool:
    """Return whether *item* has its required page and requested revision."""

    return _publication_request_completion(target, item, owner).fulfilled


def stale_requested_revision_rows(
    target: ProjectTarget,
    items: tuple[AgentPublicationOutboxItem, ...],
    owner: AgentOwnerIdentity,
) -> tuple[AgentPublicationOutboxItem, ...]:
    """Return revision-scope rows absent from their published run's commits.

    Each returned row names a requested revision that no matching published
    run carries even though the required page exists, so the ack gate will
    keep refusing it until `sase agent sync --repair-revisions --apply`
    rekeys it. Snapshots that cannot be read are skipped, never counted.
    """

    stale: list[AgentPublicationOutboxItem] = []
    snapshots: dict[str, V2HoodSnapshot | None] = {}
    observed: dict[str, tuple[list[dict[str, object]], list[dict[str, object]]]] = {}
    for item in items:
        if item.scope != PUBLICATION_SCOPE_REVISION:
            continue
        if item.local_hood not in snapshots:
            snapshots[item.local_hood] = _load_request_snapshot(
                target.sidecar_path, owner, item.local_hood
            )
        snapshot = snapshots[item.local_hood]
        if snapshot is None:
            continue
        if item.local_hood not in observed:
            observed[item.local_hood] = _completion_observations(snapshot)
        run_observations, container_observations = observed[item.local_hood]
        decision = decide_publication_request_completion(
            global_agent=item.global_agent,
            local_agent=item.local_agent,
            primary_revision=item.primary_revision,
            pages=_completion_pages(target.sidecar_path, item),
            runs=run_observations,
            containers=container_observations,
            scope=item.scope,
        )
        if (
            not decision.fulfilled
            and decision.reason
            == "required page exists without the requested primary revision"
        ):
            stale.append(item)
    return tuple(stale)


def _publication_request_completion(
    target: ProjectTarget,
    item: AgentPublicationOutboxItem,
    owner: AgentOwnerIdentity,
) -> PublicationCompletionDecision:
    """Classify one request against validated snapshot identity and page paths."""

    snapshot = _load_request_snapshot(target.sidecar_path, owner, item.local_hood)
    run_observations: list[dict[str, object]] = []
    container_observations: list[dict[str, object]] = []
    if snapshot is not None:
        run_observations, container_observations = _completion_observations(snapshot)
    return decide_publication_request_completion(
        global_agent=item.global_agent,
        local_agent=item.local_agent,
        primary_revision=item.primary_revision,
        pages=_completion_pages(target.sidecar_path, item),
        runs=run_observations,
        containers=container_observations,
        scope=item.scope,
    )


def _completion_pages(
    repo: Path,
    item: AgentPublicationOutboxItem,
) -> list[dict[str, object]]:
    """Return the required-page observations for one request."""

    candidates = (
        f"agents/{item.global_agent}/README.md",
        agent_session_page_path(item.global_agent),
        f"families/{item.global_agent}.md",
    )
    return [
        {
            "path": path,
            "exists": _safe_sidecar_file(repo, path).is_file(),
        }
        for path in candidates
    ]


def _completion_observations(
    snapshot: V2HoodSnapshot,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Return the run and container observations for one hood snapshot."""

    runs_by_id = {run.source_run_id: run for run in snapshot.runs}
    run_observations: list[dict[str, object]] = [
        {
            "global_name": run.global_name,
            "local_name": run.local_name,
            "commit_shas": [commit.sha for commit in run.commits],
            "has_prompt_file": any(kind == "prompt" for kind, _ref in run.files),
        }
        for run in snapshot.runs
    ]
    container_observations: list[dict[str, object]] = [
        {
            "kind": container.kind,
            "global_name": container.global_name,
            "member_global_names": [
                runs_by_id[member_id].global_name
                for member_id in container.member_source_run_ids
                if member_id in runs_by_id
            ],
            "commit_shas": [commit.sha for commit in container.commits],
        }
        for container in snapshot.containers
        if container.kind in SESSION_CONTAINER_KINDS
    ]
    return run_observations, container_observations


def snapshot_prompt_file_present(
    target: ProjectTarget,
    item: AgentPublicationOutboxItem,
    owner: AgentOwnerIdentity,
) -> bool | None:
    """Return whether the published run for *item* includes a prompt file.

    ``None`` means the snapshot or matching run is unavailable, so a missing
    local source cannot prove there was no prompt obligation.
    """

    snapshot = _load_request_snapshot(target.sidecar_path, owner, item.local_hood)
    if snapshot is None:
        return None
    matching = [
        run
        for run in snapshot.runs
        if run.global_name == item.global_agent or run.local_name == item.local_agent
    ]
    if not matching:
        session_members = [
            run
            for container in snapshot.containers
            if container.kind in SESSION_CONTAINER_KINDS
            and container.global_name == item.global_agent
            for run in snapshot.runs
            if run.source_run_id in container.member_source_run_ids
        ]
        matching = session_members
    if not matching:
        return None
    return any(kind == "prompt" for run in matching for kind, _ref in run.files)


def _load_request_snapshot(
    repo: Path,
    owner: AgentOwnerIdentity,
    local_hood: str,
) -> V2HoodSnapshot | None:
    path = repo / snapshot_path(owner, local_hood)
    if not path.is_file():
        return None
    try:
        return read_hood_snapshot(path)
    except PublicationDrainTimedOut:
        raise
    except Exception:
        return None


def _safe_sidecar_file(repo: Path, relative: str) -> Path:
    root = repo.resolve(strict=False)
    candidate = (root / relative).resolve(strict=False)
    if not candidate.is_relative_to(root):
        return root / "__unsafe__"
    return candidate


__all__ = [
    "publication_request_fulfilled",
    "snapshot_prompt_file_present",
    "stale_requested_revision_rows",
]
