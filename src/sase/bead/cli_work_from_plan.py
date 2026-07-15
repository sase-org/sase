"""Plan-file orchestration for ``sase bead work``."""

from __future__ import annotations

import logging
import shlex
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from rich.console import Console

from sase.bead.cli_common import (
    find_beads_location,
    init_beads,
    resolve_beads_location,
)
from sase.bead.model import BeadTier, IssueType
from sase.bead.project import BEADS_DIRNAME, BeadProject
from sase.sdd.store import SDD_STORAGE_IN_TREE, SddStore

if TYPE_CHECKING:
    from sase.bead.work import EpicWorkPlan
    from sase.sdd.plan_validate import PlanValidationResult

_logger = logging.getLogger(__name__)


class PlanFileWorkError(RuntimeError):
    """A recoverable plan-file launch failure with an optional resume command."""

    def __init__(
        self,
        message: str,
        *,
        resume_command: str | None = None,
        validation: PlanValidationResult | None = None,
    ) -> None:
        super().__init__(message)
        self.resume_command = resume_command
        self.validation = validation


@dataclass(frozen=True)
class _PlanFileWorkResult:
    """Stable result envelope for human and JSON callers."""

    archived_plan_path: Path
    authored_phase_ids: tuple[str, ...]
    dry_run: bool
    epic_id: str | None = None
    phase_bead_ids: tuple[str, ...] = ()
    launched_agent_names: tuple[str, ...] = ()
    launched: bool = False
    resumed: bool = False
    waves: tuple[tuple[str, ...], ...] = ()

    def to_json(self) -> dict[str, object]:
        return {
            "ok": True,
            "mode": "plan_file",
            "dry_run": self.dry_run,
            "epic_id": self.epic_id,
            "phase_bead_ids": list(self.phase_bead_ids),
            "authored_phase_ids": list(self.authored_phase_ids),
            "archived_plan_path": str(self.archived_plan_path),
            "launched_agent_names": list(self.launched_agent_names),
            "launched": self.launched,
            "resumed": self.resumed,
            "waves": [list(wave) for wave in self.waves],
        }


@dataclass(frozen=True)
class _FallbackBeadsLocation:
    """Legacy location used only when store discovery has no project context."""

    root: Path
    beads_dirname: str
    store: None = None

    @property
    def beads_dir(self) -> Path:
        return self.root / self.beads_dirname


def is_plan_file_target(target: str) -> bool:
    """Return whether *target* selects plan-file rather than bead-ID mode."""
    path = Path(target).expanduser()
    return target.endswith(".md") or "/" in target or "\\" in target or path.is_file()


