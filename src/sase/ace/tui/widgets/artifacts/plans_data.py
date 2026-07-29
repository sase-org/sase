"""Off-thread data collection for the Artifacts Plans pane."""

from __future__ import annotations

from pathlib import Path

from sase.bead.model import Issue

from . import plans_data_documents as _documents
from .plans_data_documents import (
    LinkedPlanPayload as _LinkedPlanPayload,
    current_linked_plan_key as _current_linked_plan_key,
    load_linked_plan_document as _load_linked_plan_document_impl,
    loaded_linked_plan_key as _loaded_linked_plan_key,
    read_linked_plan_text as _read_linked_plan_text,
)
from .plans_data_models import (
    DeepArchiveFetch as _DeepArchiveFetch,
    LinkedPlanDocument,
    PlanProposal,
    PlansProject as _PlansProject,
    PlansSnapshot,
    ProjectArchive,
    ProjectIssue,
)
from .plans_data_sources import (
    DEEP_ARCHIVE_PER_PROJECT_LIMIT,
    _ARCHIVE_MERGED_LIMIT,
    _ARCHIVE_PER_PROJECT_LIMIT,
    archive_recency_key as _archive_recency_key,
    hierarchical_id_key as _hierarchical_id_key,
    load_project_archive as _load_project_archive,
    load_project_beads as _load_project_beads,
    load_proposals as _load_proposals,
    load_deep_plan_archive,
    parse_proposal_document as _parse_proposal_document,
    plan_title as _plan_title,
    project_beads_dir as _project_beads_dir,
    project_document_roots as _project_document_roots,
    proposal_key as _proposal_key,
    read_text as _read_text,
    resolve_projects as _resolve_projects,
    store_mtime_key as _store_mtime_key,
    timestamp_recency_key as _timestamp_recency_key,
    yaml_value_to_string as _yaml_value_to_string,
)

# Keep these private names available here for tests and existing integrations that
# patch the original module boundary.
_linked_plan_signature = _documents._linked_plan_signature
_resolve_linked_plan_path = _documents._resolve_linked_plan_path
_unavailable_linked_plan_payload = _documents._unavailable_linked_plan_payload


