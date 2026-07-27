"""Plan-file orchestration for ``sase bead work``."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from rich.console import Console

from sase.bead.cli_work_from_plan_helpers import (
    build_work_plan as _build_work_plan,
    error_with_resume as _error_with_resume,
    is_plan_file_target,
    linked_bead_id_if_present as _linked_bead_id_if_present,
    neutral_gate_destination_name as _neutral_gate_destination_name,
    ordered_agent_names as _ordered_agent_names,
    preview_waves as _preview_waves,
    require_linked_epic as _require_linked_epic,
    require_matching_plan_identity as _require_matching_plan_identity,
    require_parent_override_matches_linked as _require_parent_override_matches_linked,
    same_path as _same_path,
)
from sase.bead.cli_work_from_plan_render import (
    render_created_beads as _render_created_beads,
    render_final as _render_final,
    render_parent_preview as _render_parent_preview,
    render_plan_preview as _render_plan_preview,
    render_validation_failure as _render_validation_failure,
)
from sase.bead.cli_work_from_plan_resume import (
    resume_linked_epic as _resume_linked_epic_impl,
)
from sase.bead.cli_work_from_plan_store import (
    commit_plan_file as _commit_plan_file,
    epic_plan_launch_lock as _epic_plan_launch_lock,
    publish_epic_graph_before_launch as _publish_epic_graph_before_launch,
    publish_epic_rollback as _publish_epic_rollback,
    push_store_after_launch as _push_store_after_launch,
    require_epic_launch_store_health,
    require_plan_store_health as _require_plan_store_health,
    resolve_plan_file_context as _resolve_context,
    write_and_commit_plan_file as _write_and_commit_plan_file,
)
from sase.bead.cli_work_from_plan_types import (
    PlanFileWorkError,
    PlanFileWorkResult as _PlanFileWorkResult,
)
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore


def work_from_plan_file(
    target: str,
    *,
    dry_run: bool,
    yes: bool,
    no_push: bool,
    yes_to_all: bool = False,
    parent: str | None = None,
    render: bool = True,
) -> _PlanFileWorkResult:
    """Validate, archive, materialize, link, and launch one epic plan."""
    from sase.sdd.plan_archive import plan_archive_destination
    from sase.sdd.plan_validate import validate_plan_file

    source_path = Path(target).expanduser().resolve(strict=False)
    destination_name = _neutral_gate_destination_name(source_path)
    validation = validate_plan_file(source_path, "epic", mode="launch")
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
        if dry_run:
            _require_plan_store_health(store)
        archive_destination = plan_archive_destination(
            source_path,
            store,
            destination_name=destination_name,
        )
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

    from sase.bead.epic_from_plan import (
        preview_parented_epic_id,
        require_epic_parent,
        selected_epic_parent_id,
    )

    parent_id = selected_epic_parent_id(plan.parent_bead, parent)
    preview_epic_id: str | None = None
    if dry_run and parent_id is not None:
        try:
            with BeadProject(
                location.root,
                beads_dirname=location.beads_dirname,
            ) as project:
                require_epic_parent(project, parent_id, plan_path=source_path)
                preview_epic_id = preview_parented_epic_id(project, parent_id)
        except Exception as exc:
            raise _error_with_resume(
                str(exc),
                source_path,
                no_push=no_push,
                parent_override=parent,
            ) from exc

    if dry_run:
        if archive_destination.is_file() and not _same_path(
            source_path, archive_destination
        ):
            _require_matching_plan_identity(
                source_path,
                source_title=plan.title,
                archived_path=archive_destination,
                no_push=no_push,
            )
        existing_epic_id = _linked_bead_id_if_present(archive_destination)
        if existing_epic_id is not None:
            linked_issue = _require_linked_epic(
                location, existing_epic_id, archive_destination
            )
            _require_parent_override_matches_linked(
                linked_issue,
                parent_id,
                parent_override=parent,
                plan_path=archive_destination,
            )
            parent_id = linked_issue.parent_id
            preview_epic_id = linked_issue.id
        if render:
            Console().print(
                "[green]✓[/green] Archived        "
                f"{archive_destination} (preview; no files written)"
            )
            _render_plan_preview(plan, waves)
            _render_parent_preview(
                parent_id,
                preview_epic_id,
                overridden=parent is not None,
            )
            Console().print("\nDry run complete; no beads or files were changed.")
            Console().print(f"Epic: {existing_epic_id or preview_epic_id or 'dry-run'}")
        return _PlanFileWorkResult(
            archived_plan_path=archive_destination,
            authored_phase_ids=phase_ids,
            dry_run=True,
            epic_id=existing_epic_id,
            parent_id=parent_id,
            preview_epic_id=preview_epic_id,
            resumed=existing_epic_id is not None,
            waves=waves,
        )

    with _epic_plan_launch_lock(store.repo_root):
        return _work_from_plan_file_locked(
            location=location,
            store=store,
            workspace_dir=workspace_dir,
            source_path=source_path,
            destination_name=destination_name,
            plan=plan,
            phase_ids=phase_ids,
            waves=waves,
            parent_id=parent_id,
            parent=parent,
            yes=yes,
            yes_to_all=yes_to_all,
            no_push=no_push,
            render=render,
        )


def _work_from_plan_file_locked(
    *,
    location: Any,
    store: SddStore,
    workspace_dir: Path,
    source_path: Path,
    destination_name: str | None,
    plan: Any,
    phase_ids: tuple[str, ...],
    waves: tuple[tuple[str, ...], ...],
    parent_id: str | None,
    parent: str | None,
    yes: bool,
    yes_to_all: bool,
    no_push: bool,
    render: bool,
) -> _PlanFileWorkResult:
    """Run one mutation transaction while its store launch lock is held."""
    from sase.sdd.plan_archive import archive_plan_file

    try:
        _require_plan_store_health(store)
    except Exception as exc:
        raise _error_with_resume(
            f"approved epic plans store is not safe to use: {exc}",
            source_path,
            no_push=no_push,
        ) from exc

    try:
        archive_result = archive_plan_file(
            source_path,
            store,
            tier="epic",
            destination_name=destination_name,
            preserve_existing=True,
        )
    except Exception as exc:
        raise _error_with_resume(
            f"could not archive epic plan {source_path}: {exc}",
            source_path,
            no_push=no_push,
        ) from exc
    archived_path = archive_result.path
    if not archive_result.written and not _same_path(source_path, archived_path):
        _require_matching_plan_identity(
            source_path,
            source_title=plan.title,
            archived_path=archived_path,
            no_push=no_push,
        )
    if archive_result.written and not _commit_plan_file(
        store,
        workspace_dir=workspace_dir,
        plan_path=archived_path,
        message=f"Archive approved plan {archived_path.stem}",
    ):
        raise _error_with_resume(
            f"failed to commit archived epic plan {archived_path}",
            archived_path,
            no_push=no_push,
        )
    if render:
        detail = "committed" if archive_result.written else "already archived"
        Console().print(f"[green]✓[/green] Archived        {archived_path} ({detail})")

    try:
        _require_plan_store_health(store)
    except Exception as exc:
        raise _error_with_resume(
            f"approved epic plans store is not safe to use: {exc}",
            source_path,
            no_push=no_push,
        ) from exc

    existing_epic_id = _linked_bead_id_if_present(archived_path)
    if existing_epic_id is not None:
        linked_issue = _require_linked_epic(location, existing_epic_id, archived_path)
        _require_parent_override_matches_linked(
            linked_issue,
            parent_id,
            parent_override=parent,
            plan_path=archived_path,
        )
        return _resume_linked_epic(
            location,
            store=store,
            archived_path=archived_path,
            epic_id=existing_epic_id,
            authored_phase_ids=phase_ids,
            yes=yes,
            yes_to_all=yes_to_all,
            no_push=no_push,
            render=render,
            waves=waves,
        )

    from sase.bead.cli_work_handler import launch_epic_bead_work
    from sase.bead.epic_from_plan import (
        EpicFromPlanError,
        create_and_launch_epic_from_plan,
    )
    from sase.sdd.plan_refs import plan_ref_for_store

    plan_ref = plan_ref_for_store(
        archived_path,
        store,
        workspace_dir=workspace_dir,
    )
    launched_names: tuple[str, ...] = ()

    def commit_plan_link(path: Path, content: str, message: str) -> bool:
        return _write_and_commit_plan_file(
            store,
            workspace_dir=workspace_dir,
            plan_path=path,
            content=content,
            message=message,
        )

    def publish_created_graph(project: BeadProject, epic_id: str) -> None:
        _checkpoint_and_publish_graph(
            store=store,
            project=project,
            epic_id=epic_id,
            no_push=no_push,
            render=render,
        )

    def launch_created_epic(project: BeadProject, epic_id: str) -> bool:
        nonlocal launched_names
        issue = project.show(epic_id)
        phases = [
            child
            for child in project.get_epic_children(epic_id)
            if child.issue_type is IssueType.PHASE
        ]
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
            yes_to_all=yes_to_all,
            defer_push=True,
            before_agent_launch=publish_created_graph,
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
                parent_override=parent,
            )
    except Exception as exc:
        retry_requires_push = False
        detail = str(exc)
        if isinstance(exc, EpicFromPlanError):
            retry_requires_push = exc.retry_requires_push
            if exc.graph_published and exc.rollback_performed:
                try:
                    _publish_epic_rollback(store)
                    if render:
                        Console().print(
                            "[yellow]↺[/yellow] Rollback published "
                            "after zero-spawn launch failure"
                        )
                except Exception as rollback_exc:
                    detail += f"; rollback publication also failed: {rollback_exc}"
            elif exc.graph_published and exc.state_preserved:
                _push_store_after_launch(store, no_push=no_push)
        raise _error_with_resume(
            detail,
            archived_path,
            no_push=no_push and not retry_requires_push,
            parent_override=parent,
        ) from exc

    _push_store_after_launch(store, no_push=no_push)
    result = _PlanFileWorkResult(
        archived_plan_path=archived_path,
        authored_phase_ids=phase_ids,
        dry_run=False,
        epic_id=created.epic.id,
        parent_id=created.epic.parent_id,
        phase_bead_ids=tuple(phase.id for phase in created.phases),
        launched_agent_names=launched_names,
        launched=True,
        resumed=False,
        waves=waves,
    )
    if render:
        _render_final(result)
    return result


def _resume_linked_epic(
    location: Any,
    *,
    store: SddStore,
    archived_path: Path,
    epic_id: str,
    authored_phase_ids: tuple[str, ...],
    yes: bool,
    yes_to_all: bool,
    no_push: bool,
    render: bool,
    waves: tuple[tuple[str, ...], ...],
) -> _PlanFileWorkResult:
    return _resume_linked_epic_impl(
        location,
        store=store,
        archived_path=archived_path,
        epic_id=epic_id,
        authored_phase_ids=authored_phase_ids,
        yes=yes,
        yes_to_all=yes_to_all,
        no_push=no_push,
        render=render,
        waves=waves,
        checkpoint_and_publish_graph=_checkpoint_and_publish_graph,
        publish_epic_rollback=_publish_epic_rollback,
        push_store_after_launch=_push_store_after_launch,
    )


def _checkpoint_and_publish_graph(
    *,
    store: SddStore,
    project: BeadProject,
    epic_id: str,
    no_push: bool,
    render: bool,
) -> None:
    """Commit the complete ready graph and cross the visibility barrier."""
    from sase.bead.cli_work_handler import BeadWorkError
    from sase.bead.sync import bead_state_is_clean, commit_epic_graph_checkpoint

    try:
        _require_plan_store_health(store)
        commit_epic_graph_checkpoint(project.beads_dir, epic_id)
        if not bead_state_is_clean(project.beads_dir):
            raise RuntimeError("bead-state changes remain uncommitted")
    except Exception as exc:
        raise BeadWorkError(
            f"epic graph commit failed before agent launch for {epic_id}: {exc}"
        ) from exc
    if render:
        Console().print(
            f"[green]✓[/green] Graph committed epic {epic_id} · ready for worker claims"
        )

    try:
        published = _publish_epic_graph_before_launch(store, no_push=no_push)
    except Exception as exc:
        raise BeadWorkError(
            f"epic graph publication failed before agent launch for {epic_id}: {exc}",
            preserve_epic_state=True,
            retry_requires_push=no_push,
        ) from exc
    if render:
        destination = "remote" if published else "shared authoritative store"
        Console().print(f"[green]✓[/green] Graph published {epic_id} · {destination}")


__all__ = [
    "PlanFileWorkError",
    "is_plan_file_target",
    "require_epic_launch_store_health",
    "work_from_plan_file",
]
