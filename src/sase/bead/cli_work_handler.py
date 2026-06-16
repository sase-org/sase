"""Top-level orchestration for ``sase bead work``."""

from __future__ import annotations

import argparse
import sys
from typing import TYPE_CHECKING, Any

from sase.bead.cli_common import get_project
from sase.bead.cli_work_cleanup import (
    ForcedReuseCleanupError,
    prepare_bead_work_force_reuse,
    rollback_legend_work_launch,
    rollback_work_launch,
    warn_force_reuse_collisions,
)
from sase.bead.cli_work_commit import commit_successful_work_launch
from sase.bead.cli_work_context import (
    resolve_vcs_launch_context,
    resolve_changespec_launch_context,
)
from sase.bead.cli_work_launch import launch_bead_work_agents
from sase.bead.cli_work_plan import (
    confirm_launch,
    expected_agent_names,
    expected_legend_agent_names,
    find_live_legend_name_collisions,
    find_live_name_collisions,
    legacy_epic_cleanup_names,
    print_legend_work_plan_summary,
    print_work_plan_summary,
)
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.work import (
        ChangeSpecLaunchContext,
        VCSLaunchContext,
    )


BEAD_WORK_TIMING_ENV = "SASE_BEAD_WORK_TIMING"


def _make_bead_work_timer(bead_id: str, *, dry_run: bool) -> Any:
    """Build a launch timer promoted to info logs by ``SASE_BEAD_WORK_TIMING``."""
    from sase.agent.launch_timing import LaunchTimingRecorder

    return LaunchTimingRecorder(
        "bead_work",
        {"bead_id": bead_id, "dry_run": dry_run},
        info_env_vars=(BEAD_WORK_TIMING_ENV,),
    )


def handle_bead_work(args: argparse.Namespace) -> None:
    import contextlib

    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    no_push = bool(getattr(args, "no_push", False))

    timer = _make_bead_work_timer(args.id, dry_run=dry_run)
    with timer, contextlib.ExitStack() as stack:
        with timer.stage("project_open"):
            proj = stack.enter_context(get_project())
        with timer.stage("initial_show"):
            try:
                issue = proj.show(args.id)
            except KeyError:
                print(f"Error: issue not found: {args.id}", file=sys.stderr)
                sys.exit(1)
        if issue.issue_type != IssueType.PLAN:
            print(
                f"Error: is_ready_to_work only applies to plan beads "
                f"(got {issue.issue_type.value} for {args.id})",
                file=sys.stderr,
            )
            sys.exit(1)
        if issue.tier == BeadTier.EPIC:
            _handle_epic_bead_work(
                proj, args.id, dry_run=dry_run, yes=yes, no_push=no_push, timer=timer
            )
            return
        if issue.tier == BeadTier.LEGEND:
            _handle_legend_bead_work(
                proj, args.id, dry_run=dry_run, yes=yes, no_push=no_push, timer=timer
            )
            return

        tier = issue.tier.value if issue.tier else "missing tier"
        print(
            "Error: sase bead work only applies to epic or legend plan beads "
            f"(got {tier} for {args.id})",
            file=sys.stderr,
        )
        sys.exit(1)