def load_plans_snapshot(
    project: str | None,
    *,
    previous: PlansSnapshot | None = None,
    force: bool = False,
) -> PlansSnapshot:
    """Collect one or all enabled projects through existing core facades.

    This function performs disk access and must run on a worker thread. Its
    source key covers bead events, committed plan files, and pending proposal
    identities so normal re-activation can reuse the mounted pane's cache.
    """
    resolved = _resolve_projects(project)
    project_names = tuple(item.project for item in resolved)
    enabled_projects = frozenset(project_names)
    proposals = tuple(
        sorted(
            _load_proposals(project, enabled_projects),
            key=lambda proposal: (
                _timestamp_recency_key(proposal.timestamp),
                proposal.notification.id,
                proposal.project,
            ),
        )
    )
    beads_by_project: dict[str, Path | None] = {}
    plans_by_project: dict[str, dict[str, Path]] = {}
    store_keys: list[tuple[str, object]] = []
    for item in resolved:
        beads_dir = _project_beads_dir(item.project)
        plans_roots = _project_document_roots(item)
        beads_by_project[item.project] = beads_dir
        plans_by_project[item.project] = plans_roots
        store_keys.append(
            (
                item.project,
                "missing"
                if beads_dir is None and not plans_roots
                else _store_mtime_key(beads_dir, plans_roots),
            )
        )

    base_source_key = (
        project,
        tuple(
            (item.project, item.display_name, item.workspace_dir) for item in resolved
        ),
        _proposal_key(proposals),
        tuple(store_keys),
    )
    source_key = (*base_source_key, _current_linked_plan_key(previous))
    if not force and previous is not None and previous.source_key == source_key:
        return previous

    from sase.bead.model import BeadTier, IssueType

    epics: list[ProjectIssue] = []
    phases_by_epic: dict[tuple[str, str], tuple[ProjectIssue, ...]] = {}
    ready_ids: set[tuple[str, str]] = set()
    blocked_ids: set[tuple[str, str]] = set()
    archive: list[ProjectArchive] = []
    linked_plan_documents: dict[tuple[str, str], LinkedPlanDocument] = {}
    archive_truncated = False
    errors: dict[str, str] = {}

    for item in resolved:
        project_name = item.project
        beads_dir = beads_by_project[project_name]
        plans_roots = plans_by_project[project_name]
        plans_root = plans_roots.get("plans")
        if beads_dir is None:
            if project is not None:
                errors[project_name] = "No bead store is available for this project."
        else:
            try:
                issues, project_ready_ids, project_blocked_ids = _load_project_beads(
                    beads_dir
                )
            except Exception as exc:
                _add_project_error(errors, project_name, f"Unable to read beads: {exc}")
            else:
                project_epics = tuple(
                    issue
                    for issue in issues
                    if issue.issue_type == IssueType.PLAN
                    and issue.tier == BeadTier.EPIC
                )
                epics.extend(
                    ProjectIssue(project_name, issue) for issue in project_epics
                )
                for epic in project_epics:
                    phases = tuple(
                        ProjectIssue(project_name, issue)
                        for issue in sorted(
                            (issue for issue in issues if issue.parent_id == epic.id),
                            key=lambda issue: _hierarchical_id_key(issue.id),
                        )
                    )
                    phases_by_epic[(project_name, epic.id)] = phases
                    if plans_root is not None:
                        linked_plan_documents.update(
                            _load_epic_linked_plan_documents(
                                project_name,
                                epic,
                                phases,
                                workspace_dir=item.workspace_dir,
                                plans_root=plans_root,
                            )
                        )
                ready_ids.update(
                    (project_name, issue_id) for issue_id in project_ready_ids
                )
                blocked_ids.update(
                    (project_name, issue_id) for issue_id in project_blocked_ids
                )

        if not plans_roots:
            if project is not None:
                _add_project_error(
                    errors,
                    project_name,
                    "No document sidecar is available for this project.",
                )
            continue

        project_archive: list[ProjectArchive] = []
        for role, root in plans_roots.items():
            try:
                role_archive = _load_project_archive(role, root)
            except Exception as exc:
                _add_project_error(
                    errors,
                    project_name,
                    f"Unable to read {role} archive: {exc}",
                )
                continue
            project_archive.extend(
                ProjectArchive(project_name, match, role) for match in role_archive
            )
        deduped_project_archive: dict[str, ProjectArchive] = {}
        for entry in project_archive:
            deduped_project_archive.setdefault(entry.match.plan.path, entry)
        ordered_project_archive = sorted(
            deduped_project_archive.values(),
            key=_archive_recency_key,
            reverse=True,
        )
        archive_truncated = (
            archive_truncated
            or len(ordered_project_archive) > _ARCHIVE_PER_PROJECT_LIMIT
        )
        archive.extend(ordered_project_archive[:_ARCHIVE_PER_PROJECT_LIMIT])

    epics.sort(
        key=lambda item: (
            _timestamp_recency_key(item.issue.created_at),
            _hierarchical_id_key(item.issue.id),
            item.project,
        )
    )
    archive.sort(key=_archive_recency_key, reverse=True)
    merged_archive_truncated = len(archive) > _ARCHIVE_MERGED_LIMIT
    archive_truncated = archive_truncated or merged_archive_truncated
    if merged_archive_truncated:
        del archive[_ARCHIVE_MERGED_LIMIT:]

    source_key = (
        *base_source_key,
        _loaded_linked_plan_key(linked_plan_documents),
    )

    return PlansSnapshot(
        project=project,
        projects=project_names,
        display_names={item.project: item.display_name for item in resolved},
        beads_dirs={
            name: None if path is None else str(path)
            for name, path in beads_by_project.items()
        },
        plans_roots={
            name: {role: str(path) for role, path in roots.items()}
            for name, roots in plans_by_project.items()
        },
        workspace_dirs={item.project: item.workspace_dir for item in resolved},
        proposals=proposals,
        epics=tuple(epics),
        phases_by_epic=phases_by_epic,
        ready_ids=frozenset(ready_ids),
        blocked_ids=frozenset(blocked_ids),
        archive=tuple(archive),
        linked_plan_documents=linked_plan_documents,
        source_key=source_key,
        errors=errors,
        archive_truncated=archive_truncated,
    )


def _add_project_error(
    errors: dict[str, str],
    project: str,
    message: str,
) -> None:
    previous = errors.get(project)
    errors[project] = message if previous is None else f"{previous}; {message}"


def _load_epic_linked_plan_documents(
    project: str,
    epic: Issue,
    phases: tuple[ProjectIssue, ...],
    *,
    workspace_dir: str | None,
    plans_root: Path,
) -> dict[tuple[str, str], LinkedPlanDocument]:
    """Resolve linked documents once per path for one epic phase tree."""
    documents: dict[tuple[str, str], LinkedPlanDocument] = {}
    read_cache: dict[Path, _LinkedPlanPayload] = {}
    if reference := epic.design.strip():
        documents[(project, epic.id)] = _load_linked_plan_document(
            reference,
            workspace_dir=workspace_dir,
            plans_root=plans_root,
            read_cache=read_cache,
        )
    for phase in phases:
        reference = phase.issue.design.strip()
        if not reference:
            continue
        documents[(project, phase.issue.id)] = _load_linked_plan_document(
            reference,
            workspace_dir=workspace_dir,
            plans_root=plans_root,
            read_cache=read_cache,
        )
    return documents


def _load_linked_plan_document(
    reference: str,
    *,
    workspace_dir: str | None,
    plans_root: Path,
    read_cache: dict[Path, _LinkedPlanPayload],
) -> LinkedPlanDocument:
    return _load_linked_plan_document_impl(
        reference,
        workspace_dir=workspace_dir,
        plans_root=plans_root,
        read_cache=read_cache,
        read_text=_read_linked_plan_text,
    )


def _read_linked_plan_payload(path: Path) -> _LinkedPlanPayload:
    return _documents._read_linked_plan_payload(
        path,
        read_text=_read_linked_plan_text,
    )


__all__ = [
    "DEEP_ARCHIVE_PER_PROJECT_LIMIT",
    "LinkedPlanDocument",
    "PlanProposal",
    "PlansSnapshot",
    "ProjectArchive",
    "ProjectIssue",
    "load_deep_plan_archive",
    "load_plans_snapshot",
]
