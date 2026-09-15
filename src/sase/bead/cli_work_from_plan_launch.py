"""Launch and resume transactions for plan-file bead work."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any

from rich.console import Console

from sase.bead.cli_work_from_plan_helpers import (
    build_work_plan,
    error_with_resume,
    linked_bead_id_if_present,
    ordered_agent_names,
    require_matching_plan_identity,
    require_parent_override_matches_linked,
    resolve_linked_epic,
    same_path,
)
from sase.bead.cli_work_from_plan_hooks import PlanFileWorkLaunchHooks
from sase.bead.cli_work_from_plan_render import (
    render_created_beads,
    render_final,
    render_stale_link_replacement,
)
from sase.bead.cli_work_from_plan_resume import (
    resume_linked_epic as _resume_linked_epic_impl,
)
from sase.bead.cli_work_from_plan_types import (
    PlanFileWorkResult,
    normalize_epic_launch_result,
)
from sase.bead.model import IssueType
from sase.bead.project import BeadProject
from sase.sdd.store import SddStore

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.operation_context import BeadOperationContext
    from sase.xprompt.directive_edit import PromptWaitDirective


def work_from_plan_file_locked(
    *,
    hooks: PlanFileWorkLaunchHooks,
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
) -> PlanFileWorkResult:
    """Run one mutation transaction while its store launch lock is held."""
    from sase.bead.cli_work_handler import preload_launch_imports
    from sase.sdd.plan_archive import archive_plan_file

    preload_launch_imports(timer)

    try:
        with timer.stage("plan_store_health_pre_archive"):
            hooks.require_plan_store_health(store)
    except Exception as exc:
        raise error_with_resume(
            f"approved epic plans store is not safe to use: {exc}",
            source_path,
            no_push=no_push,
            capacity=capacity,
        ) from exc

    try:
        with timer.stage("archive_plan_file"):
            archive_result = archive_plan_file(
                source_path,
                store,
                tier="epic",
                destination_name=destination_name,
                preserve_existing=True,
                expect_prompt_snapshot=expect_prompt_snapshot,
            )
    except Exception as exc:
        raise error_with_resume(
            f"could not archive epic plan {source_path}: {exc}",
            source_path,
            no_push=no_push,
            capacity=capacity,
        ) from exc
    archived_path = archive_result.path
    if not archive_result.written and not same_path(source_path, archived_path):
        require_matching_plan_identity(
            source_path,
            source_title=plan.title,
            archived_path=archived_path,
            no_push=no_push,
            capacity=capacity,
        )
    with timer.stage("archived_plan_commit", written=archive_result.written):
        archive_committed = not archive_result.written or hooks.commit_plan_file(
            store,
            workspace_dir=workspace_dir,
            plan_path=archived_path,
            message=f"Archive approved plan {archived_path.stem}",
        )
    if not archive_committed:
        raise error_with_resume(
            f"failed to commit archived epic plan {archived_path}",
            archived_path,
            no_push=no_push,
            capacity=capacity,
        )
    if render:
        detail = "committed" if archive_result.written else "already archived"
        Console().print(f"[green]✓[/green] Archived        {archived_path} ({detail})")

    try:
        with timer.stage("plan_store_health_post_archive"):
            hooks.require_plan_store_health(store)
    except Exception as exc:
        raise error_with_resume(
            f"approved epic plans store is not safe to use: {exc}",
            source_path,
            no_push=no_push,
            capacity=capacity,
        ) from exc

    linked_epic_id = linked_bead_id_if_present(archived_path)
    stale_epic_id: str | None = None
    if linked_epic_id is not None:
        from sase.bead.epic_from_plan import require_epic_parent

        linked_issue = resolve_linked_epic(
            location,
            linked_epic_id,
            archived_path,
        )
        if linked_issue is not None:
            timer.fields["bead_id"] = linked_issue.id
            if parent_id is not None:
                with ExitStack() as stack:
                    with timer.stage("bead_project_open"):
                        project = stack.enter_context(
                            BeadProject(
                                location.root,
                                beads_dirname=location.beads_dirname,
                            )
                        )
                    parent_issue = require_epic_parent(
                        project, parent_id, plan_path=archived_path
                    )
                    if parent_issue is not None:
                        parent_id = parent_issue.id
            require_parent_override_matches_linked(
                linked_issue,
                parent_id,
                parent_override=parent,
                plan_path=archived_path,
            )
            return resume_linked_epic(
                location,
                hooks=hooks,
                store=store,
                archived_path=archived_path,
                epic_id=linked_issue.id,
                authored_phase_ids=phase_ids,
                bead_context=bead_context,
                yes=yes,
                yes_to_all=yes_to_all,
                no_push=no_push,
                render=render,
                waves=waves,
                timer=timer,
                extra_waits=extra_waits,
                capacity=capacity,
            )
        stale_epic_id = linked_epic_id
        if render:
            render_stale_link_replacement(
                stale_epic_id,
                archived_path,
                dry_run=False,
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
    preserved_names: tuple[str, ...] = ()
    launch_state = ""
    published_relocations: tuple[Any, ...] = ()

    def commit_plan_link(path: Path, content: str, message: str) -> bool:
        return hooks.write_and_commit_plan_file(
            store,
            workspace_dir=workspace_dir,
            plan_path=path,
            content=content,
            message=message,
        )

    def publish_created_graph(project: BeadProject, epic_id: str) -> Any:
        nonlocal published_relocations
        publication = hooks.checkpoint_and_publish_graph(
            store=store,
            project=project,
            epic_id=epic_id,
            no_push=no_push,
            render=render,
        )
        published_relocations = tuple(getattr(publication, "bead_relocations", ()))
        return publication

    def launch_created_epic(project: BeadProject, epic_id: str) -> bool:
        nonlocal launched_names, preserved_names, launch_state
        issue = project.show(epic_id)
        phases = [
            child
            for child in project.get_epic_children(epic_id)
            if child.issue_type is IssueType.PHASE
        ]
        work_plan = build_work_plan(project, epic_id)
        launched_names = ordered_agent_names(work_plan)
        if render:
            render_created_beads(issue, phases, work_plan, archived_path)
        raw_result = launch_epic_bead_work(
            project,
            epic_id,
            dry_run=False,
            yes=yes,
            no_push=no_push,
            yes_to_all=yes_to_all,
            defer_push=True,
            before_agent_launch=publish_created_graph,
            timer=timer,
            extra_waits=extra_waits,
            capacity=capacity,
            bead_context=bead_context,
        )
        result = normalize_epic_launch_result(
            raw_result,
            fallback_launched_agent_names=ordered_agent_names(work_plan),
        )
        launched_names = result.launched_agent_names
        preserved_names = result.preserved_agent_names
        launch_state = result.launch_state
        return result.launched

    try:
        with ExitStack() as stack:
            with timer.stage("bead_project_open"):
                project = stack.enter_context(
                    BeadProject(
                        location.root,
                        beads_dirname=location.beads_dirname,
                    )
                )
            created = create_and_launch_epic_from_plan(
                project,
                plan_path=archived_path,
                plan_ref=plan_ref,
                commit_plan_update=commit_plan_link,
                launch_work=launch_created_epic,
                parent_override=parent,
                replace_stale_bead_id=stale_epic_id,
                store=store,
                primary_root=workspace_dir,
                expect_prompt_snapshot=expect_prompt_snapshot,
                timer=timer,
            )
            from sase.bead.relocation import resolve_created_bead_id

            timer.fields["bead_id"] = resolve_created_bead_id(
                created.epic.id,
                published_relocations,
            )
    except Exception as exc:
        retry_requires_push = False
        detail = str(exc)
        if isinstance(exc, EpicFromPlanError):
            retry_requires_push = exc.retry_requires_push
            if exc.graph_published and exc.rollback_performed:
                try:
                    hooks.publish_epic_rollback(store)
                    if render:
                        Console().print(
                            "[yellow]↺[/yellow] Rollback published "
                            "after zero-spawn launch failure"
                        )
                except Exception as rollback_exc:
                    detail += f"; rollback publication also failed: {rollback_exc}"
            elif exc.graph_published and exc.state_preserved:
                hooks.push_store_after_launch(
                    store,
                    no_push=no_push,
                    archived_plan_path=archived_path,
                )
        raise error_with_resume(
            detail,
            archived_path,
            no_push=no_push and not retry_requires_push,
            parent_override=parent,
            capacity=capacity,
        ) from exc

    hooks.push_store_after_launch(
        store,
        no_push=no_push,
        archived_plan_path=archived_path,
    )
    from sase.bead.relocation import resolve_created_bead_id

    result = PlanFileWorkResult(
        archived_plan_path=archived_path,
        authored_phase_ids=phase_ids,
        dry_run=False,
        epic_id=resolve_created_bead_id(created.epic.id, published_relocations),
        parent_id=created.epic.parent_id,
        replaced_stale_epic_id=stale_epic_id,
        phase_bead_ids=tuple(
            resolve_created_bead_id(phase.id, published_relocations)
            for phase in created.phases
        ),
        launched_agent_names=launched_names,
        preserved_agent_names=preserved_names,
        launch_state=launch_state,
        launched=True,
        resumed=False,
        waves=waves,
        capacity=capacity,
    )
    if render:
        render_final(result)
    return result


def resume_linked_epic(
    location: Any,
    *,
    hooks: PlanFileWorkLaunchHooks,
    store: SddStore,
    archived_path: Path,
    epic_id: str,
    authored_phase_ids: tuple[str, ...],
    bead_context: BeadOperationContext | None,
    yes: bool,
    yes_to_all: bool,
    no_push: bool,
    render: bool,
    waves: tuple[tuple[str, ...], ...],
    timer: LaunchTimingRecorder,
    extra_waits: PromptWaitDirective | None = None,
    capacity: int | None = None,
) -> PlanFileWorkResult:
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
        checkpoint_and_publish_graph=hooks.checkpoint_and_publish_graph,
        publish_epic_rollback=hooks.publish_epic_rollback,
        push_store_after_launch=hooks.push_store_after_launch,
        timer=timer,
        extra_waits=extra_waits,
        capacity=capacity,
        bead_context=bead_context,
    )


def checkpoint_and_publish_graph(
    *,
    hooks: PlanFileWorkLaunchHooks,
    store: SddStore,
    project: BeadProject,
    epic_id: str,
    no_push: bool,
    render: bool,
) -> Any:
    """Commit the complete ready graph and cross the visibility barrier."""
    from sase.bead.cli_work_handler import BeadWorkError
    from sase.bead.sync import bead_state_is_clean, commit_epic_graph_checkpoint

    try:
        hooks.require_plan_store_health(store)
        commit_epic_graph_checkpoint(project.beads_dir, epic_id)
        if not bead_state_is_clean(project.beads_dir):
            raise RuntimeError("bead-state changes remain uncommitted")
    except Exception as exc:
        raise BeadWorkError(
            f"epic graph commit failed before agent launch for {epic_id}: {exc}"
        ) from exc
    if render:
        Console().print(
            f"[green]✓[/green] Graph committed epic {epic_id} · workers preassigned"
        )

    try:
        published = hooks.publish_epic_graph_before_launch(store, no_push=no_push)
    except Exception as exc:
        raise BeadWorkError(
            f"epic graph publication failed before agent launch for {epic_id}: {exc}",
            preserve_epic_state=True,
            retry_requires_push=no_push,
        ) from exc
    if render:
        destination = "remote" if published else "shared authoritative store"
        Console().print(f"[green]✓[/green] Graph published {epic_id} · {destination}")
    return published


__all__ = [
    "PlanFileWorkLaunchHooks",
    "checkpoint_and_publish_graph",
    "resume_linked_epic",
    "work_from_plan_file_locked",
]
