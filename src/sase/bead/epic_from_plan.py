"""Deterministic epic-plan frontmatter to bead-work orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.cli_work_handler import BeadWorkError
from sase.bead.model import BeadTier, Dependency, Issue, IssueType
from sase.bead.phase_description import generated_phase_description
from sase.bead.project import BeadProject

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.sdd.store import SddStore

type PlanUpdateCommitter = Callable[[Path, str, str], bool]
type EpicWorkLauncher = Callable[[BeadProject, str], bool]


@contextmanager
def _timed_stage(
    timer: LaunchTimingRecorder | None,
    name: str,
    **fields: Any,
) -> Iterator[None]:
    if timer is None:
        yield
        return
    with timer.stage(name, **fields):
        yield


class EpicFromPlanError(RuntimeError):
    """Deterministic epic creation or kickoff failed."""

    def __init__(
        self,
        message: str,
        *,
        graph_published: bool = False,
        state_preserved: bool = False,
        rollback_performed: bool = False,
        retry_requires_push: bool = False,
    ) -> None:
        super().__init__(message)
        self.graph_published = graph_published
        self.state_preserved = state_preserved
        self.rollback_performed = rollback_performed
        self.retry_requires_push = retry_requires_push


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
    parent_override: str | None = None,
    store: SddStore | None = None,
    primary_root: Path | None = None,
    expect_prompt_snapshot: bool = False,
    timer: LaunchTimingRecorder | None = None,
) -> _EpicFromPlanResult:
    """Create an epic DAG, link the plan, and launch ``sase bead work``.

    The plan is validated again at the consumption boundary. Creation order is
    exactly frontmatter order, and dependency references are resolved through
    the frontmatter phase IDs. Failures before publication remove the newly
    created epic (cascading to its phases) and restore the plan file. A failed
    publication preserves its locally committed graph for a safe retry. Once
    a runner has spawned, the linked epic likewise remains available for an
    explicit resume.
    """
    from sase.sdd.frontmatter import parse_frontmatter, set_frontmatter_fields
    from sase.sdd.plan_validate import validate_plan_file

    plan_path = plan_path.expanduser().resolve()
    original_content = plan_path.read_text(encoding="utf-8")
    validation = validate_plan_file(plan_path, "epic", mode="launch")
    if not validation.ok or validation.plan is None:
        details = "; ".join(
            f"[{diagnostic.code}] {diagnostic.message}"
            for diagnostic in validation.diagnostics
            if diagnostic.is_error
        )
        raise EpicFromPlanError(
            f"approved epic plan failed deterministic validation: {details}"
        )

    frontmatter, _body, _had_frontmatter = parse_frontmatter(original_content)
    existing_bead_id = frontmatter.get("bead_id")
    if existing_bead_id not in (None, ""):
        raise EpicFromPlanError(
            f"approved epic plan already links bead_id {existing_bead_id!r}; "
            "refusing to create a duplicate epic"
        )

    plan = validation.plan
    if plan.title is None:
        # The Rust epic schema makes this unreachable, but keeping the host
        # boundary explicit avoids creating an untitled bead if wire contracts
        # ever drift.
        raise EpicFromPlanError("validated epic plan is missing its title")
    parent_id = selected_epic_parent_id(plan.parent_bead, parent_override)
    parent_issue = require_epic_parent(proj, parent_id, plan_path=plan_path)
    if parent_issue is not None:
        parent_id = parent_issue.id

    from sase.bead.attribution import resolve_bead_creator

    epic: Issue | None = None
    plan_link_update_attempted = False
    plan_link_committed = False
    try:
        with _timed_stage(timer, "epic_creation"):
            epic = proj.create(
                title=plan.title,
                issue_type=IssueType.PLAN,
                parent_id=parent_id,
                description=plan.goal,
                design=plan_ref,
                tier=BeadTier.EPIC,
                changespec_name=plan.patch or "",
                changespec_bug_id=plan.bug_id or "",
                model=plan.model or "",
                created_by=resolve_bead_creator(
                    issue_type=IssueType.PLAN,
                    plan_proposed_by=plan.proposed_by,
                ),
            )
        if proj.last_prefix_repair is not None:
            from sase.bead.cli_work_from_plan_render import render_prefix_repair

            render_prefix_repair(*proj.last_prefix_repair)
        if timer is not None:
            timer.fields["bead_id"] = epic.id

        phase_by_frontmatter_id: dict[str, Issue] = {}
        phases: list[Issue] = []
        with _timed_stage(timer, "phase_creation", phase_count=len(plan.phases)):
            for phase_spec in plan.phases:
                # Core inherits the epic creator for phases, keeping the complete
                # generated DAG attributed to one plan proposer.
                phase = proj.create(
                    title=phase_spec.title,
                    issue_type=IssueType.PHASE,
                    parent_id=epic.id,
                    description=phase_spec.description
                    or generated_phase_description(plan_ref, phase_spec.id),
                    model=phase_spec.model or "",
                    size=phase_spec.size,
                )
                phases.append(phase)
                phase_by_frontmatter_id[phase_spec.id] = phase

        dependencies: list[Dependency] = []
        with _timed_stage(timer, "dependency_creation"):
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
        linked_content = set_frontmatter_fields(
            original_content,
            {"bead_id": epic.id},
        )
        from sase.sdd.plan_header_writes import project_plan_header_sections

        legacy_prompt = plan_path.parent / "prompts" / plan_path.name
        plans_root = store.kind_root("plans") if store is not None else plan_path.parent
        with _timed_stage(timer, "header_projection"):
            linked_content = project_plan_header_sections(
                linked_content,
                sdd_dir=store.sdd_dir if store is not None else plans_root,
                plan_path=plan_path,
                plans_root=plans_root,
                prompt_path=(
                    plan_path
                    if expect_prompt_snapshot
                    else legacy_prompt
                    if legacy_prompt.is_file()
                    else None
                ),
                store=store,
                primary_root=primary_root,
            )
        plan_link_update_attempted = True
        with _timed_stage(timer, "plan_link_commit"):
            plan_link_committed = commit_plan_update(
                plan_path,
                linked_content,
                f"Link approved epic plan to its bead: {plan_path.stem}",
            )
        if not plan_link_committed:
            raise EpicFromPlanError(
                f"failed to commit bead_id {epic.id} to approved plan {plan_path}"
            )
        launched = launch_work(proj, epic.id)
        if not launched:
            raise EpicFromPlanError(
                f"automatic bead work launch for epic {epic.id} was aborted"
            )
        return result
    except Exception as exc:
        if isinstance(exc, BeadWorkError) and (
            exc.agents_spawned or exc.preserve_epic_state
        ):
            # A runner may already have durably claimed its bead. Removing the
            # epic would discard the recoverable launch state. Publication
            # failures also preserve the locally committed graph as the retry
            # point even though their spawn boundary remains false.
            raise EpicFromPlanError(
                str(exc),
                graph_published=exc.graph_published,
                state_preserved=True,
                retry_requires_push=exc.retry_requires_push,
            ) from exc

        rollback_errors = _rollback_epic_creation(
            proj,
            epic=epic,
            plan_path=plan_path,
            original_content=original_content,
            plan_link_update_attempted=plan_link_update_attempted,
            plan_link_committed=plan_link_committed,
            commit_plan_update=commit_plan_update,
        )
        detail = str(exc)
        if rollback_errors:
            detail += "; rollback also failed: " + "; ".join(rollback_errors)
        raise EpicFromPlanError(
            detail,
            graph_published=(
                exc.graph_published if isinstance(exc, BeadWorkError) else False
            ),
            rollback_performed=True,
            retry_requires_push=(
                exc.retry_requires_push if isinstance(exc, BeadWorkError) else False
            ),
        ) from exc


def selected_epic_parent_id(
    plan_parent_id: str | None,
    parent_override: str | None,
) -> str | None:
    """Return the effective parent for an epic plan launch.

    ``None`` means no CLI override was supplied, while an empty value or the
    documented ``top-level`` token explicitly clears a plan's managed parent.
    ``none`` is accepted as a convenient non-interactive synonym.
    """
    if parent_override is None:
        return plan_parent_id
    normalized = parent_override.strip()
    if normalized.lower() in {"", "none", "top-level"}:
        return None
    return normalized


def require_epic_parent(
    proj: BeadProject,
    parent_id: str | None,
    *,
    plan_path: Path,
) -> Issue | None:
    """Resolve an epic parent in the active store or raise with a remedy."""
    if parent_id is None:
        return None
    try:
        return proj.show(parent_id)
    except KeyError as exc:
        raise EpicFromPlanError(
            f"epic plan {plan_path} names parent bead {parent_id!r}, but that "
            "bead is missing from the active store; restore the parent bead, "
            "choose another with --parent <bead-id>, or force a top-level "
            "epic with --parent top-level"
        ) from exc


def preview_parented_epic_id(proj: BeadProject, parent_id: str) -> str:
    """Preview Rust's next direct-child allocation without mutating the store."""
    prefix = f"{parent_id}."
    highest = 0
    for issue in proj.list_issues():
        if issue.parent_id != parent_id or not issue.id.startswith(prefix):
            continue
        suffix = issue.id[len(prefix) :]
        if suffix.isdigit():
            highest = max(highest, int(suffix))
    return f"{parent_id}.{highest + 1}"


