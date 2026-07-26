"""Epic launch orchestration and compatibility helpers for ``sase bead work``."""

from __future__ import annotations

import argparse
from pathlib import Path
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from sase.bead.cli_work_cleanup import (
    CleanupPreview,
    ForcedReuseCleanupError,
    prepare_bead_work_force_reuse,
    preview_bead_work_force_reuse,
    rollback_work_launch,
)
from sase.bead.cli_work_commit import commit_successful_work_launch
from sase.bead.cli_work_context import (
    resolve_vcs_launch_context,
    resolve_changespec_launch_context,
)
from sase.bead.cli_work_launch import launch_bead_work_agents
from sase.bead.cli_work_plan import (
    confirm_cleanup,
    confirm_launch,
    expected_agent_names,
    legacy_epic_cleanup_names,
    print_work_plan_summary,
    render_cleanup_preview,
)
from sase.bead.cli_work_plan_snapshot import (
    atomic_copy_epic_plan,
    epic_plan_snapshot_destination,
    epic_plan_source_path,
    plan_ref_after_marker,
    snapshot_epic_plan,
)
from sase.bead.cli_work_entry import handle_bead_work as dispatch_bead_work
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.work import (
        ChangeSpecLaunchContext,
        VCSLaunchContext,
    )


BEAD_WORK_TIMING_ENV = "SASE_BEAD_WORK_TIMING"


class BeadWorkError(RuntimeError):
    """A recoverable ``sase bead work`` orchestration failure.

    ``agents_spawned`` records that at least one runner crossed the spawn
    boundary, so plan-file callers must preserve the recoverable epic state.
    ``agents_launched`` distinguishes failures after every requested agent was
    successfully started (currently the final bead-state commit).

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


def _post_launch_commit_error(
    epic_id: str,
    exc: Exception,
    *,
    graph_published: bool,
) -> BeadWorkError:
    return BeadWorkError(
        f"agents launched for epic {epic_id}, but committing bead state failed: {exc}",
        agents_launched=True,
        graph_published=graph_published,
    )


def _make_bead_work_timer(bead_id: str, *, dry_run: bool) -> Any:
    """Build a launch timer promoted to info logs by ``SASE_BEAD_WORK_TIMING``."""
    from sase.agent.launch_timing import LaunchTimingRecorder

    return LaunchTimingRecorder(
        "bead_work",
        {"bead_id": bead_id, "dry_run": dry_run},
        info_env_vars=(BEAD_WORK_TIMING_ENV,),
    )


def handle_bead_work(args: argparse.Namespace) -> None:
    """Dispatch CLI work while preserving the original public entry point."""
    dispatch_bead_work(args, timer_factory=_make_bead_work_timer)


# Compatibility aliases for callers that imported the former private helpers.
_epic_plan_source_path = epic_plan_source_path
_plan_ref_after_marker = plan_ref_after_marker
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
    before_agent_launch: Callable[[BeadProject, str], None] | None = None,
    timer: LaunchTimingRecorder | None = None,
) -> bool:
    """Run the epic bead-work path, returning whether agents were launched.

    This is the library entry point used both by the CLI and deterministic
    epic approval. It raises :class:`BeadWorkError` instead of terminating the
    process so host-side callers can roll back newly-created epic beads.
    """
    if timer is None:
        owned_timer = _make_bead_work_timer(epic_id, dry_run=dry_run)
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
            )

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
    changespec_context: ChangeSpecLaunchContext | None = None
    with timer.stage("vcs_context"):
        if issue.changespec_name:
            try:
                changespec_context = resolve_changespec_launch_context(
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
            changespec_context=changespec_context,
            declare_clan=plan.epic_id not in get_reserved_clan_names(),
        )

    if issue.is_ready_to_work:
        print(f"Epic {epic_id} is already ready; retrying remaining non-closed phases.")
    print_work_plan_summary(epic_id, issue.title, plan)

    preview: CleanupPreview
    try:
        preview = preview_bead_work_force_reuse(
            query,
            expected_names=expected_agent_names(plan),
            extra_cleanup_names=legacy_epic_cleanup_names(plan),
        )
    except ForcedReuseCleanupError as e:
        raise BeadWorkError(str(e)) from e

    if dry_run:
        render_cleanup_preview(epic_id, preview)
        print("\n--- Multi-prompt (dry run) ---")
        print(query)
        return False

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
                return False

    if not (yes or yes_to_all):
        launch_confirmation = confirm_launch()
        if launch_confirmation is None:
            raise BeadWorkError(
                "refusing agent launch with non-interactive stdin; re-run with "
                "--yes (or --yes-to-all) to proceed non-interactively"
            )
        if not launch_confirmation:
            print("Aborted.")
            return False

    with timer.stage("force_reuse_cleanup"):
        try:
            query = prepare_bead_work_force_reuse(
                query,
                expected_names=expected_agent_names(plan),
                extra_cleanup_names=legacy_epic_cleanup_names(plan),
            )
        except ForcedReuseCleanupError as e:
            raise BeadWorkError(str(e)) from e

    with timer.stage("plan_snapshot"):
        plan_snapshot = _snapshot_epic_plan(
            proj,
            epic_id,
            plan_ref=issue.design,
            launch_context=changespec_context or vcs_context,
        )

    marked_ready_this_run = False
    if not issue.is_ready_to_work:
        with timer.stage("mark_ready"):
            try:
                proj.mark_ready_to_work(epic_id)
                marked_ready_this_run = True
            except AlreadyReadyError:
                marked_ready_this_run = False
            except (KeyError, NotAPlanError) as e:
                raise BeadWorkError(str(e)) from e

    graph_published = False
    if before_agent_launch is not None:
        try:
            with timer.stage("graph_publication"):
                before_agent_launch(proj, epic_id)
            graph_published = True
        except BeadWorkError as exc:
            if marked_ready_this_run and not exc.preserve_epic_state:
                rollback_work_launch(
                    proj,
                    epic_id,
                    marked_ready_this_run=True,
                    no_push=True,
                )
            raise
        except Exception as exc:
            if marked_ready_this_run:
                rollback_work_launch(
                    proj,
                    epic_id,
                    marked_ready_this_run=True,
                    no_push=True,
                )
            raise BeadWorkError(
                f"epic graph publication failed before agent launch for "
                f"{epic_id}: {exc}"
            ) from exc

    try:
        with timer.stage("agent_launch"):
            results = launch_bead_work_agents(
                query,
                segment_extra_env=epic_work_segment_env(
                    plan,
                    plan_ref=issue.design,
                    plan_snapshot=plan_snapshot,
                ),
                expected_names=expected_agent_names(plan),
                launch_context=changespec_context or vcs_context,
            )
    except Exception as e:
        launched_results = list(getattr(e, "results", []))
        launched_pids = [r.pid for r in launched_results]
        rollback_work_launch(
            proj,
            epic_id,
            marked_ready_this_run=marked_ready_this_run,
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

    agent_count = sum(len(w) for w in plan.waves) + 1
    print(
        f"✓ Launched {agent_count} agents for epic {epic_id} — {issue.title} "
        f"(workspace {results[0].workspace_num})"
    )
    try:
        commit_successful_work_launch(
            proj.beads_dir,
            epic_id,
            kind="epic",
            no_push=no_push or defer_push,
            timer=timer,
        )
    except Exception as exc:
        raise _post_launch_commit_error(
            epic_id,
            exc,
            graph_published=graph_published,
        ) from exc
    return True


# Compatibility alias for callers/tests that imported the former private helper.
_handle_epic_bead_work = launch_epic_bead_work