def _handle_epic_bead_work(
    proj: BeadProject,
    epic_id: str,
    *,
    dry_run: bool,
    yes: bool,
    no_push: bool,
    timer: LaunchTimingRecorder,
) -> None:
    from sase.bead.work import (
        ChangeSpecLaunchContext,
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
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    issue = proj.show(epic_id)
    with timer.stage("work_plan_build"):
        try:
            plan = build_epic_work_plan_from_beads_dir(proj.beads_dir, epic_id)
        except EpicPlanError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

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
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
        else:
            vcs_context = resolve_vcs_launch_context()

    with timer.stage("prompt_render"):
        query = render_multi_prompt(
            plan,
            work_phase_xprompt=work_phase_xprompt,
            land_epic_xprompt=land_epic_xprompt,
            vcs_context=vcs_context,
            changespec_context=changespec_context,
        )

    if issue.is_ready_to_work:
        print(f"Epic {epic_id} is already ready; retrying remaining non-closed phases.")
    print_work_plan_summary(epic_id, issue.title, plan)

    if dry_run:
        warn_force_reuse_collisions(find_live_name_collisions(plan))
        print("\n--- Multi-prompt (dry run) ---")
        print(query)
        return

    if not yes and not confirm_launch():
        print("Aborted.")
        return

    with timer.stage("force_reuse_cleanup"):
        try:
            query = prepare_bead_work_force_reuse(
                query,
                expected_names=expected_agent_names(plan),
                extra_cleanup_names=legacy_epic_cleanup_names(plan),
            )
        except ForcedReuseCleanupError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    marked_ready_this_run = False
    if not issue.is_ready_to_work:
        with timer.stage("mark_ready"):
            try:
                proj.mark_ready_to_work(epic_id)
                marked_ready_this_run = True
            except AlreadyReadyError:
                marked_ready_this_run = False
            except (KeyError, NotAPlanError) as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

    claimed: list[tuple[str, Status, str]] = []
    with timer.stage("preclaim"):
        try:
            claimed = proj.preclaim_epic_work(
                epic_id,
                [
                    (assignment.bead_id, assignment.agent_name)
                    for wave in plan.waves
                    for assignment in wave
                ],
            )
        except (KeyError, ValueError) as e:
            print(f"Error: pre-claim failed for epic {epic_id}: {e}", file=sys.stderr)
            rollback_work_launch(
                proj, epic_id, claimed, unmark_ready=marked_ready_this_run
            )
            sys.exit(1)

    try:
        with timer.stage("agent_launch"):
            results = launch_bead_work_agents(
                query,
                segment_extra_env=epic_work_segment_env(plan),
                expected_names=expected_agent_names(plan),
                launch_context=changespec_context or vcs_context,
            )
    except Exception as e:
        print(
            f"Error: agent launch failed for epic {epic_id}: {e}\n"
            "For broader diagnostics, run `sase doctor -v`.",
            file=sys.stderr,
        )
        launched_pids = [r.pid for r in getattr(e, "results", [])]
        rollback_work_launch(
            proj,
            epic_id,
            claimed,
            unmark_ready=marked_ready_this_run,
            launched_pids=launched_pids,
        )
        sys.exit(1)

    agent_count = sum(len(w) for w in plan.waves) + 1
    print(
        f"✓ Launched {agent_count} agents for epic {epic_id} — {issue.title} "
        f"(workspace {results[0].workspace_num})"
    )
    commit_successful_work_launch(
        proj.beads_dir,
        epic_id,
        issue.title,
        kind="epic",
        no_push=no_push,
        timer=timer,
    )


def _handle_legend_bead_work(
    proj: BeadProject,
    legend_id: str,
    *,
    dry_run: bool,
    yes: bool,
    no_push: bool,
    timer: LaunchTimingRecorder,
) -> None:
    from sase.bead.work import (
        LegendPlanError,
        build_legend_work_plan_from_beads_dir,
        legend_work_segment_env,
        render_legend_multi_prompt,
    )
    from sase.bead.xprompts import (
        BeadXPromptNotFoundError,
        resolve_land_legend_xprompt,
    )

    with timer.stage("xprompt_lookup"):
        try:
            land_legend_xprompt = resolve_land_legend_xprompt()
        except (BeadXPromptNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    issue = proj.show(legend_id)
    with timer.stage("work_plan_build"):
        try:
            plan = build_legend_work_plan_from_beads_dir(proj.beads_dir, legend_id)
        except LegendPlanError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    with timer.stage("vcs_context"):
        vcs_context = resolve_vcs_launch_context()

    with timer.stage("prompt_render"):
        query = render_legend_multi_prompt(
            plan,
            land_legend_xprompt=land_legend_xprompt,
            vcs_context=vcs_context,
        )

    if issue.is_ready_to_work:
        print(f"Legend {legend_id} is already ready; retrying epic agent launch.")
    print_legend_work_plan_summary(legend_id, issue.title, plan)

    if dry_run:
        warn_force_reuse_collisions(find_live_legend_name_collisions(plan))
        print("\n--- Multi-prompt (dry run) ---")
        print(query)
        return

    if not yes and not confirm_launch():
        print("Aborted.")
        return

    with timer.stage("force_reuse_cleanup"):
        try:
            query = prepare_bead_work_force_reuse(
                query,
                expected_names=expected_legend_agent_names(plan),
            )
        except ForcedReuseCleanupError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    marked_ready_this_run = False
    if not issue.is_ready_to_work:
        with timer.stage("mark_ready"):
            try:
                proj.mark_ready_to_work(legend_id)
                marked_ready_this_run = True
            except AlreadyReadyError:
                marked_ready_this_run = False
            except (KeyError, NotAPlanError) as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

    try:
        with timer.stage("agent_launch"):
            results = launch_bead_work_agents(
                query,
                segment_extra_env=legend_work_segment_env(plan),
                expected_names=expected_legend_agent_names(plan),
                launch_context=vcs_context,
            )
    except Exception as e:
        print(
            f"Error: agent launch failed for legend {legend_id}: {e}\n"
            "For broader diagnostics, run `sase doctor -v`.",
            file=sys.stderr,
        )
        launched_pids = [r.pid for r in getattr(e, "results", [])]
        rollback_legend_work_launch(
            proj,
            legend_id,
            unmark_ready=marked_ready_this_run,
            launched_pids=launched_pids,
        )
        sys.exit(1)

    epic_agent_count = len(plan.assignments)
    agent_count = epic_agent_count + 1
    print(
        f"✓ Launched {agent_count} agents for legend {legend_id} — "
        f"{issue.title} ({epic_agent_count} epic-planning, 1 land; "
        f"workspace {results[0].workspace_num})"
    )
    commit_successful_work_launch(
        proj.beads_dir,
        legend_id,
        issue.title,
        kind="legend",
        no_push=no_push,
        timer=timer,
    )
