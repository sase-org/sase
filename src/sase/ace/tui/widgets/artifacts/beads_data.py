"""Off-thread data collection for the Artifacts Beads pane."""

from __future__ import annotations

import time
from collections.abc import Iterable
from pathlib import Path

from sase.ace.patch.models import Patch
from sase.ace.tui.artifacts_bugs import (
    issue_tracker_capabilities,
    list_project_issues,
    resolve_issue_tracker_scope,
)
from sase.bead.model import IssueType
from sase.bug_links import find_external_ref_links, normalize_external_ref
from sase.vcs_provider import IssueWire

from .beads_data_models import (
    BeadsSnapshot,
    ExternalIssueCapabilities,
    ExternalIssueLink,
    ExternalIssueProjectCache,
    ExternalIssueRelation,
    PendingTriage,
    ProjectBead,
)
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
from .plans_data_models import PlansProject

_EXTERNAL_ISSUE_CACHE_TTL_SECONDS = 60.0
_EXTERNAL_ISSUE_LIST_LIMIT = 100


def load_beads_snapshot(
    project: str | None,
    *,
    previous: BeadsSnapshot | None = None,
    force: bool = False,
    patches: Iterable[Patch] = (),
) -> BeadsSnapshot:
    """Load one or all projects; callers must run this on a worker thread."""
    resolved = _resolve_projects(project)
    now = time.monotonic()
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

    local_source_key: tuple[object, ...] = (
        project,
        tuple(
            (item.project, item.display_name, item.workspace_dir) for item in resolved
        ),
        tuple(store_keys),
        _notifications_mtime_key(),
    )
    if (
        not force
        and previous is not None
        and _snapshot_local_source_key(previous) == local_source_key
        and _external_caches_fresh(previous, project_names, now)
    ):
        return previous

    tasks: list[ProjectBead] = []
    epics: list[ProjectBead] = []
    phases_by_epic: dict[tuple[str, str], tuple[ProjectBead, ...]] = {}
    local_beads: list[ProjectBead] = []
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

        local_beads.extend(ProjectBead(project_name, issue) for issue in issues)
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
    patch_snapshot = tuple(patches)
    external_projects = _load_external_issue_caches(
        resolved,
        previous=previous,
        force=force,
        now=now,
    )
    external_links = _build_external_issue_links(
        local_beads,
        patches=patch_snapshot,
        external_projects=external_projects,
        display_names={item.project: item.display_name for item in resolved},
    )
    external_unmirrored_counts = _external_unmirrored_counts(
        external_projects,
        external_links,
    )
    external_source_key = _external_source_key(
        project_names,
        external_projects,
        external_links,
        external_unmirrored_counts,
    )
    source_key = (local_source_key, external_source_key)
    if not force and previous is not None and previous.source_key == source_key:
        return previous

    def task_order(item: ProjectBead) -> tuple[object, ...]:
        issue = item.issue
        status_order = {
            "ready": 1,
            "in_progress": 2,
            "claimed": 3,
            "open": 4,
            "snoozed": 5,
            "closed": 6,
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
        external_projects=external_projects,
        external_links=external_links,
        external_unmirrored_counts=external_unmirrored_counts,
        external_source_key=external_source_key,
    )


def _snapshot_local_source_key(snapshot: BeadsSnapshot) -> tuple[object, ...]:
    """Return the local-store portion of a snapshot source key."""

    if len(snapshot.source_key) == 2 and isinstance(snapshot.source_key[0], tuple):
        return snapshot.source_key[0]
    return snapshot.source_key


def _external_caches_fresh(
    snapshot: BeadsSnapshot,
    projects: tuple[str, ...],
    now: float,
) -> bool:
    """Return whether all projects have usable, non-expired issue cache entries."""

    if not snapshot.external_projects:
        return False
    for project in projects:
        cache = snapshot.external_projects.get(project)
        if cache is None:
            return False
        if now - cache.refreshed_at >= _EXTERNAL_ISSUE_CACHE_TTL_SECONDS:
            return False
    return True


