"""Epic bead-work launch planning through preclaim for ``sase bead work``."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sase.bead._cli_work_handler_shared import (
    EpicWorkResult,
    epic_bead_assignees,
    ordered_selected_names,
    resume_command,
)
from sase.bead._store_contention import (
    BeadStoreContentionError,
    retry_bead_store_mutation,
)
from sase.bead.cli_work_cleanup import (
    CleanupPreview,
    ForcedReuseCleanupError,
    prepare_selected_bead_work_force_reuse,
    preview_bead_work_launch_selection,
    revalidate_bead_work_launch_selection,
    rollback_work_launch,
)
from sase.bead.cli_work_cleanup_types import format_blocked_cleanup_error
from sase.bead.cli_work_context import (
    resolve_patch_launch_context,
    resolve_vcs_launch_context,
)
from sase.bead.cli_work_handler_entry import (
    make_bead_work_timer,
    preload_launch_imports,
)
from sase.bead.cli_work_handler_errors import BeadWorkError
from sase.bead.cli_work_name_preflight import (
    preflight_bead_work_launch_names,
)
from sase.bead.cli_work_plan import (
    bead_work_slots,
    confirm_cleanup,
    confirm_launch,
    expected_agent_names,
    print_work_plan_summary,
    render_blocked_launch_warning,
    render_cleanup_preview,
)
from sase.bead.cli_work_plan_snapshot import (
    atomic_copy_epic_plan,
    snapshot_epic_plan,
)
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.operation_context import BeadOperationContext
    from sase.bead.project import EpicPreclaimRollback
    from sase.bead.work import PatchLaunchContext, VCSLaunchContext
    from sase.macro.directive_edit import PromptWaitDirective


def launch_epic_bead_work(
    proj: BeadProject,
    epic_id: str,
    *,
    dry_run: bool,
    yes: bool,
    no_push: bool,
    yes_to_all: bool = False,
    defer_push: bool = False,
    before_agent_launch: Callable[[BeadProject, str], Any] | None = None,
    timer: LaunchTimingRecorder | None = None,
    extra_waits: PromptWaitDirective | None = None,
    capacity: int | None = None,
    bead_context: BeadOperationContext | None = None,
) -> EpicWorkResult:
    """Run the epic bead-work path, returning the structured launch outcome.

    This is the library entry point used both by the CLI and deterministic
    epic approval. It raises :class:`BeadWorkError` instead of terminating the
    process so host-side callers can roll back newly-created epic beads.
    """
    if timer is None:
        owned_timer = make_bead_work_timer(epic_id, dry_run=dry_run)
        with owned_timer:
            return launch_epic_bead_work(
                proj,
                epic_id,
                dry_run=dry_run,
                yes=yes,
                no_push=no_push,
                yes_to_all=yes_to_all,
                defer_push=defer_push,
                before_agent_launch=before_agent_launch,
                timer=owned_timer,
                extra_waits=extra_waits,
                capacity=capacity,
                bead_context=bead_context,
            )

    if not dry_run:
        preload_launch_imports(timer)

    from sase.bead.work import (
        EpicPlanError,
        build_epic_work_plan_from_beads_dir,
        render_multi_prompt,
    )
    from sase.bead.macros import (
        BeadMacroNotFoundError,
        resolve_land_epic_macro,
        resolve_work_phase_macro,
    )

    with timer.stage("xprompt_lookup"):
        try:
            macro_project = (
                bead_context.project_key
                if bead_context is not None and bead_context.project_key
                else None
            )
            work_phase_macro = resolve_work_phase_macro(project=macro_project)
            land_epic_macro = resolve_land_epic_macro(project=macro_project)
        except (BeadMacroNotFoundError, ValueError) as e:
            raise BeadWorkError(str(e)) from e

    timer.add_fields(resolved_epic_id=epic_id)
    issue = proj.show(epic_id)
    with timer.stage("work_plan_build"):
        try:
            plan = build_epic_work_plan_from_beads_dir(proj.beads_dir, epic_id)
        except EpicPlanError as e:
            raise BeadWorkError(str(e)) from e

    vcs_context: VCSLaunchContext | None = None
    patch_context: PatchLaunchContext | None = None
    with timer.stage("vcs_context"):
        if issue.changespec_name:
            try:
                if bead_context is None:
                    patch_context = resolve_patch_launch_context(
                        changespec_name=issue.changespec_name,
                        bug_id=issue.changespec_bug_id,
                    )
                else:
                    patch_context = resolve_patch_launch_context(
                        changespec_name=issue.changespec_name,
                        bug_id=issue.changespec_bug_id,
                        bead_context=bead_context,
                    )
            except ValueError as e:
                raise BeadWorkError(str(e)) from e
        else:
            vcs_context = (
                resolve_vcs_launch_context()
                if bead_context is None
                else resolve_vcs_launch_context(bead_context=bead_context)
            )

    from sase.bead.work_queue_capacity import (
        EpicQueueCapacityConflictError,
        format_raised_capacity_line,
        resolve_epic_queue_capacities,
    )

    with timer.stage("queue_capacity_preflight"):
        try:
            queue_capacities = resolve_epic_queue_capacities(
                plan,
                work_phase_macro,
                land_epic_macro,
                capacity,
            )
        except EpicQueueCapacityConflictError as e:
            raise BeadWorkError(str(e)) from e

    from sase.agent.names import get_reserved_clan_names

    declare_clan = plan.epic_id not in get_reserved_clan_names()
    rendered_capacity = capacity if not queue_capacities.segment_capacity else None
    rendered_segment_capacity = queue_capacities.segment_capacity or None

    def _render_prompt(*, launch_names: frozenset[str] | None = None) -> str:
        from sase.macro.directive_edit import (
            apply_inherited_agent_tab,
            inherited_agent_tab,
        )

        # Lineage inheritance (R2): an EpicApproval approve runs
        # ``sase bead work`` from the planner's tab, so every phase and land
        # segment carries it. Session-attach and explicit-``%tab`` segments
        # keep their own routing per the shared skip rules.
        return apply_inherited_agent_tab(
            render_multi_prompt(
                plan,
                work_phase_macro=work_phase_macro,
                land_epic_macro=land_epic_macro,
                vcs_context=vcs_context,
                patch_context=patch_context,
                declare_clan=declare_clan,
                launch_names=launch_names,
                extra_waits=extra_waits,
                capacity=rendered_capacity,
                segment_capacity=rendered_segment_capacity,
            ),
            inherited_agent_tab(),
        )

    with timer.stage("prompt_render"):
        query = _render_prompt()

    if issue.is_ready_to_work:
        print(f"Epic {epic_id} is already ready; retrying remaining non-closed phases.")
    print_work_plan_summary(epic_id, issue.title, plan)
    for entry in queue_capacities.raised:
        print(format_raised_capacity_line(entry))

    preview: CleanupPreview
    with timer.stage("bead_assignee_reads", bead_count=1 + len(plan.phase_bead_ids)):
        bead_assignees = epic_bead_assignees(proj, plan)
    try:
        slots = bead_work_slots(plan)
        with timer.stage("initial_selection", slot_count=len(slots)):
            preview = preview_bead_work_launch_selection(
                query,
                slots=slots,
                directive_names=expected_agent_names(plan),
                bead_assignees=bead_assignees,
                timer=timer,
            )
    except ForcedReuseCleanupError as e:
        raise BeadWorkError(str(e)) from e
    assert preview.selection is not None
    selection = preview.selection
    timer.add_fields(
        selected_owner_count=len(selection.launch_names),
        preserved_owner_count=len(selection.preserved_names),
        cleanup_owner_count=len(selection.destructive_targets),
        blocked_owner_count=len(selection.blocked_targets),
    )

    if dry_run:
        render_cleanup_preview(epic_id, preview)
        render_blocked_launch_warning(len(selection.blocked_targets))
        dry_query = _render_prompt(launch_names=selection.launch_names)
        print("\n--- Multi-prompt (dry run) ---")
        print(dry_query)
        return EpicWorkResult(
            epic_id=epic_id,
            launch_state="dry_run",
            launched_agent_names=ordered_selected_names(plan, selection.launch_names),
            preserved_agent_names=selection.preserved_names,
        )

    if selection.blocked_targets:
        render_cleanup_preview(epic_id, preview)
        raise BeadWorkError(format_blocked_cleanup_error(selection.blocked_targets))

    if preview.has_destructive_targets:
        render_cleanup_preview(epic_id, preview)
        if not yes_to_all:
            cleanup_confirmation = confirm_cleanup()
            if cleanup_confirmation is None:
                raise BeadWorkError(
                    "refusing destructive agent cleanup with non-interactive "
                    "stdin; re-run with --yes-to-all to proceed non-interactively"
                )
            if not cleanup_confirmation:
                print("Aborted.")
                return EpicWorkResult(
                    epic_id=epic_id,
                    launch_state="declined",
                    preserved_agent_names=selection.preserved_names,
                )

    if not selection.has_launches:
        print(
            f"Epic {epic_id} already has matching active work; no new agents "
            "were launched."
        )
        return EpicWorkResult(
            epic_id=epic_id,
            launch_state="already_running",
            preserved_agent_names=selection.preserved_names,
        )

    if not (yes or yes_to_all):
        launch_confirmation = confirm_launch()
        if launch_confirmation is None:
            raise BeadWorkError(
                "refusing agent launch with non-interactive stdin; re-run with "
                "--yes (or --yes-to-all) to proceed non-interactively"
            )
        if not launch_confirmation:
            print("Aborted.")
            return EpicWorkResult(
                epic_id=epic_id,
                launch_state="declined",
                preserved_agent_names=selection.preserved_names,
            )

    with timer.stage("force_reuse_cleanup"):
        try:
            with timer.stage(
                "bead_assignee_reads",
                bead_count=1 + len(plan.phase_bead_ids),
            ):
                bead_assignees = epic_bead_assignees(proj, plan)
            with timer.stage(
                "target_revalidation",
                total_owners=len(selection.destructive_targets),
            ):
                selection = revalidate_bead_work_launch_selection(
                    selection,
                    bead_assignees=bead_assignees,
                    timer=timer,
                )
            if not selection.has_launches:
                print(
                    f"Epic {epic_id} already has matching active work; no new "
                    "agents were launched."
                )
                return EpicWorkResult(
                    epic_id=epic_id,
                    launch_state="already_running",
                    preserved_agent_names=selection.preserved_names,
                )
            query = _render_prompt(launch_names=selection.launch_names)
            query = prepare_selected_bead_work_force_reuse(
                query,
                selection=selection,
                bead_assignees=bead_assignees,
                timer=timer,
            )
        except ForcedReuseCleanupError as e:
            raise BeadWorkError(str(e)) from e

    try:
        preflight_bead_work_launch_names(
            selection.launch_names,
            resume_command=resume_command(epic_id, capacity=capacity),
            timer=timer,
        )
    except ForcedReuseCleanupError as e:
        raise BeadWorkError(str(e)) from e

    with timer.stage("plan_snapshot"):
        plan_snapshot = snapshot_epic_plan(
            proj,
            epic_id,
            plan_ref=issue.design,
            launch_context=patch_context or vcs_context,
            copy_plan=atomic_copy_epic_plan,
        )

    phase_assignments = [
        (assignment.bead_id, assignment.agent_name)
        for wave in plan.waves
        for assignment in wave
        if assignment.agent_name in selection.launch_names
    ]
    marked_ready_this_run = False
    rollback_preclaims: tuple[EpicPreclaimRollback, ...] = ()
    if not issue.is_ready_to_work:
        try:
            with timer.stage("mark_ready"):
                retry_bead_store_mutation(
                    lambda: proj.mark_ready_to_work(epic_id),
                    beads_dir=proj.beads_dir,
                    what=f"mark epic {epic_id} ready to work",
                    resume_command=resume_command(epic_id, capacity=capacity),
                )
                marked_ready_this_run = True
        except AlreadyReadyError:
            marked_ready_this_run = False
        except (BeadStoreContentionError, KeyError, NotAPlanError, ValueError) as exc:
            raise BeadWorkError(str(exc)) from exc
    try:
        with timer.stage("preclaim"):
            rollback_preclaims = retry_bead_store_mutation(
                lambda: proj.preclaim_epic_work(
                    epic_id,
                    phase_assignments,
                    (
                        plan.land_agent_name
                        if plan.land_agent_name in selection.launch_names
                        else None
                    ),
                ),
                beads_dir=proj.beads_dir,
                what=f"preclaim epic {epic_id}",
                resume_command=resume_command(epic_id, capacity=capacity),
            )
    except (BeadStoreContentionError, KeyError, NotAPlanError, ValueError) as exc:
        rollback_work_launch(
            proj,
            epic_id,
            marked_ready_this_run=marked_ready_this_run,
            rollback_preclaims=rollback_preclaims,
            no_push=True,
        )
        raise BeadWorkError(str(exc)) from exc

    from sase.bead.cli_work_handler_publish import publish_epic_work_graph_and_launch

    return publish_epic_work_graph_and_launch(
        proj,
        epic_id,
        plan=plan,
        issue=issue,
        selection=selection,
        query=query,
        plan_snapshot=plan_snapshot,
        marked_ready_this_run=marked_ready_this_run,
        rollback_preclaims=rollback_preclaims,
        patch_context=patch_context,
        vcs_context=vcs_context,
        timer=timer,
        capacity=capacity,
        no_push=no_push,
        defer_push=defer_push,
        before_agent_launch=before_agent_launch,
    )


__all__ = [
    "launch_epic_bead_work",
]
