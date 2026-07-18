"""Off-thread data collection for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.bead.model import Issue
from sase.bead.project import BeadProject
from sase.notifications.models import Notification
from sase.plan_search.model import PlanSearchMatch


@dataclass(frozen=True)
class PlanProposal:
    """One pending plan approval with its existing notification context."""

    project: str
    notification: Notification
    title: str
    tier: str
    age: str
    timestamp: str
    plan_path: str
    content: str
    frontmatter: dict[str, str]
    body: str
    agent: str
    provider_model: str


@dataclass(frozen=True)
class ProjectIssue:
    """A bead issue together with the project that owns its store."""

    project: str
    issue: Issue


@dataclass(frozen=True)
class ProjectArchive:
    """An archived plan together with the project that owns its SDD root."""

    project: str
    match: PlanSearchMatch


@dataclass(frozen=True)
class _DeepArchiveFetch:
    """One bounded, cross-project archive browse completed off-thread."""

    archive: tuple[ProjectArchive, ...]
    scanned_count: int
    capped: bool
    errors: dict[str, str]


@dataclass(frozen=True)
class PlansSnapshot:
    """Immutable result applied to the Plans pane on the UI thread."""

    project: str | None
    projects: tuple[str, ...]
    display_names: dict[str, str]
    beads_dirs: dict[str, str | None]
    plans_roots: dict[str, str | None]
    workspace_dirs: dict[str, str | None]
    proposals: tuple[PlanProposal, ...]
    epics: tuple[ProjectIssue, ...]
    phases_by_epic: dict[tuple[str, str], tuple[ProjectIssue, ...]]
    ready_ids: frozenset[tuple[str, str]]
    blocked_ids: frozenset[tuple[str, str]]
    archive: tuple[ProjectArchive, ...]
    source_key: tuple[object, ...]
    errors: dict[str, str]
    archive_truncated: bool = False


@dataclass(frozen=True)
class _PlansProject:
    """Resolved metadata for one project included in a snapshot."""

    project: str
    display_name: str
    workspace_dir: str | None


_ARCHIVE_PER_PROJECT_LIMIT = 50
_ARCHIVE_MERGED_LIMIT = 100
DEEP_ARCHIVE_PER_PROJECT_LIMIT = 500


def load_plans_snapshot(
    project: str | None,
    *,
    previous: PlansSnapshot | None = None,
    force: bool = False,
) -> PlansSnapshot:
    """Collect one or all enabled projects through existing core facades.

    This function performs disk access and must run on a worker thread.  Its
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
    plans_by_project: dict[str, Path | None] = {}
    store_keys: list[tuple[str, object]] = []
    for item in resolved:
        beads_dir = _project_beads_dir(item.project)
        plans_root = None if beads_dir is None else beads_dir.parent
        beads_by_project[item.project] = beads_dir
        plans_by_project[item.project] = plans_root
        store_keys.append(
            (
                item.project,
                "missing"
                if beads_dir is None or plans_root is None
                else _store_mtime_key(beads_dir, plans_root),
            )
        )

    source_key = (
        project,
        tuple(
            (item.project, item.display_name, item.workspace_dir) for item in resolved
        ),
        _proposal_key(proposals),
        tuple(store_keys),
    )
    if not force and previous is not None and previous.source_key == source_key:
        return previous

    from sase.bead.model import BeadTier, IssueType

    epics: list[ProjectIssue] = []
    phases_by_epic: dict[tuple[str, str], tuple[ProjectIssue, ...]] = {}
    ready_ids: set[tuple[str, str]] = set()
    blocked_ids: set[tuple[str, str]] = set()
    archive: list[ProjectArchive] = []
    archive_truncated = False
    errors: dict[str, str] = {}

    for item in resolved:
        project_name = item.project
        beads_dir = beads_by_project[project_name]
        plans_root = plans_by_project[project_name]
        if beads_dir is None or plans_root is None:
            if project is not None:
                errors[project_name] = "No bead store is available for this project."
            continue

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
                if issue.issue_type == IssueType.PLAN and issue.tier == BeadTier.EPIC
            )
            epics.extend(ProjectIssue(project_name, issue) for issue in project_epics)
            for epic in project_epics:
                phases_by_epic[(project_name, epic.id)] = tuple(
                    ProjectIssue(project_name, issue)
                    for issue in sorted(
                        (issue for issue in issues if issue.parent_id == epic.id),
                        key=lambda issue: _hierarchical_id_key(issue.id),
                    )
                )
            ready_ids.update((project_name, issue_id) for issue_id in project_ready_ids)
            blocked_ids.update(
                (project_name, issue_id) for issue_id in project_blocked_ids
            )

        try:
            project_archive = _load_project_archive(plans_root)
            archive_truncated = (
                archive_truncated or len(project_archive) > _ARCHIVE_PER_PROJECT_LIMIT
            )
            archive.extend(
                ProjectArchive(project_name, match)
                for match in project_archive[:_ARCHIVE_PER_PROJECT_LIMIT]
            )
        except Exception as exc:
            _add_project_error(
                errors,
                project_name,
                f"Unable to read plan archive: {exc}",
            )

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

    return PlansSnapshot(
        project=project,
        projects=project_names,
        display_names={item.project: item.display_name for item in resolved},
        beads_dirs={
            name: None if path is None else str(path)
            for name, path in beads_by_project.items()
        },
        plans_roots={
            name: None if path is None else str(path)
            for name, path in plans_by_project.items()
        },
        workspace_dirs={item.project: item.workspace_dir for item in resolved},
        proposals=proposals,
        epics=tuple(epics),
        phases_by_epic=phases_by_epic,
        ready_ids=frozenset(ready_ids),
        blocked_ids=frozenset(blocked_ids),
        archive=tuple(archive),
        source_key=source_key,
        errors=errors,
        archive_truncated=archive_truncated,
    )


