"""Aggregate repository and workspace counts for project management views."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from sase.core.project_lifecycle_wire import (
    ProjectRecordWire,
    effective_project_name,
)
from sase.repo_inventory import collect_repo_inventory
from sase.workspace_provider.inventory import collect_workspace_inventory

from .project_management_rendering import ProjectInventoryCounts


@dataclass(frozen=True)
class _ProjectCountsLoadResult:
    counts: dict[str, ProjectInventoryCounts]
    errors: tuple[str, ...] = ()


def _collect_project_inventory_counts(
    projects_root: Path,
    project_records: Sequence[ProjectRecordWire],
) -> _ProjectCountsLoadResult:
    """Join repo and workspace inventories into per-project aggregates."""

    project_keys = {record.project_name for record in project_records}
    project_lookup: dict[str, str] = {}
    for record in project_records:
        for name in (
            record.project_name,
            effective_project_name(record),
            *record.aliases,
        ):
            project_lookup.setdefault(name, record.project_name)

    repo_kind_counts: dict[str, dict[str, int]] = {
        key: {"primary": 0, "sidecar": 0, "linked": 0, "external": 0}
        for key in project_keys
    }
    workspace_counts = dict.fromkeys(project_keys, 0)
    claimed_workspace_counts = dict.fromkeys(project_keys, 0)
    issue_messages: dict[str, list[str]] = {key: [] for key in project_keys}
    errors: list[str] = []

    try:
        repo_inventory = collect_repo_inventory(
            projects_root,
            include_disabled=True,
        )
    except Exception as exc:
        errors.append(f"repos unavailable: {exc}")
    else:
        for repo in repo_inventory.records:
            if repo.project_key in repo_kind_counts:
                repo_kind_counts[repo.project_key][repo.kind] += 1
        for repo_issue in repo_inventory.issues:
            key = project_lookup.get(repo_issue.project)
            if key is not None:
                issue_messages[key].append(f"Repo inventory: {repo_issue.message}")

    try:
        workspace_inventory = collect_workspace_inventory(
            projects_root,
            include_disabled=True,
        )
    except Exception as exc:
        errors.append(f"workspaces unavailable: {exc}")
    else:
        for workspace in workspace_inventory.records:
            if workspace.project_key not in workspace_counts:
                continue
            workspace_counts[workspace.project_key] += 1
            if workspace.claimed:
                claimed_workspace_counts[workspace.project_key] += 1
        for workspace_issue in workspace_inventory.issues:
            key = project_lookup.get(workspace_issue.project)
            if key is not None:
                issue_messages[key].append(
                    f"Workspace inventory: {workspace_issue.message}"
                )

    counts: dict[str, ProjectInventoryCounts] = {}
    for key in project_keys:
        kinds = repo_kind_counts[key]
        counts[key] = ProjectInventoryCounts(
            repo_count=sum(kinds.values()),
            primary_repo_count=kinds["primary"],
            sidecar_repo_count=kinds["sidecar"],
            linked_repo_count=kinds["linked"],
            external_repo_count=kinds["external"],
            workspace_count=workspace_counts[key],
            claimed_workspace_count=claimed_workspace_counts[key],
            issue_messages=tuple(issue_messages[key]),
        )
    return _ProjectCountsLoadResult(counts, tuple(errors))


__all__ = [
    "_ProjectCountsLoadResult",
    "_collect_project_inventory_counts",
]