def work_from_plan_file(
    target: str,
    *,
    dry_run: bool,
    yes: bool,
    no_push: bool,
    render: bool = True,
) -> _PlanFileWorkResult:
    """Validate, archive, materialize, link, and launch one epic plan."""
    from sase.sdd.plan_archive import archive_plan_file, plan_archive_destination
    from sase.sdd.plan_validate import validate_plan_file

    source_path = Path(target).expanduser().resolve(strict=False)
    validation = validate_plan_file(source_path, "epic")
    if not validation.ok or validation.plan is None:
        if render:
            _render_validation_failure(source_path, validation)
        raise PlanFileWorkError(
            f"epic plan validation failed: {source_path}",
            validation=validation,
        )

    plan = validation.plan
    phase_ids = tuple(phase.id for phase in plan.phases)
    waves = _preview_waves(plan)
    dependency_count = sum(len(phase.depends_on) for phase in plan.phases)
    if render:
        Console().print(f"[bold]Epic plan[/bold]  {source_path}")
        Console().print(
            "[green]✓[/green] Validated       "
            f"tier: epic · {len(plan.phases)} phases · "
            f"{dependency_count} dependency edges"
        )

    try:
        location, store, workspace_dir = _resolve_context(dry_run=dry_run)
        archive_destination = plan_archive_destination(source_path, store)
    except Exception as exc:
        raise _error_with_resume(
            f"could not resolve the SDD and bead stores: {exc}",
            source_path,
            no_push=no_push,
        ) from exc
    if render:
        Console().print(
            "[green]✓[/green] Store           "
            f"{store.storage} · beads at {location.beads_dir}"
        )

    if dry_run:
        existing_epic_id = _linked_bead_id_if_present(archive_destination)
        if existing_epic_id is not None:
            _require_linked_epic(location, existing_epic_id, archive_destination)
        if render:
            Console().print(
                "[green]✓[/green] Archived        "
                f"{archive_destination} (preview; no files written)"
            )
            _render_plan_preview(plan, waves)
            Console().print("\nDry run complete; no beads or files were changed.")
            Console().print(f"Epic: {existing_epic_id or 'dry-run'}")
        return _PlanFileWorkResult(
            archived_plan_path=archive_destination,
            authored_phase_ids=phase_ids,
            dry_run=True,
            epic_id=existing_epic_id,
            resumed=existing_epic_id is not None,
            waves=waves,
        )

    try:
        archive_result = archive_plan_file(
            source_path,
            store,
            tier="epic",
            preserve_existing=True,
        )
    except Exception as exc:
        raise _error_with_resume(
            f"could not archive epic plan {source_path}: {exc}",
            source_path,
            no_push=no_push,
        ) from exc
    archived_path = archive_result.path
    if archive_result.written and not _commit_plan_file(
        store,
        workspace_dir=workspace_dir,
        plan_path=archived_path,
        no_push=no_push,
        push_after_commit=False,
        message=f"Archive approved plan {source_path.stem}",
    ):
        raise _error_with_resume(
            f"failed to commit archived epic plan {archived_path}",
            archived_path,
            no_push=no_push,
        )
    if render:
        detail = "committed" if archive_result.written else "already archived"
        Console().print(f"[green]✓[/green] Archived        {archived_path} ({detail})")

    existing_epic_id = _linked_bead_id_if_present(archived_path)
    if existing_epic_id is not None:
        return _resume_linked_epic(
            location,
            store=store,
            archived_path=archived_path,
            epic_id=existing_epic_id,
            authored_phase_ids=phase_ids,
            yes=yes,
            no_push=no_push,
            render=render,
            waves=waves,
        )

    from sase.bead.cli_work_handler import launch_epic_bead_work
    from sase.bead.epic_from_plan import create_and_launch_epic_from_plan
    from sase.sdd.plan_refs import plan_ref_for_store

    plan_ref = plan_ref_for_store(
        archived_path,
        store,
        workspace_dir=workspace_dir,
    )
    launched_names: tuple[str, ...] = ()
    plan_link_commit_calls = 0

    def commit_plan_link(path: Path) -> bool:
        nonlocal plan_link_commit_calls
        is_rollback = plan_link_commit_calls > 0
        plan_link_commit_calls += 1
        return _commit_plan_file(
            store,
            workspace_dir=workspace_dir,
            plan_path=path,
            no_push=no_push,
            push_after_commit=is_rollback,
            message=f"Link approved epic plan to its bead: {path.stem}",
        )

    def launch_created_epic(project: BeadProject, epic_id: str) -> bool:
        nonlocal launched_names
        issue = project.show(epic_id)
        phases = project.get_epic_children(epic_id)
        work_plan = _build_work_plan(project, epic_id)
        launched_names = _ordered_agent_names(work_plan)
        if render:
            _render_created_beads(issue, phases, work_plan, archived_path)
        return launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=yes,
            no_push=no_push,
            defer_push=True,
        )

    try:
        with BeadProject(
            location.root,
            beads_dirname=location.beads_dirname,
        ) as project:
            created = create_and_launch_epic_from_plan(
                project,
                plan_path=archived_path,
                plan_ref=plan_ref,
                commit_plan_update=commit_plan_link,
                launch_work=launch_created_epic,
                rollback_push_after_commit=False if no_push else None,
            )
    except Exception as exc:
        raise _error_with_resume(str(exc), archived_path, no_push=no_push) from exc

    _push_store_after_launch(store, no_push=no_push)
    result = _PlanFileWorkResult(
        archived_plan_path=archived_path,
        authored_phase_ids=phase_ids,
        dry_run=False,
        epic_id=created.epic.id,
        phase_bead_ids=tuple(phase.id for phase in created.phases),
        launched_agent_names=launched_names,
        launched=True,
        resumed=False,
        waves=waves,
    )
    if render:
        _render_final(result)
    return result