def _resolve_projects(project: str | None) -> tuple[_PlansProject, ...]:
    from sase.core.paths import sase_projects_dir
    from sase.core.project_lifecycle_facade import list_project_records
    from sase.core.project_lifecycle_wire import effective_project_name

    records = list_project_records(
        sase_projects_dir(),
        "all",
        include_home=False,
        projects_only=True,
    )
    candidates = tuple(
        record for record in records if record.is_project and not record.system_managed
    )
    if project is None:
        selected = tuple(record for record in candidates if record.state == "enabled")
    else:
        selected = tuple(
            record for record in candidates if record.project_name == project
        )
        if not selected:
            return (_PlansProject(project, project, None),)
    return tuple(
        _PlansProject(
            record.project_name,
            effective_project_name(record),
            record.workspace_dir,
        )
        for record in sorted(
            selected,
            key=lambda record: (
                effective_project_name(record).casefold(),
                record.project_name,
            ),
        )
    )


def _project_beads_dir(project: str) -> Path | None:
    from sase.bead.workspace import get_project_beads_dirs_for_project

    directories = get_project_beads_dirs_for_project(project)
    if not directories:
        return None
    return directories[0]


def _load_proposals(
    project: str | None,
    enabled_projects: frozenset[str],
) -> tuple[PlanProposal, ...]:
    from sase.main.plan_inventory import build_plan_inventory
    from sase.notifications.store import load_notifications

    inventory = build_plan_inventory(limit=50, statuses=("proposed",))
    notifications = {
        notification.id: notification
        for notification in load_notifications(include_dismissed=False)
    }
    proposals: list[PlanProposal] = []
    for row in inventory.proposed:
        if project is None and row.project not in enabled_projects:
            continue
        if project is not None and row.project != project:
            continue
        notification = notifications.get(row.notification_id)
        if notification is None:
            continue
        plan_path = row._plan_key
        content = _read_text(Path(plan_path))
        frontmatter, body = _parse_proposal_document(content)
        proposals.append(
            PlanProposal(
                project=row.project,
                notification=notification,
                title=frontmatter.get("title") or _plan_title(Path(plan_path), content),
                tier=row.tier,
                age=row.age,
                timestamp=row.timestamp,
                plan_path=plan_path,
                content=content,
                frontmatter=frontmatter,
                body=body,
                agent=row.agent,
                provider_model=row.provider_model,
            )
        )
    return tuple(proposals)


def _parse_proposal_document(content: str) -> tuple[dict[str, str], str]:
    """Project proposal YAML into the same flat strings as plan search."""
    from sase.sdd.frontmatter import parse_frontmatter

    frontmatter, body, _had_frontmatter = parse_frontmatter(content)
    return (
        {
            key: _yaml_value_to_string(value)
            for key, value in frontmatter.items()
            if isinstance(key, str)
        },
        body,
    )


