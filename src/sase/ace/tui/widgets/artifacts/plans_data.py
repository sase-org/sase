"""Off-thread data collection for the document-only Artifacts Plans pane."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.ace.tui._artifact_tab_model import PanePresentation, PaneSortField
from sase.bead.model import Issue

from . import plans_data_documents as _documents
from .bead_plan_links import BeadPlanLink, build_bead_plan_links, plan_owner
from .plans_data_documents import (
    LinkedPlanPayload as _LinkedPlanPayload,
    current_linked_plan_key as _current_linked_plan_key,
    load_linked_plan_document as _load_linked_plan_document_impl,
    loaded_linked_plan_key as _loaded_linked_plan_key,
    read_linked_plan_text as _read_linked_plan_text,
)
from .plans_data_models import (
    ActivePlanDocument,
    DeepArchiveFetch as _DeepArchiveFetch,
    LinkedPlanDocument,
    PlanProposal,
    PlansProject as _PlansProject,
    PlansSnapshot,
    ProjectArchive,
)
from .plans_data_sources import (
    DEEP_ARCHIVE_PER_PROJECT_LIMIT,
    _ARCHIVE_MERGED_LIMIT,
    _ARCHIVE_PER_PROJECT_LIMIT,
    archive_recency_key as _archive_recency_key,
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
from .provider_documents import provider_document_field_value

# Preserve loader seams patched by focused tests and external integrations.
_linked_plan_signature = _documents._linked_plan_signature
_resolve_linked_plan_path = _documents._resolve_linked_plan_path
_unavailable_linked_plan_payload = _documents._unavailable_linked_plan_payload


def load_plans_snapshot(
    project: str | None,
    *,
    provider_kind: str = "plan",
    provider_label: str | None = None,
    provider_presentation: PanePresentation | None = None,
    provider_presentation_digest: str = "",
    previous: PlansSnapshot | None = None,
    force: bool = False,
) -> PlansSnapshot:
    """Collect proposals, active linked documents, and committed archive rows.

    This function performs disk access and must run on a worker thread. Beads
    contribute only their plan-link projection; no bead becomes a Plans row.
    """
    resolved = _resolve_projects(project)
    presentation = provider_presentation or PanePresentation()
    project_names = tuple(item.project for item in resolved)
    enabled_projects = frozenset(project_names)
    proposals = (
        tuple(
            sorted(
                _load_proposals(project, enabled_projects),
                key=lambda proposal: (
                    _timestamp_recency_key(proposal.timestamp),
                    proposal.notification.id,
                    proposal.project,
                ),
            )
        )
        if provider_kind == "plan"
        else ()
    )
    beads_by_project: dict[str, Path | None] = {}
    plans_by_project: dict[str, dict[str, Path]] = {}
    store_keys: list[tuple[str, object]] = []
    for item in resolved:
        beads_dir = _project_beads_dir(item.project)
        plans_roots = _project_document_roots(item, provider_kind=provider_kind)
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
        provider_kind,
        provider_presentation_digest,
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

    active_by_path: dict[str, ActivePlanDocument] = {}
    archive_candidates: list[ProjectArchive] = []
    bead_plan_links: dict[tuple[str, str], BeadPlanLink] = {}
    linked_plan_documents: dict[tuple[str, str], LinkedPlanDocument] = {}
    archive_truncated = False
    errors: dict[str, str] = {}

    for item in resolved:
        project_name = item.project
        beads_dir = beads_by_project[project_name]
        plans_roots = plans_by_project[project_name]
        plans_root = plans_roots.get("plans") if provider_kind == "plan" else None
        issues: tuple[Issue, ...] = ()
        if provider_kind != "plan":
            issues = ()
        elif beads_dir is None:
            if project is not None:
                errors[project_name] = "No bead store is available for this project."
        else:
            try:
                issues = tuple(_load_project_beads(beads_dir))
            except Exception as exc:
                _add_project_error(errors, project_name, f"Unable to read beads: {exc}")

        if plans_root is not None and issues:
            project_links = build_bead_plan_links(
                project_name,
                issues,
                workspace_dir=item.workspace_dir,
                plans_root=plans_root,
            )
            bead_plan_links.update(project_links)
            read_cache: dict[Path, _LinkedPlanPayload] = {}
            for key, link in project_links.items():
                if not link.live:
                    continue
                document = _load_linked_plan_document(
                    link.reference,
                    workspace_dir=item.workspace_dir,
                    plans_root=plans_root,
                    read_cache=read_cache,
                )
                linked_plan_documents[key] = document
            for link in project_links.values():
                active_document = linked_plan_documents.get(
                    (project_name, link.bead_id)
                )
                if (
                    active_document is None
                    or not active_document.available
                    or not active_document.path
                ):
                    continue
                owner = plan_owner(
                    project_links,
                    project=project_name,
                    path=active_document.path,
                    live_only=True,
                )
                if owner is not None:
                    active_by_path.setdefault(
                        active_document.path,
                        ActivePlanDocument(project_name, active_document, owner),
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
        archive_candidates.extend(ordered_project_archive[:_ARCHIVE_PER_PROJECT_LIMIT])

    active = sorted(
        active_by_path.values(),
        key=lambda entry: (
            _timestamp_recency_key(_active_timestamp(entry)),
            entry.document.path,
            entry.project,
        ),
    )
    archive = [
        entry
        for entry in archive_candidates
        if entry.match.plan.path not in active_by_path
    ]
    if provider_kind == "plan" or not presentation.default_sort:
        archive.sort(key=_archive_recency_key, reverse=True)
    else:
        archive.sort(key=lambda entry: _provider_archive_sort_key(entry, presentation))
    merged_archive_truncated = len(archive) > _ARCHIVE_MERGED_LIMIT
    archive_truncated = archive_truncated or merged_archive_truncated
    if merged_archive_truncated:
        del archive[_ARCHIVE_MERGED_LIMIT:]

    source_key = (*base_source_key, _loaded_linked_plan_key(linked_plan_documents))
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
        active=tuple(active),
        archive=tuple(archive),
        bead_plan_links=bead_plan_links,
        linked_plan_documents=linked_plan_documents,
        source_key=source_key,
        errors=errors,
        archive_truncated=archive_truncated,
        provider_kind=provider_kind,
        provider_label=provider_label or _provider_label(provider_kind),
        provider_presentation_digest=provider_presentation_digest,
        provider_presentation=presentation,
    )


def _provider_archive_sort_key(
    entry: ProjectArchive,
    presentation: PanePresentation,
) -> tuple[object, ...]:
    parts: list[object] = []
    for item in presentation.default_sort:
        value = provider_document_field_value(entry, item.field).strip()
        parts.append((not value, _sort_value(value, item)))
    plan = entry.match.plan
    parts.append((plan.path, entry.project, plan.relpath))
    return tuple(parts)


def _sort_value(value: str, sort: PaneSortField) -> object:
    parsed = _parse_sort_timestamp(value)
    desc = sort.direction == "desc"
    if parsed is not None:
        timestamp = parsed.timestamp()
        return (0, -timestamp if desc else timestamp)
    folded = value.casefold()
    if desc:
        return (1, tuple(-ord(char) for char in folded))
    return (1, folded)


def _parse_sort_timestamp(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        from sase.core.time import get_timezone

        parsed = parsed.replace(tzinfo=get_timezone())
    return parsed


def _active_timestamp(entry: ActivePlanDocument) -> str:
    return (
        entry.document.frontmatter.get("create_time", "")
        or entry.document.frontmatter.get("created_at", "")
        or entry.owner.bead_created_at
    )


def _provider_label(provider_kind: str) -> str:
    label = provider_kind.replace("_", " ").replace("-", " ").strip().title()
    if not label:
        return "Document"
    return label


def _add_project_error(errors: dict[str, str], project: str, message: str) -> None:
    previous = errors.get(project)
    errors[project] = message if previous is None else f"{previous}; {message}"


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
    return _documents._read_linked_plan_payload(path, read_text=_read_linked_plan_text)


__all__ = [
    "ActivePlanDocument",
    "BeadPlanLink",
    "DEEP_ARCHIVE_PER_PROJECT_LIMIT",
    "LinkedPlanDocument",
    "PlanProposal",
    "PlansSnapshot",
    "ProjectArchive",
    "load_deep_plan_archive",
    "load_plans_snapshot",
]