def _resolve_context(*, dry_run: bool) -> tuple[Any, SddStore, Path]:
    cwd = Path.cwd().expanduser().resolve()
    location: Any = resolve_beads_location(cwd, materialize=not dry_run)
    if location is None:
        if dry_run:
            location = _FallbackBeadsLocation(
                root=cwd,
                beads_dirname=BEADS_DIRNAME,
            )
        else:
            root, beads_dirname = find_beads_location(materialize=True)
            location = _FallbackBeadsLocation(
                root=root,
                beads_dirname=beads_dirname,
            )

    if not dry_run and not location.beads_dir.is_dir():
        init_beads(location.root, location.beads_dirname)

    store = location.store
    if store is None:
        store = SddStore(
            storage=SDD_STORAGE_IN_TREE,
            sdd_dir=location.root / "sdd",
            repo_root=location.root,
        )
    workspace_dir = location.root if store.is_in_tree else cwd
    return location, store, workspace_dir


def _commit_plan_file(
    store: SddStore,
    *,
    workspace_dir: Path,
    plan_path: Path,
    no_push: bool,
    push_after_commit: bool | Literal["async"] | None,
    message: str,
) -> bool:
    effective_push = False if no_push else push_after_commit
    if store.is_in_tree and effective_push is not False:
        from sase.axe.run_agent_exec_plan_sdd import commit_sdd_files_for_exec_plan

        return commit_sdd_files_for_exec_plan(
            str(workspace_dir),
            plan_path.stem,
            plan_tier="epic",
            logger=_logger,
            subprocess_run=subprocess.run,
        )

    from sase.sdd.files import commit_sdd_store_files

    commit_store = store
    if store.is_in_tree:
        commit_store = replace(store, repo_root=workspace_dir)
    return commit_sdd_store_files(
        commit_store,
        message,
        paths=[plan_path],
        push_after_commit=effective_push,
    )


def _push_store_after_launch(store: SddStore, *, no_push: bool) -> None:
    if no_push:
        return
    from sase.sdd._commit_store import push_sdd_store_after_commit

    try:
        push_sdd_store_after_commit(store, push_after_commit="async")
    except Exception:
        _logger.warning("Failed to start deferred SDD store push", exc_info=True)


def _linked_bead_id_if_present(plan_path: Path) -> str | None:
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


def _require_linked_epic(
    location: Any,
    epic_id: str,
    plan_path: Path,
) -> None:
    if not location.beads_dir.is_dir():
        raise PlanFileWorkError(
            _stale_link_message(epic_id, plan_path),
        )
    try:
        with BeadProject(
            location.root,
            beads_dirname=location.beads_dirname,
        ) as project:
            issue = project.show(epic_id)
    except (FileNotFoundError, KeyError) as exc:
        raise PlanFileWorkError(_stale_link_message(epic_id, plan_path)) from exc
    if issue.issue_type is not IssueType.PLAN or issue.tier is not BeadTier.EPIC:
        raise PlanFileWorkError(
            f"plan {plan_path} links bead_id {epic_id}, but that bead is not an "
            "epic plan bead; remove the stale bead_id or restore the correct bead"
        )


def _resume_linked_epic(
    location: Any,
    *,
    store: SddStore,
    archived_path: Path,
    epic_id: str,
    authored_phase_ids: tuple[str, ...],
    yes: bool,
    no_push: bool,
    render: bool,
    waves: tuple[tuple[str, ...], ...],
) -> _PlanFileWorkResult:
    from sase.bead.cli_work_handler import BeadWorkError, launch_epic_bead_work

    try:
        with BeadProject(
            location.root,
            beads_dirname=location.beads_dirname,
        ) as project:
            try:
                issue = project.show(epic_id)
            except KeyError as exc:
                raise PlanFileWorkError(
                    _stale_link_message(epic_id, archived_path)
                ) from exc
            if (
                issue.issue_type is not IssueType.PLAN
                or issue.tier is not BeadTier.EPIC
            ):
                raise PlanFileWorkError(
                    f"plan {archived_path} links bead_id {epic_id}, but that bead "
                    "is not an epic plan bead; remove the stale bead_id or restore "
                    "the correct bead"
                )
            phases = project.get_epic_children(epic_id)
            work_plan = _build_work_plan(project, epic_id)
            launched_names = _ordered_agent_names(work_plan)
            if render:
                Console().print(f"[cyan]↻[/cyan] Epic bead       resuming {epic_id}")
                _render_created_beads(issue, phases, work_plan, archived_path)
            launched = launch_epic_bead_work(
                project,
                epic_id,
                dry_run=False,
                yes=yes,
                no_push=no_push,
                defer_push=True,
            )
    except PlanFileWorkError:
        raise
    except BeadWorkError as exc:
        raise _error_with_resume(str(exc), archived_path, no_push=no_push) from exc
    except Exception as exc:
        raise _error_with_resume(str(exc), archived_path, no_push=no_push) from exc

    if launched:
        _push_store_after_launch(store, no_push=no_push)
    result = _PlanFileWorkResult(
        archived_plan_path=archived_path,
        authored_phase_ids=authored_phase_ids,
        dry_run=False,
        epic_id=epic_id,
        phase_bead_ids=tuple(phase.id for phase in phases),
        launched_agent_names=launched_names if launched else (),
        launched=launched,
        resumed=True,
        waves=waves,
    )
    if render:
        _render_final(result)
    return result


