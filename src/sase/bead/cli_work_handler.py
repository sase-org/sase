"""Epic launch orchestration and compatibility helpers for ``sase bead work``."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

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
from sase.bead.cli_work_commit import (
    EpicLaunchCheckpointError,
    checkpoint_epic_work_launch,
)
from sase.bead.cli_work_context import (
    resolve_vcs_launch_context,
    resolve_patch_launch_context,
)
from sase.bead.cli_work_launch import launch_bead_work_agents
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
    epic_plan_snapshot_destination,
    epic_plan_source_path,
    snapshot_epic_plan,
)
from sase.bead.cli_work_task import (
    TaskBeadWorkError as TaskBeadWorkError,
    TaskWorkResult as TaskWorkResult,
    launch_task_bead_work as launch_task_bead_work,
)
from sase.bead.cli_work_entry import handle_bead_work as dispatch_bead_work
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.project import EpicPreclaimRollback
    from sase.bead.work import (
        PatchLaunchContext,
        VCSLaunchContext,
    )
    from sase.xprompt.directive_edit import PromptWaitDirective


BEAD_WORK_TIMING_ENV = "SASE_BEAD_WORK_TIMING"

type EpicLaunchState = Literal[
    "already_running",
    "declined",
    "dry_run",
    "launched",
]


@dataclass(frozen=True)
class _EpicWorkResult:
    """Outcome of one epic bead-work request."""

    epic_id: str
    launch_state: EpicLaunchState
    launched_agent_names: tuple[str, ...] = ()
    preserved_agent_names: tuple[str, ...] = ()
    workspace_num: int | None = None

    @property
    def launched(self) -> bool:
        return self.launch_state == "launched"

    def __bool__(self) -> bool:
        return self.launched


class BeadWorkError(RuntimeError):
    """A recoverable ``sase bead work`` orchestration failure.

    ``agents_spawned`` records that at least one runner crossed the spawn
    boundary, so plan-file callers must preserve the recoverable epic state.
    ``agents_launched`` remains available for compatibility with host callers.

    ``graph_published`` records that the pre-launch visibility barrier
    completed. ``preserve_epic_state`` is reserved for failures where the
    locally committed graph is the safe resume point even though no runner
    spawned, such as a rejected ``--no-push`` detached-store launch.
    """

    def __init__(
        self,
        message: str,
        *,
        agents_spawned: bool = False,
        agents_launched: bool = False,
        graph_published: bool = False,
        preserve_epic_state: bool = False,
        retry_requires_push: bool = False,
    ) -> None:
        super().__init__(message)
        self.agents_spawned = agents_spawned or agents_launched
        self.agents_launched = agents_launched
        self.graph_published = graph_published
        self.preserve_epic_state = preserve_epic_state
        self.retry_requires_push = retry_requires_push


def make_bead_work_timer(target: str, *, dry_run: bool) -> Any:
    """Build a launch timer promoted to info logs by ``SASE_BEAD_WORK_TIMING``."""
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.cli_work_from_plan_helpers import is_plan_file_target

    identity_field = "plan_path" if is_plan_file_target(target) else "bead_id"

    return LaunchTimingRecorder(
        "bead_work",
        {identity_field: target, "dry_run": dry_run},
        info_env_vars=(BEAD_WORK_TIMING_ENV,),
        durable=True,
    )


def handle_bead_work(args: argparse.Namespace) -> None:
    """Dispatch CLI work while preserving the original public entry point."""
    dispatch_bead_work(args, timer_factory=make_bead_work_timer)


# Compatibility aliases for callers that imported the former private helpers.
_epic_plan_source_path = epic_plan_source_path
_epic_plan_snapshot_destination = epic_plan_snapshot_destination


def _atomic_copy_epic_plan(source: Path, destination: Path) -> None:
    """Compatibility wrapper for atomic approved-plan copies."""
    atomic_copy_epic_plan(source, destination)


def _snapshot_epic_plan(
    proj: BeadProject,
    epic_id: str,
    *,
    plan_ref: str,
    launch_context: VCSLaunchContext | None,
) -> str | None:
    """Compatibility wrapper for approved-plan snapshot storage."""
    return snapshot_epic_plan(
        proj,
        epic_id,
        plan_ref=plan_ref,
        launch_context=launch_context,
        copy_plan=_atomic_copy_epic_plan,
    )


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
) -> _EpicWorkResult:
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
            )

    if not dry_run:
        preload_launch_imports(timer)

    from sase.bead.work import (
        EpicPlanError,
        build_epic_work_plan_from_beads_dir,
        epic_work_segment_env,
        render_multi_prompt,
    )
    from sase.bead.xprompts import (
        BeadXPromptNotFoundError,
        resolve_land_epic_xprompt,
        resolve_work_phase_xprompt,
    )

    with timer.stage("xprompt_lookup"):
        try:
            work_phase_xprompt = resolve_work_phase_xprompt()
            land_epic_xprompt = resolve_land_epic_xprompt()
        except (BeadXPromptNotFoundError, ValueError) as e:
            raise BeadWorkError(str(e)) from e

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
                patch_context = resolve_patch_launch_context(
                    changespec_name=issue.changespec_name,
                    bug_id=issue.changespec_bug_id,
                )
            except ValueError as e:
                raise BeadWorkError(str(e)) from e
        else:
            vcs_context = resolve_vcs_launch_context()

    with timer.stage("prompt_render"):
        from sase.agent.names import get_reserved_clan_names

        query = render_multi_prompt(
            plan,
            work_phase_xprompt=work_phase_xprompt,
            land_epic_xprompt=land_epic_xprompt,
            vcs_context=vcs_context,
            patch_context=patch_context,
            declare_clan=plan.epic_id not in get_reserved_clan_names(),
            extra_waits=extra_waits,
        )

    if issue.is_ready_to_work:
        print(f"Epic {epic_id} is already ready; retrying remaining non-closed phases.")
    print_work_plan_summary(epic_id, issue.title, plan)

    preview: CleanupPreview
    bead_assignees = _epic_bead_assignees(proj, plan)
    try:
        preview = preview_bead_work_launch_selection(
            query,
            slots=bead_work_slots(plan),
            directive_names=expected_agent_names(plan),
            bead_assignees=bead_assignees,
        )
    except ForcedReuseCleanupError as e:
        raise BeadWorkError(str(e)) from e
    assert preview.selection is not None
    selection = preview.selection

    if dry_run:
        render_cleanup_preview(epic_id, preview)
        render_blocked_launch_warning(len(selection.blocked_targets))
        dry_query = render_multi_prompt(
            plan,
            work_phase_xprompt=work_phase_xprompt,
            land_epic_xprompt=land_epic_xprompt,
            vcs_context=vcs_context,
            patch_context=patch_context,
            declare_clan=plan.epic_id not in get_reserved_clan_names(),
            launch_names=selection.launch_names,
            extra_waits=extra_waits,
        )
        print("\n--- Multi-prompt (dry run) ---")
        print(dry_query)
        return _EpicWorkResult(
            epic_id=epic_id,
            launch_state="dry_run",
            launched_agent_names=_ordered_selected_names(plan, selection.launch_names),
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
                return _EpicWorkResult(
                    epic_id=epic_id,
                    launch_state="declined",
                    preserved_agent_names=selection.preserved_names,
                )

    if not selection.has_launches:
        print(
            f"Epic {epic_id} already has matching active work; no new agents "
            "were launched."
        )
        return _EpicWorkResult(
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
            return _EpicWorkResult(
                epic_id=epic_id,
                launch_state="declined",
                preserved_agent_names=selection.preserved_names,
            )

    with timer.stage("force_reuse_cleanup"):
        try:
            bead_assignees = _epic_bead_assignees(proj, plan)
            selection = revalidate_bead_work_launch_selection(
                selection,
                bead_assignees=bead_assignees,
            )
            if not selection.has_launches:
                print(
                    f"Epic {epic_id} already has matching active work; no new "
                    "agents were launched."
                )
                return _EpicWorkResult(
                    epic_id=epic_id,
                    launch_state="already_running",
                    preserved_agent_names=selection.preserved_names,
                )
            query = render_multi_prompt(
                plan,
                work_phase_xprompt=work_phase_xprompt,
                land_epic_xprompt=land_epic_xprompt,
                vcs_context=vcs_context,
                patch_context=patch_context,
                declare_clan=plan.epic_id not in get_reserved_clan_names(),
                launch_names=selection.launch_names,
                extra_waits=extra_waits,
            )
            query = prepare_selected_bead_work_force_reuse(
                query,
                selection=selection,
                bead_assignees=bead_assignees,
            )
        except ForcedReuseCleanupError as e:
            raise BeadWorkError(str(e)) from e

    with timer.stage("plan_snapshot"):
        plan_snapshot = _snapshot_epic_plan(
            proj,
            epic_id,
            plan_ref=issue.design,
            launch_context=patch_context or vcs_context,
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
                    resume_command=f"sase bead work {epic_id}",
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
                resume_command=f"sase bead work {epic_id}",
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

    graph_published = False
    graph_relocations: tuple[Any, ...] = ()
    try:
        with timer.stage("graph_publication"):
            if before_agent_launch is not None:
                callback_result = before_agent_launch(proj, epic_id)
                graph_relocations = tuple(
                    getattr(callback_result, "bead_relocations", ())
                )
            else:
                try:
                    checkpoint_result = checkpoint_epic_work_launch(
                        proj.beads_dir,
                        epic_id,
                        no_push=no_push or defer_push,
                        timer=timer,
                    )
                    graph_relocations = tuple(
                        getattr(checkpoint_result, "bead_relocations", ())
                    )
                except EpicLaunchCheckpointError as exc:
                    raise BeadWorkError(
                        str(exc),
                        preserve_epic_state=exc.checkpoint_created,
                        retry_requires_push=exc.retry_requires_push,
                    ) from exc
        graph_published = True
    except BeadWorkError as exc:
        if not exc.preserve_epic_state:
            rollback_work_launch(
                proj,
                epic_id,
                marked_ready_this_run=marked_ready_this_run,
                rollback_preclaims=rollback_preclaims,
                no_push=True,
            )
        raise
    except Exception as exc:
        rollback_work_launch(
            proj,
            epic_id,
            marked_ready_this_run=marked_ready_this_run,
            rollback_preclaims=rollback_preclaims,
            no_push=True,
        )
        raise BeadWorkError(
            f"epic graph publication failed before agent launch for {epic_id}: {exc}"
        ) from exc

    if graph_relocations:
        from sase.bead.relocation import (
            resolve_created_bead_id,
            rewrite_text_for_bead_relocations,
        )

        epic_id = resolve_created_bead_id(epic_id, graph_relocations)
        query = rewrite_text_for_bead_relocations(query, graph_relocations)

    try:
        with timer.stage("agent_launch"):
            segment_env = epic_work_segment_env(
                plan,
                plan_ref=issue.design,
                plan_snapshot=plan_snapshot,
                launch_names=selection.launch_names,
            )
            if graph_relocations:
                segment_env = tuple(
                    {
                        key: (
                            rewrite_text_for_bead_relocations(value, graph_relocations)
                            if isinstance(value, str)
                            else value
                        )
                        for key, value in segment.items()
                    }
                    for segment in segment_env
                )
            results = launch_bead_work_agents(
                query,
                segment_extra_env=segment_env,
                expected_names=set(selection.launch_names),
                launch_context=patch_context or vcs_context,
            )
    except Exception as e:
        launched_results = list(getattr(e, "results", []))
        launched_pids = [r.pid for r in launched_results]
        rollback_work_launch(
            proj,
            epic_id,
            marked_ready_this_run=marked_ready_this_run,
            rollback_preclaims=rollback_preclaims,
            no_push=no_push or defer_push,
            launched_pids=launched_pids,
            launched_results=launched_results,
        )
        raise BeadWorkError(
            f"agent launch failed for epic {epic_id}: {e}\n"
            "For broader diagnostics, run `sase doctor -v`.",
            agents_spawned=bool(launched_results or launched_pids),
            graph_published=graph_published,
        ) from e

    agent_count = len(selection.launch_names)
    preserved_count = len(selection.preserved_names)
    preserved_text = (
        f"; preserved {preserved_count} existing" if preserved_count else ""
    )
    print(
        f"✓ Launched {agent_count} agents for epic {epic_id} — {issue.title} "
        f"(workspace {results[0].workspace_num}{preserved_text})"
    )
    return _EpicWorkResult(
        epic_id=epic_id,
        launch_state="launched",
        launched_agent_names=_ordered_selected_names(plan, selection.launch_names),
        preserved_agent_names=selection.preserved_names,
        workspace_num=results[0].workspace_num,
    )


def _epic_bead_assignees(proj: BeadProject, plan: Any) -> dict[str, str]:
    bead_ids = {plan.epic_id, *plan.phase_bead_ids}
    assignees: dict[str, str] = {}
    for bead_id in bead_ids:
        try:
            assignees[bead_id] = proj.show(bead_id).assignee
        except KeyError:
            assignees[bead_id] = ""
    return assignees


def _ordered_selected_names(plan: Any, launch_names: frozenset[str]) -> tuple[str, ...]:
    ordered = [
        assignment.agent_name
        for wave in plan.waves
        for assignment in wave
        if assignment.agent_name in launch_names
    ]
    if plan.land_agent_name in launch_names:
        ordered.append(plan.land_agent_name)
    return tuple(ordered)


def preload_launch_imports(timer: LaunchTimingRecorder) -> None:
    """Eagerly import the deferred launch chain once code-swap lock is held."""
    if getattr(timer, "_sase_preloaded_launch_imports", False):
        return
    timer._sase_preloaded_launch_imports = True  # type: ignore[attr-defined]
    with timer.stage("preload_launch_imports"):
        import sase.ace.tui.actions.agent_workflow._ref_resolution  # noqa: F401
        import sase.agent.launcher  # noqa: F401


# Compatibility alias for callers/tests that imported the former private helper.
_handle_epic_bead_work = launch_epic_bead_work
