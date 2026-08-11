"""Off-thread data and mutation helpers for the Artifacts Bugs pane."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from sase.ace.patch.models import Patch
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bug_links import (
    BugLinks,
    ExternalRefLinks,
    find_bug_links,
    find_external_ref_links,
    normalize_external_ref,
)
from sase.vcs_provider import IssueListState, IssueState, IssueWire


class _IssueProvider(Protocol):
    """Issue-capable portion of the selected VCS provider."""

    def supports_issues(self) -> bool: ...

    def list_issues(
        self,
        cwd: str,
        state: IssueListState = "open",
        limit: int = 100,
    ) -> list[IssueWire]: ...

    def create_issue(
        self,
        title: str,
        body: str,
        labels: Sequence[str],
        cwd: str,
    ) -> IssueWire: ...

    def update_issue(
        self,
        number: int,
        cwd: str,
        *,
        title: str | None = None,
        body: str | None = None,
        state: IssueState | None = None,
        labels: Sequence[str] | None = None,
    ) -> IssueWire: ...

    def get_issue_url(self, number: int, cwd: str) -> str: ...


@dataclass(frozen=True)
class _BugScope:
    """Resolved tracker scope for one SASE project."""

    project_key: str
    display_name: str
    project_file: str
    cwd: str
    provider: _IssueProvider


@dataclass(frozen=True)
class BugSnapshot:
    """One immutable issue-list result ready for a UI-thread paint."""

    project_key: str | None
    display_name: str
    project_file: str
    cwd: str
    state_filter: IssueListState
    issues: tuple[IssueWire, ...] = ()
    links: tuple[tuple[int, BugLinks], ...] = ()
    supported: bool = True
    error: str = ""
    warning: str = ""

    def links_for(self, number: int) -> BugLinks:
        """Return precomputed local links for *number*."""
        return next(
            (links for issue_number, links in self.links if issue_number == number),
            BugLinks(str(number), (), ()),
        )


def _resolve_bug_scope(project: str) -> _BugScope:
    """Resolve a project picker value to its primary repo and VCS provider."""
    from sase.core.paths import sase_projects_dir
    from sase.core.project_lifecycle_facade import list_project_records
    from sase.core.project_lifecycle_wire import effective_project_name
    from sase.vcs_provider import get_vcs_provider

    records = list_project_records(
        sase_projects_dir(),
        "all",
        include_home=False,
        projects_only=True,
    )
    project_folded = project.casefold()
    record = next(
        (
            candidate
            for candidate in records
            if candidate.is_project
            and not candidate.system_managed
            and project_folded
            in {
                candidate.project_name.casefold(),
                effective_project_name(candidate).casefold(),
                *(alias.casefold() for alias in candidate.aliases),
            }
        ),
        None,
    )
    if record is None:
        raise ValueError(f"project {project!r} was not found")
    cwd = (record.workspace_dir or "").strip()
    if not cwd:
        raise ValueError(f"project {effective_project_name(record)!r} has no workspace")
    return _BugScope(
        project_key=record.project_name,
        display_name=effective_project_name(record),
        project_file=record.project_file,
        cwd=cwd,
        provider=cast(_IssueProvider, get_vcs_provider(cwd)),
    )


def collect_bug_snapshot(
    project: str | None,
    state_filter: IssueListState,
    patches: Iterable[Patch],
    *,
    limit: int = 100,
) -> BugSnapshot:
    """Collect remote issues and local links; callers must run this off-thread."""
    if project is None:
        return BugSnapshot(None, "", "", "", state_filter)

    try:
        scope = _resolve_bug_scope(project)
    except Exception as exc:
        return BugSnapshot(project, project, "", "", state_filter, error=str(exc))

    if not scope.provider.supports_issues():
        return BugSnapshot(
            scope.project_key,
            scope.display_name,
            scope.project_file,
            scope.cwd,
            state_filter,
            supported=False,
        )

    try:
        issues = tuple(
            scope.provider.list_issues(
                scope.cwd,
                state=state_filter,
                limit=limit,
            )
        )
    except Exception as exc:
        return BugSnapshot(
            scope.project_key,
            scope.display_name,
            scope.project_file,
            scope.cwd,
            state_filter,
            error=str(exc),
        )

    beads, warning = _load_project_beads(scope.project_key)
    patch_snapshot = tuple(patches)
    links = tuple(
        (
            issue.number,
            _links_for_issue(issue.number, beads, patch_snapshot, scope.project_key),
        )
        for issue in issues
    )
    return BugSnapshot(
        scope.project_key,
        scope.display_name,
        scope.project_file,
        scope.cwd,
        state_filter,
        issues=issues,
        links=links,
        warning=warning,
    )


def _links_for_issue(
    issue_number: int,
    beads: tuple[Issue, ...],
    patches: tuple[Patch, ...],
    project: str,
) -> BugLinks:
    legacy_links = find_bug_links(issue_number, beads, patches)
    external_ref = normalize_external_ref(issue_number, project=project)
    external_links = find_external_ref_links(
        external_ref,
        beads,
        patches,
        project=project,
    )
    return _merge_bug_links(legacy_links, external_links)


def _merge_bug_links(legacy: BugLinks, external: ExternalRefLinks) -> BugLinks:
    epics_by_id: dict[str, Issue] = {bead.id: bead for bead in legacy.epics}
    beads_by_id: dict[str, Issue] = {}
    for bead in external.beads:
        if bead.issue_type == IssueType.PLAN and bead.tier == BeadTier.EPIC:
            epics_by_id.setdefault(bead.id, bead)
        elif bead.id not in epics_by_id:
            beads_by_id.setdefault(bead.id, bead)

    patches_by_name: dict[str, Patch] = {patch.name: patch for patch in legacy.patches}
    for patch in external.patches:
        patches_by_name.setdefault(patch.name, patch)

    return BugLinks(
        legacy.bug_id or external.external_ref,
        tuple(epics_by_id.values()),
        tuple(patches_by_name.values()),
        tuple(beads_by_id.values()),
    )


def create_project_issue(
    project: str,
    *,
    title: str,
    body: str,
    labels: Sequence[str],
) -> IssueWire:
    """Create an issue in a resolved project tracker."""
    scope = _supported_scope(project)
    return scope.provider.create_issue(title, body, labels, scope.cwd)


def update_project_issue(
    project: str,
    number: int,
    *,
    title: str | None = None,
    body: str | None = None,
    state: IssueState | None = None,
    labels: Sequence[str] | None = None,
) -> IssueWire:
    """Update an issue in a resolved project tracker."""
    scope = _supported_scope(project)
    return scope.provider.update_issue(
        number,
        scope.cwd,
        title=title,
        body=body,
        state=state,
        labels=labels,
    )


def issue_url(project: str, issue: IssueWire) -> str:
    """Return a cached URL or ask the provider for its non-fetching URL."""
    if issue.url:
        return issue.url
    return issue_url_for_number(project, issue.number)


def issue_url_for_number(project: str, number: int) -> str:
    """Resolve an issue URL without fetching the issue from its tracker."""
    scope = _supported_scope(project)
    return scope.provider.get_issue_url(number, scope.cwd)


def _supported_scope(project: str) -> _BugScope:
    scope = _resolve_bug_scope(project)
    if not scope.provider.supports_issues():
        raise NotImplementedError(
            "Bugs needs a tracker-capable provider (GitHub) for this project"
        )
    return scope


def _load_project_beads(project: str) -> tuple[tuple[Issue, ...], str]:
    from sase.bead.workspace import get_project_beads_dirs_for_project
    from sase.core.bead_read_facade import list_issues

    try:
        beads_dirs = get_project_beads_dirs_for_project(project) or []
        beads = tuple(
            bead for beads_dir in beads_dirs for bead in list_issues(beads_dir)
        )
        return beads, ""
    except Exception as exc:
        # Tracker triage remains useful when a local plans sidecar is absent or
        # temporarily unreadable; surface the degraded link state separately.
        return (), f"Local bug links unavailable: {exc}"


__all__ = [
    "BugSnapshot",
    "collect_bug_snapshot",
    "create_project_issue",
    "issue_url",
    "issue_url_for_number",
    "update_project_issue",
]