def _load_external_issue_caches(
    resolved: tuple[PlansProject, ...],
    *,
    previous: BeadsSnapshot | None,
    force: bool,
    now: float,
) -> dict[str, ExternalIssueProjectCache]:
    caches: dict[str, ExternalIssueProjectCache] = {}
    previous_caches = {} if previous is None else previous.external_projects
    for item in resolved:
        project = item.project
        display_name = item.display_name
        prior = previous_caches.get(project)
        if (
            not force
            and prior is not None
            and now - prior.refreshed_at < _EXTERNAL_ISSUE_CACHE_TTL_SECONDS
        ):
            caches[project] = prior
            continue
        caches[project] = _load_external_issue_cache(
            project,
            display_name,
            now=now,
        )
    return caches


def _load_external_issue_cache(
    project: str,
    display_name: str,
    *,
    now: float,
) -> ExternalIssueProjectCache:
    try:
        scope = resolve_issue_tracker_scope(project)
    except Exception as exc:
        return ExternalIssueProjectCache(
            project=project,
            display_name=display_name,
            refreshed_at=now,
            error=str(exc),
        )

    raw_capabilities = issue_tracker_capabilities(scope.provider)
    capabilities = ExternalIssueCapabilities(
        listing=raw_capabilities.listing,
        reads=raw_capabilities.reads,
        mutations=raw_capabilities.mutations,
        urls=raw_capabilities.urls,
    )
    if not capabilities.listing:
        return ExternalIssueProjectCache(
            project=scope.project_key,
            display_name=scope.display_name,
            project_file=scope.project_file,
            cwd=scope.cwd,
            capabilities=capabilities,
            refreshed_at=now,
        )
    try:
        listed = list_project_issues(
            scope,
            state="all",
            limit=_EXTERNAL_ISSUE_LIST_LIMIT + 1,
        )
    except Exception as exc:
        return ExternalIssueProjectCache(
            project=scope.project_key,
            display_name=scope.display_name,
            project_file=scope.project_file,
            cwd=scope.cwd,
            capabilities=capabilities,
            refreshed_at=now,
            error=str(exc),
        )
    truncated = len(listed) > _EXTERNAL_ISSUE_LIST_LIMIT
    return ExternalIssueProjectCache(
        project=scope.project_key,
        display_name=scope.display_name,
        project_file=scope.project_file,
        cwd=scope.cwd,
        capabilities=capabilities,
        issues=tuple(listed[:_EXTERNAL_ISSUE_LIST_LIMIT]),
        refreshed_at=now,
        complete=not truncated,
        truncated=truncated,
    )


def _build_external_issue_links(
    beads: list[ProjectBead],
    *,
    patches: tuple[Patch, ...],
    external_projects: dict[str, ExternalIssueProjectCache],
    display_names: dict[str, str],
) -> dict[tuple[str, str], tuple[ExternalIssueLink, ...]]:
    all_issues = tuple(item.issue for item in beads)
    links: dict[tuple[str, str], tuple[ExternalIssueLink, ...]] = {}
    for item in beads:
        issue_links: list[ExternalIssueLink] = []
        for external_ref, relation in _local_external_refs(item):
            ref_project, issue_id = _external_ref_parts(external_ref)
            cache = external_projects.get(ref_project)
            cached_issue = _cached_issue(cache, issue_id)
            reverse_links = find_external_ref_links(
                external_ref,
                all_issues,
                patches,
                project=item.project,
            )
            issue_links.append(
                ExternalIssueLink(
                    external_ref=external_ref,
                    project=ref_project,
                    display_project=display_names.get(ref_project, ref_project),
                    issue_id=issue_id,
                    relation=relation,
                    issue=cached_issue,
                    stale=cache is not None and cache.complete and cached_issue is None,
                    drift=_issue_drifted(item.issue, cached_issue, relation=relation),
                    reverse_beads=reverse_links.beads,
                    reverse_patches=reverse_links.patches,
                )
            )
        if issue_links:
            links[(item.project, item.issue.id)] = tuple(issue_links)
    return links


