"""Off-thread data collection for the Artifacts Plans pane."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sase.bead.model import Issue
from sase.bead.project import BeadProject
from sase.notifications.models import Notification
from sase.plan_search.model import PlanSearchMatch


@dataclass(frozen=True)
class PlanProposal:
    """One pending plan approval with its existing notification context."""

    notification: Notification
    title: str
    tier: str
    age: str
    timestamp: str
    plan_path: str
    content: str
    agent: str
    provider_model: str


@dataclass(frozen=True)
class PlansSnapshot:
    """Immutable result applied to the Plans pane on the UI thread."""

    project: str
    beads_dir: str | None
    plans_root: str | None
    workspace_dir: str | None
    proposals: tuple[PlanProposal, ...]
    epics: tuple[Issue, ...]
    phases_by_epic: dict[str, tuple[Issue, ...]]
    ready_ids: frozenset[str]
    blocked_ids: frozenset[str]
    archive: tuple[PlanSearchMatch, ...]
    source_key: tuple[object, ...]
    error: str | None = None


def load_plans_snapshot(
    project: str,
    *,
    previous: PlansSnapshot | None = None,
    force: bool = False,
) -> PlansSnapshot:
    """Collect one project's plan pipeline through existing core facades.

    This function performs disk access and must run on a worker thread.  Its
    source key covers bead events, committed plan files, and pending proposal
    identities so normal re-activation can reuse the mounted pane's cache.
    """
    proposals = _load_proposals(project)
    beads_dir = _project_beads_dir(project)
    if beads_dir is None:
        return PlansSnapshot(
            project=project,
            beads_dir=None,
            plans_root=None,
            workspace_dir=_project_workspace_dir(project),
            proposals=proposals,
            epics=(),
            phases_by_epic={},
            ready_ids=frozenset(),
            blocked_ids=frozenset(),
            archive=(),
            source_key=("missing", project, _proposal_key(proposals)),
            error="No bead store is available for this project.",
        )

    plans_root = beads_dir.parent
    source_key = (
        project,
        _proposal_key(proposals),
        _store_mtime_key(beads_dir, plans_root),
    )
    if not force and previous is not None and previous.source_key == source_key:
        return previous

    try:
        with BeadProject(
            beads_dir.parent, beads_dirname=beads_dir.name
        ) as bead_project:
            issues = bead_project.list_issues()
            ready_ids = frozenset(issue.id for issue in bead_project.ready())
            blocked_ids = frozenset(issue.id for issue in bead_project.blocked())
    except Exception as exc:
        return PlansSnapshot(
            project=project,
            beads_dir=str(beads_dir),
            plans_root=str(plans_root),
            workspace_dir=_project_workspace_dir(project),
            proposals=proposals,
            epics=(),
            phases_by_epic={},
            ready_ids=frozenset(),
            blocked_ids=frozenset(),
            archive=(),
            source_key=source_key,
            error=f"Unable to read beads: {exc}",
        )

    from sase.bead.model import BeadTier, IssueType, Status

    epics = tuple(
        sorted(
            (
                issue
                for issue in issues
                if issue.issue_type == IssueType.PLAN and issue.tier == BeadTier.EPIC
            ),
            key=lambda issue: (
                {
                    Status.IN_PROGRESS: 0,
                    Status.OPEN: 1,
                    Status.CLOSED: 2,
                }[issue.status],
                issue.id,
            ),
        )
    )
    epic_ids = {issue.id for issue in epics}
    phases_by_epic: dict[str, tuple[Issue, ...]] = {}
    for epic_id in epic_ids:
        phases_by_epic[epic_id] = tuple(
            sorted(
                (issue for issue in issues if issue.parent_id == epic_id),
                key=lambda issue: _hierarchical_id_key(issue.id),
            )
        )

    archive: tuple[PlanSearchMatch, ...]
    try:
        from sase.plan_search.facade import SOURCE_REPO, search

        archive = tuple(
            search(
                None,
                kinds=("tale", "epic"),
                source=SOURCE_REPO,
                sort="recent",
                limit=50,
                repo_root=plans_root,
            )
        )
    except Exception:
        # Beads remain useful even if one malformed archived plan prevents the
        # search facade from producing an archive result.
        archive = ()

    return PlansSnapshot(
        project=project,
        beads_dir=str(beads_dir),
        plans_root=str(plans_root),
        workspace_dir=_project_workspace_dir(project),
        proposals=proposals,
        epics=epics,
        phases_by_epic=phases_by_epic,
        ready_ids=ready_ids,
        blocked_ids=blocked_ids,
        archive=archive,
        source_key=source_key,
    )


def _project_beads_dir(project: str) -> Path | None:
    from sase.bead.workspace import get_project_beads_dirs_for_project

    directories = get_project_beads_dirs_for_project(project)
    if not directories:
        return None
    return directories[0]


def _project_workspace_dir(project: str) -> str | None:
    from sase.core.paths import sase_projects_dir
    from sase.core.project_lifecycle_facade import list_project_records

    records = list_project_records(
        sase_projects_dir(),
        "all",
        include_home=False,
        projects_only=True,
    )
    for record in records:
        if record.project_name == project:
            return record.workspace_dir
    return None


def _load_proposals(project: str) -> tuple[PlanProposal, ...]:
    from sase.main.plan_inventory import build_plan_inventory
    from sase.notifications.store import load_notifications

    inventory = build_plan_inventory(limit=50, statuses=("proposed",))
    notifications = {
        notification.id: notification
        for notification in load_notifications(include_dismissed=False)
    }
    proposals: list[PlanProposal] = []
    for row in inventory.proposed:
        if row.project != project:
            continue
        notification = notifications.get(row.notification_id)
        if notification is None:
            continue
        plan_path = row._plan_key
        content = _read_text(Path(plan_path))
        proposals.append(
            PlanProposal(
                notification=notification,
                title=_plan_title(Path(plan_path), content),
                tier=row.tier,
                age=row.age,
                timestamp=row.timestamp,
                plan_path=plan_path,
                content=content,
                agent=row.agent,
                provider_model=row.provider_model,
            )
        )
    return tuple(proposals)


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


def _proposal_key(proposals: tuple[PlanProposal, ...]) -> tuple[tuple[str, str], ...]:
    return tuple(
        (proposal.notification.id, proposal.timestamp) for proposal in proposals
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


__all__ = ["PlanProposal", "PlansSnapshot", "load_plans_snapshot"]
