"""Cheap read-only proof checks for stuck planner publication rows."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
import json
from pathlib import Path

from sase.agents_sync.git import GitRunner
from sase.agents_sync.models import ProjectTarget
from sase.agents_sync.publication_outbox import (
    PUBLICATION_SCOPE_REVISION,
    AgentPublicationOutboxItem,
    list_agent_publications,
)
from sase.agents_sync._publication_planner_scope_repair_models import (
    PlannerScopeRepairReport,
    PlannerScopeRowReport,
)

_PLANNER_ARCHIVE_WINDOW_SECONDS = 10
_PLANNER_ARCHIVE_LOG_OP = "agents_sync.planner_scope_repair.archive_log"


def classify_project_planner_scopes(
    target: ProjectTarget,
    *,
    git_runner: GitRunner,
) -> PlannerScopeRepairReport:
    """Classify revision-scope outbox rows without inventory or ancestry scans."""

    items = tuple(
        item
        for item in list_agent_publications(target.project_key)
        if item.scope == PUBLICATION_SCOPE_REVISION
    )
    if not items:
        return PlannerScopeRepairReport(
            target.project_key, target.project, False, (), 0
        )

    metadata_results = {
        item.logical_key: _planner_metadata_proof(item) for item in items
    }
    unresolved = tuple(
        item for item in items if not metadata_results[item.logical_key][0]
    )
    archive_commits: dict[str, list[tuple[int, str]]] = {}
    evidence_error: str | None = None
    if unresolved:
        archive_commits, evidence_error = _planner_archive_commits(
            target, git_runner=git_runner
        )

    rows: list[PlannerScopeRowReport] = []
    for item in items:
        proven, metadata_reason = metadata_results[item.logical_key]
        evidence_kind: str | None = None
        evidence_commit: str | None = None
        reason = metadata_reason
        if proven:
            evidence_kind = "planner_metadata"
        else:
            evidence_commit = _nearby_planner_archive_commit(item, archive_commits)
            if evidence_commit is not None:
                proven = True
                evidence_kind = "planner_archive_commit"
                reason = (
                    "matching --plan archive commit is within "
                    f"{_PLANNER_ARCHIVE_WINDOW_SECONDS} seconds"
                )
            elif evidence_error is not None:
                reason = "no metadata proof; planner archive lookup failed"
            else:
                reason = (
                    "no matching approval metadata or nearby planner archive commit"
                )
        rows.append(
            PlannerScopeRowReport(
                global_agent=item.global_agent,
                local_agent=item.local_agent,
                primary_revision=item.primary_revision,
                eligible=proven,
                evidence_kind=evidence_kind,
                evidence_commit=evidence_commit,
                reason=reason,
            )
        )

    frozen_rows = tuple(rows)
    return PlannerScopeRepairReport(
        target.project_key,
        target.project,
        False,
        frozen_rows,
        sum(row.eligible for row in frozen_rows),
        evidence_error=evidence_error,
    )


def _planner_metadata_proof(item: AgentPublicationOutboxItem) -> tuple[bool, str]:
    """Check the durable plan-approval metadata named by one outbox row."""

    if item.artifacts_dir is None:
        return False, "row has no artifacts directory"
    artifacts_dir = Path(item.artifacts_dir).expanduser()
    if not artifacts_dir.is_absolute():
        return False, "row artifacts directory is not absolute"
    metadata_path = artifacts_dir / "agent_meta.json"
    try:
        with metadata_path.open(encoding="utf-8") as handle:
            metadata = json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return False, "planner metadata is missing or unreadable"
    if not isinstance(metadata, Mapping):
        return False, "planner metadata is not a JSON object"
    expected_name = f"{item.local_agent}--plan"
    if metadata.get("name") != expected_name:
        return False, "metadata does not name this agent's --plan turn"
    if metadata.get("plan_approved") is not True:
        return False, "planner turn was not approved"
    if metadata.get("workspace_head") != item.primary_revision:
        return False, "planner workspace_head does not match the row revision"
    return True, "approved planner metadata matches the row revision"


def _planner_archive_commits(
    target: ProjectTarget,
    *,
    git_runner: GitRunner,
) -> tuple[dict[str, list[tuple[int, str]]], str | None]:
    """Read planner archive commit subjects once from the sidecar history."""

    result = git_runner(
        target.sidecar_path,
        [
            "log",
            "--all",
            "--format=%ct%x09%H%x09%s",
            "--grep=archive prompt for",
            "--fixed-strings",
        ],
        network=False,
        op=_PLANNER_ARCHIVE_LOG_OP,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or f"git log exited {result.returncode}"
        return {}, detail

    commits: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for line in result.stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        timestamp, commit, subject = parts
        prefix = "chore(agents): archive prompt for "
        if not subject.startswith(prefix) or not subject.endswith("--plan"):
            continue
        local_agent = subject[len(prefix) : -len("--plan")]
        if not local_agent:
            continue
        try:
            committed_at = int(timestamp)
        except ValueError:
            continue
        commits[local_agent].append((committed_at, commit))
    return dict(commits), None


def _nearby_planner_archive_commit(
    item: AgentPublicationOutboxItem,
    commits: Mapping[str, list[tuple[int, str]]],
) -> str | None:
    """Return a nearby exact local- or global-agent ``--plan`` archive commit."""

    if item.created_at <= 0:
        return None
    identities = {item.local_agent, item.global_agent}
    nearby = [
        (abs(committed_at - item.created_at), committed_at, commit)
        for identity in identities
        for committed_at, commit in commits.get(identity, ())
        if abs(committed_at - item.created_at) <= _PLANNER_ARCHIVE_WINDOW_SECONDS
    ]
    if not nearby:
        return None
    return min(nearby)[2]


__all__ = ["classify_project_planner_scopes"]