def _build_work_plan(project: BeadProject, epic_id: str) -> EpicWorkPlan:
    from sase.bead.work import build_epic_work_plan_from_beads_dir

    return build_epic_work_plan_from_beads_dir(project.beads_dir, epic_id)


def _ordered_agent_names(plan: EpicWorkPlan) -> tuple[str, ...]:
    return tuple(
        [assignment.agent_name for wave in plan.waves for assignment in wave]
        + [plan.land_agent_name]
    )


def _preview_waves(plan: Any) -> tuple[tuple[str, ...], ...]:
    remaining = {phase.id: set(phase.depends_on) for phase in plan.phases}
    order = [phase.id for phase in plan.phases]
    completed: set[str] = set()
    waves: list[tuple[str, ...]] = []
    while remaining:
        wave = tuple(
            phase_id
            for phase_id in order
            if phase_id in remaining and remaining[phase_id] <= completed
        )
        if not wave:
            # Strict validation rejects cycles. Keep this defensive boundary
            # actionable if the Rust wire contract ever regresses.
            raise PlanFileWorkError("validated epic plan contains a dependency cycle")
        waves.append(wave)
        completed.update(wave)
        for phase_id in wave:
            del remaining[phase_id]
    return tuple(waves)


def _render_validation_failure(
    plan_path: Path,
    validation: PlanValidationResult,
) -> None:
    from sase.main.plan_validate_render import render_validation_human
    from sase.sdd.plan_validate import plan_frontmatter_schema

    render_validation_human(
        validation,
        tier="epic",
        path=str(plan_path),
        schema=plan_frontmatter_schema("epic"),
        console=Console(stderr=True),
    )


def _render_plan_preview(
    plan: Any,
    waves: tuple[tuple[str, ...], ...],
) -> None:
    title_by_id = {phase.id: phase.title for phase in plan.phases}
    for index, wave in enumerate(waves, start=1):
        entries = " · ".join(f"{phase_id} {title_by_id[phase_id]}" for phase_id in wave)
        Console().print(f"  [bold]Wave {index}[/bold]  {entries}")
    Console().print("  [bold]Land[/bold]    @epic_lander")


def _render_created_beads(
    issue: Any,
    phases: list[Any],
    work_plan: EpicWorkPlan,
    archived_path: Path,
) -> None:
    Console().print(f"[green]✓[/green] Epic bead       {issue.id} — {issue.title}")
    phase_text = " · ".join(f"{phase.id} {phase.title}" for phase in phases)
    Console().print(f"[green]✓[/green] Phase beads     {phase_text}")
    dependency_count = sum(len(phase.dependencies) for phase in phases)
    Console().print(
        f"[green]✓[/green] Dependencies    {dependency_count} edges · "
        f"{len(work_plan.waves)} waves"
    )
    Console().print(
        f"[green]✓[/green] Plan linked     bead_id: {issue.id} · {archived_path}"
    )


def _render_final(result: _PlanFileWorkResult) -> None:
    assert result.epic_id is not None
    if result.launched:
        Console().print(
            f"\nEpic {result.epic_id} is underway — track it on the Agents tab, "
            f"or run:\n  sase bead show {result.epic_id}"
        )
    else:
        Console().print(f"\nEpic {result.epic_id} launch was not started.")
    print(f"Epic: {result.epic_id}")


def _error_with_resume(
    message: str,
    archived_path: Path,
    *,
    no_push: bool,
) -> PlanFileWorkError:
    command = f"sase bead work {shlex.quote(str(archived_path))} --yes"
    if no_push:
        command += " --no-push"
    return PlanFileWorkError(message, resume_command=command)


def _stale_link_message(epic_id: str, plan_path: Path) -> str:
    return (
        f"plan {plan_path} links bead_id {epic_id}, but that bead is missing; "
        "remove the stale bead_id or restore the bead store"
    )


__all__ = [
    "PlanFileWorkError",
    "is_plan_file_target",
    "work_from_plan_file",
]