def _yaml_value_to_string(value: object) -> str:
    """Mirror the Rust plan reader's display-oriented YAML flattening."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(_yaml_value_to_string(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(
            f"{_yaml_value_to_string(key)}: {_yaml_value_to_string(item)}"
            for key, item in value.items()
        )
    return str(value)


def _load_project_beads(
    beads_dir: Path,
) -> tuple[list[Issue], frozenset[str], frozenset[str]]:
    with BeadProject(beads_dir.parent, beads_dirname=beads_dir.name) as bead_project:
        issues = bead_project.list_issues()
        ready_ids = frozenset(issue.id for issue in bead_project.ready())
        blocked_ids = frozenset(issue.id for issue in bead_project.blocked())
    return issues, ready_ids, blocked_ids


def _load_project_archive(plans_root: Path) -> tuple[PlanSearchMatch, ...]:
    from sase.plan_search.facade import SOURCE_REPO, search

    return tuple(
        search(
            None,
            kinds=("tale", "epic"),
            source=SOURCE_REPO,
            sort="recent",
            limit=_ARCHIVE_PER_PROJECT_LIMIT + 1,
            repo_root=plans_root,
        )
    )


def load_deep_plan_archive(
    project_roots: tuple[tuple[str, str], ...],
    *,
    limit: int = DEEP_ARCHIVE_PER_PROJECT_LIMIT,
) -> _DeepArchiveFetch:
    """Browse a bounded archive corpus for each project.

    This performs filesystem access through the Rust-backed plan-search facade
    and therefore must only be called from a worker thread.  Query membership
    is deliberately left to the pane's Python matcher so preview and deep
    reconciliation cannot drift.
    """
    from sase.plan_search.facade import SOURCE_REPO, search

    archive: list[ProjectArchive] = []
    errors: dict[str, str] = {}
    capped = False
    for project, plans_root in project_roots:
        try:
            matches = tuple(
                search(
                    None,
                    kinds=("tale", "epic"),
                    source=SOURCE_REPO,
                    sort="recent",
                    limit=limit,
                    repo_root=plans_root,
                )
            )
        except Exception as exc:
            errors[project] = str(exc)
            continue
        capped = capped or len(matches) >= limit
        archive.extend(ProjectArchive(project, match) for match in matches)

    deduped: dict[str, ProjectArchive] = {}
    for project_archive in archive:
        deduped.setdefault(project_archive.match.plan.path, project_archive)
    ordered = tuple(sorted(deduped.values(), key=_archive_recency_key, reverse=True))
    return _DeepArchiveFetch(
        archive=ordered,
        scanned_count=len(ordered),
        capped=capped,
        errors=errors,
    )


def _archive_recency_key(item: ProjectArchive) -> tuple[str, str, str]:
    return (
        item.match.plan.created_at,
        item.match.plan.path,
        item.project,
    )


def _add_project_error(
    errors: dict[str, str],
    project: str,
    message: str,
) -> None:
    previous = errors.get(project)
    errors[project] = message if previous is None else f"{previous}; {message}"


def _plan_title(path: Path, content: str) -> str:
    in_frontmatter = False
    for line in content.splitlines()[:80]:
        if line.strip() == "---":
            if in_frontmatter:
                break
            in_frontmatter = True
            continue
        if in_frontmatter and line.startswith("title:"):
            title = line.split(":", 1)[1].strip().strip("'\"")
            if title:
                return title
    return path.stem.replace("_", " ").replace("-", " ").strip().title()


def _read_text(path: Path) -> str:
    try:
        return path.expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        return f"# Unable to read plan\n\n{exc}"


def _proposal_key(
    proposals: tuple[PlanProposal, ...],
) -> tuple[tuple[str, str, str, str], ...]:
    return tuple(
        (
            proposal.project,
            proposal.notification.id,
            proposal.timestamp,
            proposal.plan_path,
        )
        for proposal in proposals
    )


def _store_mtime_key(
    beads_dir: Path,
    plans_root: Path,
) -> tuple[tuple[str, int, int], ...]:
    paths: list[Path] = []
    for name in ("issues.jsonl", "config.json"):
        paths.append(beads_dir / name)
    events_dir = beads_dir / "events"
    if events_dir.is_dir():
        paths.extend(path for path in events_dir.rglob("*") if path.is_file())

    month_pattern = "[0-9][0-9][0-9][0-9][0-9][0-9]"
    plan_roots = (plans_root, plans_root / "plans")
    for root in plan_roots:
        if not root.is_dir():
            continue
        for month in root.glob(month_pattern):
            if month.is_dir():
                paths.extend(path for path in month.glob("*.md") if path.is_file())

    keyed: list[tuple[str, int, int]] = []
    for path in sorted(set(paths)):
        try:
            stat = path.stat()
        except OSError:
            continue
        keyed.append((str(path), stat.st_mtime_ns, stat.st_size))
    return tuple(keyed)


def _hierarchical_id_key(issue_id: str) -> tuple[object, ...]:
    parts: list[object] = []
    for part in issue_id.split("."):
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(parts)


def _timestamp_recency_key(timestamp: str) -> tuple[bool, float]:
    """Sort valid timestamps newest-first and missing/invalid values last."""
    value = timestamp.strip()
    if not value:
        return True, 0.0
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return True, 0.0
    if parsed.tzinfo is None:
        from sase.core.time import get_timezone

        parsed = parsed.replace(tzinfo=get_timezone())
    return False, -parsed.timestamp()


__all__ = [
    "DEEP_ARCHIVE_PER_PROJECT_LIMIT",
    "PlanProposal",
    "PlansSnapshot",
    "ProjectArchive",
    "ProjectIssue",
    "load_deep_plan_archive",
    "load_plans_snapshot",
]