def _local_external_refs(
    item: ProjectBead,
) -> tuple[tuple[str, ExternalIssueRelation], ...]:
    issue = item.issue
    values: list[tuple[str, ExternalIssueRelation]] = []
    mirrored = normalize_external_ref(issue.external_ref, project=item.project)
    if mirrored:
        values.append((mirrored, "mirrored"))
    seen = {mirrored} if mirrored else set[str]()
    for reference in issue.refs:
        if not reference.strip().casefold().startswith("bug:"):
            continue
        normalized = normalize_external_ref(reference, project=item.project)
        if not normalized or normalized in seen:
            continue
        values.append((normalized, "referenced"))
        seen.add(normalized)
    return tuple(values)


def _external_ref_parts(external_ref: str) -> tuple[str, str]:
    raw = external_ref.removeprefix("bug:")
    if "#" not in raw:
        return "", ""
    project, issue_id = raw.rsplit("#", 1)
    return project, issue_id


def _cached_issue(
    cache: ExternalIssueProjectCache | None,
    issue_id: str,
) -> IssueWire | None:
    if cache is None or not issue_id.isdigit():
        return None
    return cache.issue_for_number(int(issue_id))


def _issue_drifted(
    local_issue: object,
    cached_issue: IssueWire | None,
    *,
    relation: ExternalIssueRelation,
) -> bool:
    if relation != "mirrored" or cached_issue is None:
        return False
    local_title = getattr(local_issue, "title", "").strip().casefold()
    remote_title = cached_issue.title.strip().casefold()
    if local_title and remote_title and local_title != remote_title:
        return True
    local_status = getattr(getattr(local_issue, "status", None), "value", "")
    remote_closed = cached_issue.state == "closed"
    return bool(local_status) and (local_status == "closed") != remote_closed


def _external_unmirrored_counts(
    external_projects: dict[str, ExternalIssueProjectCache],
    external_links: dict[tuple[str, str], tuple[ExternalIssueLink, ...]],
) -> dict[str, int]:
    mirrored_refs = {
        link.external_ref
        for links in external_links.values()
        for link in links
        if link.relation == "mirrored"
    }
    counts: dict[str, int] = {}
    for project, cache in external_projects.items():
        if not cache.issues:
            continue
        counts[project] = sum(
            normalize_external_ref(issue.number, project=project) not in mirrored_refs
            for issue in cache.issues
        )
    return counts


def _external_source_key(
    projects: tuple[str, ...],
    external_projects: dict[str, ExternalIssueProjectCache],
    external_links: dict[tuple[str, str], tuple[ExternalIssueLink, ...]],
    external_unmirrored_counts: dict[str, int],
) -> tuple[object, ...]:
    project_key = tuple(
        _external_cache_source_key(external_projects.get(project))
        for project in projects
    )
    link_key = tuple(
        (
            owner,
            bead_id,
            tuple(
                (
                    link.external_ref,
                    link.relation,
                    link.state,
                    link.drift,
                    tuple(bead.id for bead in link.reverse_beads),
                    tuple(patch.name for patch in link.reverse_patches),
                )
                for link in links
            ),
        )
        for (owner, bead_id), links in sorted(external_links.items())
    )
    return (project_key, link_key, tuple(sorted(external_unmirrored_counts.items())))


def _external_cache_source_key(
    cache: ExternalIssueProjectCache | None,
) -> tuple[object, ...]:
    if cache is None:
        return ()
    return (
        cache.project,
        cache.display_name,
        cache.project_file,
        cache.cwd,
        (
            cache.capabilities.listing,
            cache.capabilities.reads,
            cache.capabilities.mutations,
            cache.capabilities.urls,
        ),
        cache.complete,
        cache.truncated,
        cache.error,
        tuple(
            (
                issue.number,
                issue.state,
                issue.title,
                issue.body,
                issue.labels,
                issue.assignees,
                issue.author,
                issue.updated_at,
                issue.url,
                issue.comment_count,
            )
            for issue in cache.issues
        ),
    )


__all__ = ["BeadsSnapshot", "PendingTriage", "ProjectBead", "load_beads_snapshot"]