def _rollback_epic_creation(
    proj: BeadProject,
    *,
    epic: Issue | None,
    plan_path: Path,
    original_content: str,
    plan_link_update_attempted: bool,
    plan_link_committed: bool,
    commit_plan_update: PlanUpdateCommitter,
) -> list[str]:
    errors: list[str] = []
    if epic is not None:
        try:
            from sase.bead.sync import (
                bead_store_write_lock,
                commit_epic_creation_rollback,
            )

            with bead_store_write_lock(proj.beads_dir) as already_locked:
                proj.remove(epic.id)
                commit_epic_creation_rollback(
                    proj.beads_dir,
                    epic.id,
                    already_locked=already_locked,
                )
        except Exception as exc:  # noqa: BLE001 - rollback is best effort
            errors.append(f"could not remove epic {epic.id}: {exc}")

    if plan_link_update_attempted:
        try:
            # A false result is benign when the failed forward commit never
            # reached git; an exception still reports an incomplete rollback.
            restored = commit_plan_update(
                plan_path,
                original_content,
                f"Restore approved epic plan after failed launch: {plan_path.stem}",
            )
            if plan_link_committed and not restored:
                errors.append(f"could not commit restored approved plan {plan_path}")
        except Exception as exc:  # noqa: BLE001 - preserve the primary error
            errors.append(f"could not restore approved plan {plan_path}: {exc}")
    return errors


__all__ = [
    "EpicFromPlanError",
    "create_and_launch_epic_from_plan",
    "preview_parented_epic_id",
    "require_epic_parent",
    "selected_epic_parent_id",
]
