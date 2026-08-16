"""Validation and bookkeeping helpers for plan-file bead work."""

from __future__ import annotations

import shlex
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.cli_work_from_plan_types import PlanFileWorkError
from sase.bead.model import BeadTier, Issue, IssueType
from sase.bead.project import BeadProject
from sase.sdd.plan_waves import plan_phase_waves

if TYPE_CHECKING:
    from sase.bead.work import EpicWorkPlan


def is_plan_file_target(target: str) -> bool:
    """Return whether *target* selects plan-file rather than bead-ID mode."""
    path = Path(target).expanduser()
    return target.endswith(".md") or "/" in target or "\\" in target or path.is_file()


def linked_bead_id_if_present(plan_path: Path) -> str | None:
    if not plan_path.is_file():
        return None
    from sase.sdd.frontmatter import parse_frontmatter

    frontmatter, _body, _had_frontmatter = parse_frontmatter(
        plan_path.read_text(encoding="utf-8")
    )
    raw = frontmatter.get("bead_id")
    if raw in (None, ""):
        return None
    return str(raw)


def neutral_gate_destination_name(source_path: Path) -> str | None:
    """Return the durable proposal name for a neutral gate plan resource."""
    from sase.plan_gate import original_plan_file_for_resource

    original = original_plan_file_for_resource(source_path)
    return original.name if original is not None else None


def same_path(left: Path, right: Path) -> bool:
    return left.resolve(strict=False) == right.resolve(strict=False)


def require_matching_plan_identity(
    source_path: Path,
    *,
    source_title: str,
    archived_path: Path,
    no_push: bool,
) -> None:
    """Reject a preserved archive entry belonging to a different plan."""
    from sase.sdd.plan_tiers import normalize_plan_tier, parse_plan_frontmatter

    try:
        content = archived_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise error_with_resume(
            f"could not read existing archived plan {archived_path}: {exc}",
            archived_path,
            no_push=no_push,
        ) from exc
    frontmatter, error = parse_plan_frontmatter(content)
    archived_tier = (
        normalize_plan_tier(frontmatter.get("tier")) if error is None else None
    )
    raw_title = frontmatter.get("title") if error is None else None
    archived_title = raw_title.strip() if isinstance(raw_title, str) else None
    if archived_tier == "epic" and archived_title == source_title.strip():
        return

    raise error_with_resume(
        (
            f"epic plan archive collision: source {source_path} "
            f"(tier epic, title {source_title!r}) maps to existing {archived_path} "
            f"(tier {archived_tier or 'unknown'}, title {archived_title!r}); "
            "the existing archive belongs to a different plan"
        ),
        archived_path,
        no_push=no_push,
    )


def resolve_linked_epic(
    location: Any,
    epic_id: str,
    plan_path: Path,
) -> Issue | None:
    """Resolve a managed plan link without treating a missing bead as fatal."""
    if not location.beads_dir.is_dir():
        raise PlanFileWorkError(
            f"plan {plan_path} links bead_id {epic_id}, but the bead store is "
            "missing; restore the bead store before launching this plan"
        )
    try:
        with BeadProject(
            location.root,
            beads_dirname=location.beads_dirname,
        ) as project:
            issue = project.show(epic_id)
    except FileNotFoundError as exc:
        raise PlanFileWorkError(
            f"plan {plan_path} links bead_id {epic_id}, but the bead store is "
            "missing; restore the bead store before launching this plan"
        ) from exc
    except KeyError:
        return None
    if issue.issue_type is not IssueType.PLAN or issue.tier is not BeadTier.EPIC:
        raise PlanFileWorkError(
            f"plan {plan_path} links bead_id {epic_id}, but that bead is not an "
            "epic plan bead; remove the stale bead_id or restore the correct bead"
        )
    return issue


def require_parent_override_matches_linked(
    issue: Issue,
    parent_id: str | None,
    *,
    parent_override: str | None,
    plan_path: Path,
) -> None:
    """Reject a create-time parent override when a linked epic already exists."""
    if parent_override is None or issue.parent_id == parent_id:
        return
    actual = issue.parent_id or "top-level"
    requested = parent_id or "top-level"
    raise PlanFileWorkError(
        f"plan {plan_path} already links epic {issue.id} under {actual}; "
        f"--parent requested {requested}, but existing beads cannot be reparented"
    )


def build_work_plan(project: BeadProject, epic_id: str) -> EpicWorkPlan:
    from sase.bead.work import build_epic_work_plan_from_beads_dir

    return build_epic_work_plan_from_beads_dir(project.beads_dir, epic_id)


def ordered_agent_names(plan: EpicWorkPlan) -> tuple[str, ...]:
    return tuple(
        [assignment.agent_name for wave in plan.waves for assignment in wave]
        + [plan.land_agent_name]
    )


def preview_waves(plan: Any) -> tuple[tuple[str, ...], ...]:
    waves = plan_phase_waves(plan.phases)
    if waves is None:
        # Strict validation rejects cycles. Keep this defensive boundary
        # actionable if the Rust wire contract ever regresses.
        raise PlanFileWorkError("validated epic plan contains a dependency cycle")
    return waves


def error_with_resume(
    message: str,
    archived_path: Path,
    *,
    no_push: bool,
    parent_override: str | None = None,
) -> PlanFileWorkError:
    command = f"sase bead work {shlex.quote(str(archived_path))} --yes"
    if no_push:
        command += " --no-push"
    if parent_override is not None:
        command += f" --parent {shlex.quote(parent_override)}"
    return PlanFileWorkError(message, resume_command=command)


def stale_link_message(epic_id: str, plan_path: Path) -> str:
    return (
        f"plan {plan_path} links bead_id {epic_id}, but that bead is missing; "
        "remove the stale bead_id or restore the bead store"
    )
