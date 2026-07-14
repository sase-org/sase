"""Deterministic epic-plan frontmatter to bead-work orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from sase.bead.cli_common import auto_commit_bead_store
from sase.bead.cli_work_handler import BeadWorkError
from sase.bead.model import BeadTier, Dependency, Issue, IssueType
from sase.bead.project import BeadProject

type PlanUpdateCommitter = Callable[[Path], bool]
type EpicWorkLauncher = Callable[[BeadProject, str], bool]


class _EpicFromPlanError(RuntimeError):
    """Deterministic epic creation or kickoff failed."""


@dataclass(frozen=True)
class _EpicFromPlanResult:
    """Beads allocated from one validated epic plan."""

    epic: Issue
    phases: tuple[Issue, ...]
    dependencies: tuple[Dependency, ...]


def create_and_launch_epic_from_plan(
    proj: BeadProject,
    *,
    plan_path: Path,
    plan_ref: str,
    commit_plan_update: PlanUpdateCommitter,
    launch_work: EpicWorkLauncher,
) -> _EpicFromPlanResult:
    """Create an epic DAG, link the plan, and launch ``sase bead work``.

    The plan is validated again at the consumption boundary. Creation order is
    exactly frontmatter order, and dependency references are resolved through
    the frontmatter phase IDs. Any failure before a complete agent launch
    removes the newly-created epic (cascading to its phases), restores the plan
    file, and records the rollback in non-in-tree bead stores.
    """
    from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields
    from sase.sdd.plan_validate import validate_plan_file

    plan_path = plan_path.expanduser().resolve()
    original_content = plan_path.read_text(encoding="utf-8")
    validation = validate_plan_file(plan_path, "epic")
    if not validation.ok or validation.plan is None:
        details = "; ".join(
            f"[{diagnostic.code}] {diagnostic.message}"
            for diagnostic in validation.diagnostics
            if diagnostic.is_error
        )
        raise _EpicFromPlanError(
            f"approved epic plan failed deterministic validation: {details}"
        )

    frontmatter, _body, _had_frontmatter = parse_frontmatter(original_content)
    existing_bead_id = frontmatter.get("bead_id")
    if existing_bead_id not in (None, ""):
        raise _EpicFromPlanError(
            f"approved epic plan already links bead_id {existing_bead_id!r}; "
            "refusing to create a duplicate epic"
        )

    plan = validation.plan
    if plan.title is None:
        # The Rust epic schema makes this unreachable, but keeping the host
        # boundary explicit avoids creating an untitled bead if wire contracts
        # ever drift.
        raise _EpicFromPlanError("validated epic plan is missing its title")

    epic: Issue | None = None
    plan_link_written = False
    try:
        epic = proj.create(
            title=plan.title,
            issue_type=IssueType.PLAN,
            description=plan.goal,
            design=plan_ref,
            tier=BeadTier.EPIC,
            changespec_name=plan.changespec or "",
            changespec_bug_id=plan.bug_id or "",
            model=plan.model or "",
        )

        linked_content = set_frontmatter_fields(
            original_content,
            {"bead_id": epic.id},
        )
        plan_path.write_text(linked_content, encoding="utf-8")
        plan_link_written = True
        if not commit_plan_update(plan_path):
            raise _EpicFromPlanError(
                f"failed to commit bead_id {epic.id} to approved plan {plan_path}"
            )

        phase_by_frontmatter_id: dict[str, Issue] = {}
        phases: list[Issue] = []
        for phase_spec in plan.phases:
            phase = proj.create(
                title=phase_spec.title,
                issue_type=IssueType.PHASE,
                parent_id=epic.id,
                description=phase_spec.description
                or _generated_phase_description(plan_ref, phase_spec.id),
                model=phase_spec.model or "",
            )
            phases.append(phase)
            phase_by_frontmatter_id[phase_spec.id] = phase

        dependencies: list[Dependency] = []
        for phase_spec in plan.phases:
            phase = phase_by_frontmatter_id[phase_spec.id]
            for dependency_id in phase_spec.depends_on:
                dependencies.append(
                    proj.add_dependency(
                        phase.id,
                        phase_by_frontmatter_id[dependency_id].id,
                    )
                )

        result = _EpicFromPlanResult(
            epic=epic,
            phases=tuple(phases),
            dependencies=tuple(dependencies),
        )
        launched = launch_work(proj, epic.id)
        if not launched:
            raise _EpicFromPlanError(
                f"automatic bead work launch for epic {epic.id} was aborted"
            )
        return result
    except Exception as exc:
        if isinstance(exc, BeadWorkError) and exc.agents_launched:
            # Every requested agent is already running. Removing their beads
            # would make those live agents orphaned; preserve the successful
            # launch and surface the post-launch commit failure as actionable.
            raise _EpicFromPlanError(str(exc)) from exc

        rollback_errors = _rollback_epic_creation(
            proj,
            epic=epic,
            plan_path=plan_path,
            original_content=original_content,
            plan_link_written=plan_link_written,
            commit_plan_update=commit_plan_update,
        )
        detail = str(exc)
        if rollback_errors:
            detail += "; rollback also failed: " + "; ".join(rollback_errors)
        if isinstance(exc, _EpicFromPlanError) and not rollback_errors:
            raise
        raise _EpicFromPlanError(detail) from exc


def _generated_phase_description(plan_ref: str, phase_id: str) -> str:
    """Return the stable fallback pointer used for description-less phases."""
    return f"Phase `{phase_id}` in approved epic plan `{plan_ref}`."


def _rollback_epic_creation(
    proj: BeadProject,
    *,
    epic: Issue | None,
    plan_path: Path,
    original_content: str,
    plan_link_written: bool,
    commit_plan_update: PlanUpdateCommitter,
) -> list[str]:
    errors: list[str] = []
    if epic is not None:
        try:
            proj.remove(epic.id)
            auto_commit_bead_store(
                f"chore(beads): rollback deterministic epic creation {epic.id}"
            )
        except Exception as exc:  # noqa: BLE001 - rollback is best effort
            errors.append(f"could not remove epic {epic.id}: {exc}")

    if plan_link_written:
        try:
            plan_path.write_text(original_content, encoding="utf-8")
            # A false result is benign when the failed forward commit never
            # reached git; an exception still reports an incomplete rollback.
            commit_plan_update(plan_path)
        except Exception as exc:  # noqa: BLE001 - preserve the primary error
            errors.append(f"could not restore approved plan {plan_path}: {exc}")
    return errors


__all__ = [
    "create_and_launch_epic_from_plan",
]
