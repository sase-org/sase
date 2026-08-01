"""Off-thread data collection for the Artifacts Beads pane."""

from __future__ import annotations

from pathlib import Path

from sase.bead.model import IssueType

from .beads_data_models import BeadsSnapshot, PendingTriage, ProjectBead
from .beads_data_sources import (
    _hierarchical_id_key,
    _project_beads_dir,
    _project_document_roots,
    _resolve_projects,
    _timestamp_recency_key,
    load_pending_triage as _load_pending_triage,
    load_project_beads as _load_project_beads,
    notifications_mtime_key as _notifications_mtime_key,
    resolve_plan_link as _resolve_plan_link,
    store_mtime_key as _store_mtime_key,
)


def load_beads_snapshot(
    project: str | None,
    *,
    previous: BeadsSnapshot | None = None,
    force: bool = False,
) -> BeadsSnapshot:
    """Load one or all projects; callers must run this on a worker thread."""
    resolved = _resolve_projects(project)
    project_names = tuple(item.project for item in resolved)
    beads_by_project: dict[str, Path | None] = {}
    plans_roots: dict[str, Path | None] = {}
    store_keys: list[tuple[str, object]] = []
    for item in resolved:
        beads_dir = _project_beads_dir(item.project)
        document_roots = _project_document_roots(item)
        beads_by_project[item.project] = beads_dir
        plans_roots[item.project] = document_roots.get("plans")
        store_keys.append((item.project, _store_mtime_key(beads_dir)))

    source_key: tuple[object, ...] = (
        project,
        tuple(
            (item.project, item.display_name, item.workspace_dir) for item in resolved
        ),
        tuple(store_keys),
        _notifications_mtime_key(),
    )
    if not force and previous is not None and previous.source_key == source_key:
        return previous

    tasks: list[ProjectBead] = []
    epics: list[ProjectBead] = []
    phases_by_epic: dict[tuple[str, str], tuple[ProjectBead, ...]] = {}
    ready_ids: set[tuple[str, str]] = set()
    blocked_ids: set[tuple[str, str]] = set()
    plan_links: dict[tuple[str, str], str] = {}
    errors: dict[str, str] = {}

    for item in resolved:
        project_name = item.project
        beads_dir = beads_by_project[project_name]
        if beads_dir is None:
            if project is not None:
                errors[project_name] = "No bead store is available for this project."
            continue
        try:
            issues, project_ready_ids, project_blocked_ids = _load_project_beads(
                beads_dir
            )
        except Exception as exc:
            errors[project_name] = f"Unable to read beads: {exc}"
            continue

        project_tasks = tuple(
            issue for issue in issues if issue.issue_type is IssueType.TASK
        )
        tasks.extend(ProjectBead(project_name, issue) for issue in project_tasks)
        project_epics = tuple(
            issue for issue in issues if issue.issue_type is IssueType.PLAN
        )
        epics.extend(ProjectBead(project_name, issue) for issue in project_epics)
        for epic in project_epics:
            phases = tuple(
                ProjectBead(project_name, issue)
                for issue in sorted(
                    (
                        issue
                        for issue in issues
                        if issue.issue_type is IssueType.PHASE
                        and issue.parent_id == epic.id
                    ),
                    key=lambda issue: _hierarchical_id_key(issue.id),
                )
            )
            phases_by_epic[(project_name, epic.id)] = phases
        ready_ids.update((project_name, issue_id) for issue_id in project_ready_ids)
        blocked_ids.update((project_name, issue_id) for issue_id in project_blocked_ids)
        plans_root = plans_roots[project_name]
        for issue in issues:
            if issue.issue_type not in {
                IssueType.TASK,
                IssueType.PHASE,
                IssueType.PLAN,
            }:
                continue
            if not issue.design.strip():
                continue
            plan_links[(project_name, issue.id)] = _resolve_plan_link(
                issue.design,
                workspace_dir=item.workspace_dir,
                plans_root=plans_root,
            )

    triage_gates = {
        key: gate
        for key, gate in _load_pending_triage().items()
        if key[0] in project_names
    }

    def task_order(item: ProjectBead) -> tuple[object, ...]:
        issue = item.issue
        status_order = {
            "ready": 1,
            "in_progress": 2,
            "claimed": 3,
            "open": 4,
            "closed": 5,
        }
        return (
            0 if (item.project, issue.id) in triage_gates else 1,
            status_order[issue.status.value],
            _timestamp_recency_key(issue.updated_at or issue.created_at),
            _hierarchical_id_key(issue.id),
            item.project,
        )

    def epic_order(item: ProjectBead) -> tuple[object, ...]:
        return (
            _timestamp_recency_key(item.issue.updated_at or item.issue.created_at),
            _hierarchical_id_key(item.issue.id),
            item.project,
        )

    tasks.sort(key=task_order)
    epics.sort(key=epic_order)
    return BeadsSnapshot(
        project=project,
        projects=project_names,
        display_names={item.project: item.display_name for item in resolved},
        beads_dirs={
            name: None if path is None else str(path)
            for name, path in beads_by_project.items()
        },
        workspace_dirs={item.project: item.workspace_dir for item in resolved},
        tasks=tuple(tasks),
        epics=tuple(epics),
        phases_by_epic=phases_by_epic,
        ready_ids=frozenset(ready_ids),
        blocked_ids=frozenset(blocked_ids),
        plan_links=plan_links,
        triage_gates=triage_gates,
        source_key=source_key,
        errors=errors,
    )


__all__ = ["BeadsSnapshot", "PendingTriage", "ProjectBead", "load_beads_snapshot"]
