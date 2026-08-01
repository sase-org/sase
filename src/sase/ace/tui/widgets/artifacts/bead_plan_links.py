"""Shared bead-to-plan projection for the Artifacts Beads and Plans panes."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from sase.bead.model import BeadTier, Issue, IssueType, Status
from sase.plan_documents import PlanWorkspace, resolve_plan_path


@dataclass(frozen=True)
class BeadPlanLink:
    """Presentation-neutral metadata for one bead's resolved plan link."""

    project: str
    bead_id: str
    bead_type: IssueType
    bead_status: Status
    bead_tier: BeadTier | None
    bead_title: str
    bead_created_at: str
    reference: str
    path: str

    @property
    def live(self) -> bool:
        """Return whether this link can place its document in Active plans."""
        return self.bead_status is not Status.CLOSED


def build_bead_plan_links(
    project: str,
    issues: Iterable[Issue],
    *,
    workspace_dir: str | None,
    plans_root: Path,
) -> dict[tuple[str, str], BeadPlanLink]:
    """Resolve every bead design reference once on a worker thread."""
    links: dict[tuple[str, str], BeadPlanLink] = {}
    workspace = PlanWorkspace(
        workspace_dir=workspace_dir or "",
        plans_root=str(plans_root),
    )
    for issue in issues:
        reference = issue.design.strip()
        if not reference:
            continue
        resolved = resolve_plan_path(reference, workspaces=(workspace,))
        if resolved.status == "invalid_reference" or resolved.path is None:
            continue
        links[(project, issue.id)] = BeadPlanLink(
            project=project,
            bead_id=issue.id,
            bead_type=issue.issue_type,
            bead_status=issue.status,
            bead_tier=issue.tier,
            bead_title=issue.title,
            bead_created_at=issue.created_at,
            reference=reference,
            path=str(Path(resolved.path)),
        )
    return links


def plan_owner(
    links: dict[tuple[str, str], BeadPlanLink],
    *,
    project: str,
    path: str,
    live_only: bool = False,
) -> BeadPlanLink | None:
    """Return the deterministic owning bead for one resolved plan path."""
    candidates = (
        link
        for link in links.values()
        if link.project == project
        and link.path == path
        and (not live_only or link.live)
    )
    return min(candidates, key=_owner_key, default=None)


def _owner_key(link: BeadPlanLink) -> tuple[int, tuple[tuple[int, object], ...]]:
    kind_order = {
        IssueType.PLAN: 0,
        IssueType.TASK: 1,
        IssueType.PHASE: 2,
    }
    return kind_order.get(link.bead_type, 3), _bead_plan_link_id_key(link.bead_id)


def _bead_plan_link_id_key(value: str) -> tuple[tuple[int, object], ...]:
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in value.split(".")
    )


__all__ = ["BeadPlanLink", "build_bead_plan_links", "plan_owner"]
