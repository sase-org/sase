"""Project, proposal, bead, and archive sources for Plans snapshots."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from sase.bead.model import Issue
from sase.bead.project import BeadProject
from sase.plan_search.model import PlanSearchMatch

from .plans_data_models import (
    DeepArchiveFetch,
    PlanProposal,
    PlansProject,
    ProjectArchive,
)

_ARCHIVE_PER_PROJECT_LIMIT = 50
_ARCHIVE_MERGED_LIMIT = 100
DEEP_ARCHIVE_PER_PROJECT_LIMIT = 500


def resolve_projects(project: str | None) -> tuple[PlansProject, ...]:
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
            return (PlansProject(project, project, None),)
    return tuple(
        PlansProject(
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


def project_beads_dir(project: str) -> Path | None:
    from sase.bead.workspace import get_project_beads_dirs_for_project

    directories = get_project_beads_dirs_for_project(project)
    if not directories:
        return None
    return directories[0]


def load_proposals(
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
        content = read_text(Path(plan_path))
        frontmatter, body = parse_proposal_document(content)
        proposals.append(
            PlanProposal(
                project=row.project,
                notification=notification,
                title=frontmatter.get("title") or plan_title(Path(plan_path), content),
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


def parse_proposal_document(content: str) -> tuple[dict[str, str], str]:
    """Project proposal YAML into the same flat strings as plan search."""
    from sase.sdd.frontmatter import parse_frontmatter

    frontmatter, body, _had_frontmatter = parse_frontmatter(content)
    return (
        {
            key: yaml_value_to_string(value)
            for key, value in frontmatter.items()
            if isinstance(key, str)
        },
        body,
    )


def yaml_value_to_string(value: object) -> str:
    """Mirror the Rust plan reader's display-oriented YAML flattening."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (int, float, str)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return ", ".join(yaml_value_to_string(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(
            f"{yaml_value_to_string(key)}: {yaml_value_to_string(item)}"
            for key, item in value.items()
        )
    return str(value)


def load_project_beads(
    beads_dir: Path,
) -> tuple[list[Issue], frozenset[str], frozenset[str]]:
    with BeadProject(beads_dir.parent, beads_dirname=beads_dir.name) as bead_project:
        issues = bead_project.list_issues()
        ready_ids = frozenset(issue.id for issue in bead_project.ready())
        blocked_ids = frozenset(issue.id for issue in bead_project.blocked())
    return issues, ready_ids, blocked_ids


def load_project_archive(plans_root: Path) -> tuple[PlanSearchMatch, ...]:
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
) -> DeepArchiveFetch:
    """Browse a bounded archive corpus for each project.

    This performs filesystem access through the Rust-backed plan-search facade
    and therefore must only be called from a worker thread. Query membership
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
    ordered = tuple(sorted(deduped.values(), key=archive_recency_key, reverse=True))
    return DeepArchiveFetch(
        archive=ordered,
        scanned_count=len(ordered),
        capped=capped,
        errors=errors,
    )


def archive_recency_key(item: ProjectArchive) -> tuple[str, str, str]:
    return (
        item.match.plan.created_at,
        item.match.plan.path,
        item.project,
    )


def plan_title(path: Path, content: str) -> str:
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


def read_text(path: Path) -> str:
    try:
        return path.expanduser().read_text(encoding="utf-8")
    except OSError as exc:
        return f"# Unable to read plan\n\n{exc}"


def proposal_key(
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


def store_mtime_key(
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


def hierarchical_id_key(issue_id: str) -> tuple[object, ...]:
    parts: list[object] = []
    for part in issue_id.split("."):
        parts.append((0, int(part)) if part.isdigit() else (1, part))
    return tuple(parts)


def timestamp_recency_key(timestamp: str) -> tuple[bool, float]:
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
