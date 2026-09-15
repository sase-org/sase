"""Plan-file orchestration for ``sase bead work``."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from sase.bead.cli_work_from_plan_helpers import (
    error_with_resume as _error_with_resume,
    is_plan_file_target,
    linked_bead_id_if_present as _linked_bead_id_if_present,
    neutral_gate_destination_name as _neutral_gate_destination_name,
    preview_waves as _preview_waves,
    require_matching_plan_identity as _require_matching_plan_identity,
    require_parent_override_matches_linked as _require_parent_override_matches_linked,
    resolve_linked_epic as _resolve_linked_epic,
    same_path as _same_path,
)
from sase.bead.cli_work_from_plan_hooks import (
    PlanFileWorkLaunchHooks as _PlanFileWorkLaunchHooks,
)
from sase.bead.cli_work_from_plan_launch import (
    checkpoint_and_publish_graph as _checkpoint_and_publish_graph_impl,
    work_from_plan_file_locked as _work_from_plan_file_locked_impl,
)
from sase.bead.cli_work_from_plan_render import (
    render_parent_preview as _render_parent_preview,
    render_plan_preview as _render_plan_preview,
    render_stale_link_replacement as _render_stale_link_replacement,
    render_validation_failure as _render_validation_failure,
)
from sase.bead.cli_work_from_plan_store import (
    commit_plan_file as _commit_plan_file,
    epic_launch_lock_anchor as _epic_launch_lock_anchor,
    epic_plan_launch_lock as _epic_plan_launch_lock,
    publish_epic_graph_before_launch_result as _publish_epic_graph_before_launch,
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
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.operation_context import BeadOperationContext
    from sase.xprompt.directive_edit import PromptWaitDirective


def work_from_plan_file(
    target: str,
    *,
    dry_run: bool,
    yes: bool,
    no_push: bool,
    yes_to_all: bool = False,
    parent: str | None = None,
    render: bool = True,
    expect_prompt_snapshot: bool = False,
    timer: LaunchTimingRecorder | None = None,
    extra_waits: PromptWaitDirective | None = None,
    capacity: int | None = None,
) -> _PlanFileWorkResult:
    """Validate, archive, materialize, link, and launch one epic plan."""
    if timer is None:
        from sase.bead.cli_work_handler import make_bead_work_timer

        owned_timer = make_bead_work_timer(target, dry_run=dry_run)
        with owned_timer:
            return work_from_plan_file(
                target,
                dry_run=dry_run,
                yes=yes,
                no_push=no_push,
                yes_to_all=yes_to_all,
                parent=parent,
                render=render,
                expect_prompt_snapshot=expect_prompt_snapshot,
                timer=owned_timer,
                extra_waits=extra_waits,
                capacity=capacity,
            )

    from sase.sdd.plan_archive import plan_archive_destination
    from sase.sdd.plan_validate import validate_plan_file

    source_path = Path(target).expanduser().resolve(strict=False)
    timer.fields["plan_path"] = str(source_path)
    destination_name = _neutral_gate_destination_name(source_path)
    with timer.stage("plan_validation"):
        validation = validate_plan_file(source_path, "epic", mode="launch")
    if not validation.ok or validation.plan is None:
        if render:
            _render_validation_failure(source_path, validation)
        raise PlanFileWorkError(
            f"epic plan validation failed: {source_path}",
            validation=validation,
        )

    with ExitStack() as stack:
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

        from sase.bead.epic_from_plan import (
            preview_parented_epic_id,
            require_epic_parent,
            selected_epic_parent_id,
        )

        parent_id = selected_epic_parent_id(plan.parent_bead, parent)
        parent_bead_context = _resolve_parent_bead_context(
            parent_id,
            source_path=source_path,
            dry_run=dry_run,
            no_push=no_push,
            parent=parent,
            capacity=capacity,
        )
        if not dry_run:
            with timer.stage("plan_launch_lock"):
                stack.enter_context(
                    _epic_plan_launch_lock(
                        _plan_file_launch_lock_anchor(parent_bead_context),
                        plan_file=source_path,
                    )
                )
        try:
            with timer.stage("store_context"):
                location, store, workspace_dir = _resolve_plan_file_context(
                    dry_run=dry_run,
                    bead_context=parent_bead_context,
                )
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
                parent_override=parent,
                capacity=capacity,
            ) from exc
        if render:
            Console().print(
                "[green]✓[/green] Store           "
                f"{store.storage} · beads at {location.beads_dir}"
            )

        preview_epic_id: str | None = None
        if dry_run and parent_id is not None:
            try:
                with ExitStack() as preview_stack:
                    with timer.stage("bead_project_open"):
                        project = preview_stack.enter_context(
                            BeadProject(
                                location.root,
                                beads_dirname=location.beads_dirname,
                            )
                        )
                    parent_issue = require_epic_parent(
                        project, parent_id, plan_path=source_path
                    )
                    if parent_issue is not None:
                        parent_id = parent_issue.id
                    preview_epic_id = preview_parented_epic_id(project, parent_id)
            except Exception as exc:
                raise _error_with_resume(
                    str(exc),
                    source_path,
                    no_push=no_push,
                    parent_override=parent,
                    capacity=capacity,
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
                    capacity=capacity,
                )
            linked_epic_id = _linked_bead_id_if_present(archive_destination)
            existing_epic_id: str | None = None
            stale_epic_id: str | None = None
            if linked_epic_id is not None:
                linked_issue = _resolve_linked_epic(
                    location, linked_epic_id, archive_destination
                )
                if linked_issue is None:
                    stale_epic_id = linked_epic_id
                else:
                    existing_epic_id = linked_issue.id
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
                if stale_epic_id is not None:
                    _render_stale_link_replacement(
                        stale_epic_id,
                        archive_destination,
                        dry_run=True,
                    )
                _render_plan_preview(plan, waves)
                _render_parent_preview(
                    parent_id,
                    preview_epic_id,
                    overridden=parent is not None,
                )
                Console().print("\nDry run complete; no beads or files were changed.")
                preview_label = (
                    existing_epic_id
                    or preview_epic_id
                    or ("new epic" if stale_epic_id is not None else "dry-run")
                )
                stale_suffix = (
                    f" (replaces stale {stale_epic_id})"
                    if stale_epic_id is not None
                    else ""
                )
                Console().print(f"Epic: {preview_label}{stale_suffix}")
            return _PlanFileWorkResult(
                archived_plan_path=archive_destination,
                authored_phase_ids=phase_ids,
                dry_run=True,
                epic_id=existing_epic_id,
                parent_id=parent_id,
                preview_epic_id=preview_epic_id,
                replaced_stale_epic_id=stale_epic_id,
                resumed=existing_epic_id is not None,
                waves=waves,
                capacity=capacity,
            )

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
            bead_context=parent_bead_context,
            yes=yes,
            yes_to_all=yes_to_all,
            no_push=no_push,
            render=render,
            expect_prompt_snapshot=expect_prompt_snapshot,
            timer=timer,
            extra_waits=extra_waits,
            capacity=capacity,
        )


def _launch_hooks() -> _PlanFileWorkLaunchHooks:
    return _PlanFileWorkLaunchHooks(
        commit_plan_file=_commit_plan_file,
        write_and_commit_plan_file=_write_and_commit_plan_file,
        checkpoint_and_publish_graph=_checkpoint_and_publish_graph,
        publish_epic_graph_before_launch=_publish_epic_graph_before_launch,
        publish_epic_rollback=_publish_epic_rollback,
        push_store_after_launch=_push_store_after_launch,
        require_plan_store_health=_require_plan_store_health,
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
    bead_context: BeadOperationContext | None,
    yes: bool,
    yes_to_all: bool,
    no_push: bool,
    render: bool,
    expect_prompt_snapshot: bool = False,
    timer: LaunchTimingRecorder,
    extra_waits: PromptWaitDirective | None = None,
    capacity: int | None = None,
) -> _PlanFileWorkResult:
    return _work_from_plan_file_locked_impl(
        hooks=_launch_hooks(),
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
        bead_context=bead_context,
        yes=yes,
        yes_to_all=yes_to_all,
        no_push=no_push,
        render=render,
        expect_prompt_snapshot=expect_prompt_snapshot,
        timer=timer,
        extra_waits=extra_waits,
        capacity=capacity,
    )


def _checkpoint_and_publish_graph(
    *,
    store: SddStore,
    project: BeadProject,
    epic_id: str,
    no_push: bool,
    render: bool,
) -> Any:
    return _checkpoint_and_publish_graph_impl(
        hooks=_launch_hooks(),
        store=store,
        project=project,
        epic_id=epic_id,
        no_push=no_push,
        render=render,
    )


def _resolve_plan_file_context(
    *,
    dry_run: bool,
    bead_context: BeadOperationContext | None,
) -> tuple[Any, SddStore, Path]:
    if bead_context is None:
        return _resolve_context(dry_run=dry_run)
    return _resolve_context(dry_run=dry_run, bead_context=bead_context)


def _plan_file_launch_lock_anchor(
    bead_context: BeadOperationContext | None,
) -> Path:
    if bead_context is None:
        return _epic_launch_lock_anchor()
    location = bead_context.location
    store = location.store
    workspace_dir = (
        location.root
        if store is None or store.is_in_tree
        else bead_context.primary_workspace or bead_context.invocation_cwd
    )
    return _epic_launch_lock_anchor(workspace_dir)


def _resolve_parent_bead_context(
    parent_id: str | None,
    *,
    source_path: Path,
    dry_run: bool,
    no_push: bool,
    parent: str | None,
    capacity: int | None,
) -> BeadOperationContext | None:
    if parent_id is None:
        return None
    from sase.bead.operation_context import (
        BeadOperationRoutingError,
        resolve_operation_context_for_targets,
    )

    try:
        return resolve_operation_context_for_targets(
            [parent_id],
            for_write=not dry_run,
            materialize=not dry_run,
        )
    except BeadOperationRoutingError as exc:
        message = str(exc)
        missing = "not found" in message.casefold()
        detail = (
            f"epic plan {source_path} names parent bead {parent_id!r}, but that "
            "bead is missing from the active store and enabled project stores; "
            "restore the parent bead, choose another with --parent <bead-id>, "
            "or force a top-level epic with --parent top-level"
            if missing
            else (
                f"epic plan {source_path} names parent bead {parent_id!r}, but "
                f"that bead could not be resolved: {message}"
            )
        )
        raise _error_with_resume(
            detail,
            source_path,
            no_push=no_push,
            parent_override=parent,
            capacity=capacity,
        ) from exc


__all__ = [
    "PlanFileWorkError",
    "is_plan_file_target",
    "require_epic_launch_store_health",
    "work_from_plan_file",
]
