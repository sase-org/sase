"""Epic work launch handler for the bead CLI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sase.bead.cli_common import get_project
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError
from sase.core.paths import sase_projects_dir

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.agent.launch_types import AgentLaunchResult
    from sase.bead.work import (
        ChangeSpecLaunchContext,
        EpicWorkPlan,
        LegendWorkPlan,
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


def _launch_bead_work_agents(
    query: str,
    *,
    segment_extra_env: tuple[dict[str, str], ...],
    expected_names: set[str],
    launch_context: VCSLaunchContext | None,
) -> list[AgentLaunchResult]:
    """Launch the rendered bead-work multi-prompt.

    When a VCS/ChangeSpec launch context was resolved (every segment carries an
    explicit ``#<workflow>:<ref>`` prefix), dispatch through the fast planned
    adapter that skips generic fan-out discovery. Otherwise fall back to the
    generic CWD launcher, which resolves project context from the workspace.
    """
    from sase.agent import launcher as _launcher

    if launch_context is None:
        return [
            _launcher.launch_agent_from_cwd(query, segment_extra_env=segment_extra_env)
        ]
    return _launcher.launch_planned_bead_work_agents(
        segments=query.split("\n---\n"),
        segment_extra_env=segment_extra_env,
        expected_names=expected_names,
        project_name=launch_context.project_name,
    )


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
            vcs_context = _resolve_vcs_launch_context()

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
        _warn_force_reuse_collisions(find_live_name_collisions(plan))
        print("\n--- Multi-prompt (dry run) ---")
        print(query)
        return

    if not yes and not confirm_launch():
        print("Aborted.")
        return

    with timer.stage("force_reuse_cleanup"):
        try:
            query = _prepare_bead_work_force_reuse(
                query,
                expected_names=expected_agent_names(plan),
                extra_cleanup_names=_legacy_epic_cleanup_names(plan),
            )
        except _ForcedReuseCleanupError as e:
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
            results = _launch_bead_work_agents(
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
    _commit_successful_work_launch(
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
        vcs_context = _resolve_vcs_launch_context()

    with timer.stage("prompt_render"):
        query = render_legend_multi_prompt(
            plan,
            land_legend_xprompt=land_legend_xprompt,
            vcs_context=vcs_context,
        )

    if issue.is_ready_to_work:
        print(f"Legend {legend_id} is already ready; retrying epic agent launch.")
    _print_legend_work_plan_summary(legend_id, issue.title, plan)

    if dry_run:
        _warn_force_reuse_collisions(_find_live_legend_name_collisions(plan))
        print("\n--- Multi-prompt (dry run) ---")
        print(query)
        return

    if not yes and not confirm_launch():
        print("Aborted.")
        return

    with timer.stage("force_reuse_cleanup"):
        try:
            query = _prepare_bead_work_force_reuse(
                query,
                expected_names=_expected_legend_agent_names(plan),
            )
        except _ForcedReuseCleanupError as e:
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
            results = _launch_bead_work_agents(
                query,
                segment_extra_env=legend_work_segment_env(plan),
                expected_names=_expected_legend_agent_names(plan),
                launch_context=vcs_context,
            )
    except Exception as e:
        print(
            f"Error: agent launch failed for legend {legend_id}: {e}\n"
            "For broader diagnostics, run `sase doctor -v`.",
            file=sys.stderr,
        )
        launched_pids = [r.pid for r in getattr(e, "results", [])]
        _rollback_legend_work_launch(
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
    _commit_successful_work_launch(
        proj.beads_dir,
        legend_id,
        issue.title,
        kind="legend",
        no_push=no_push,
        timer=timer,
    )


def resolve_changespec_launch_context(
    *,
    changespec_name: str,
    bug_id: str,
) -> ChangeSpecLaunchContext:
    """Resolve VCS/project context for a ChangeSpec-attached epic launch."""
    from sase.bead.work import ChangeSpecLaunchContext

    vcs_context = _resolve_required_vcs_launch_context(
        purpose="ChangeSpec-attached epic"
    )

    return ChangeSpecLaunchContext(
        changespec_name=changespec_name,
        bug_id=bug_id,
        vcs_workflow=vcs_context.vcs_workflow,
        project_name=vcs_context.project_name,
    )


def _resolve_vcs_launch_context() -> VCSLaunchContext | None:
    """Best-effort VCS/project context for regular epic launches."""
    try:
        return _resolve_required_vcs_launch_context(purpose="regular epic")
    except ValueError:
        return None


def _resolve_required_vcs_launch_context(*, purpose: str) -> VCSLaunchContext:
    """Resolve current project/workflow context or raise a purpose-specific error."""
    from sase.bead.project_name import infer_project_name_from_cwd
    from sase.bead.work import VCSLaunchContext
    from sase.workspace_provider import detect_workflow_type

    project_name = infer_project_name_from_cwd()
    if not project_name:
        raise ValueError(
            f"cannot launch {purpose}: unable to infer the current SASE "
            "project from this workspace"
        )

    from sase.ace.changespec.project_spec_path import preferred_project_spec_path

    project_dir = sase_projects_dir() / project_name
    project_file = Path(preferred_project_spec_path(str(project_dir), project_name))
    if not project_file.exists():
        raise ValueError(
            f"cannot launch {purpose}: project file not found at {project_file}"
        )

    try:
        vcs_workflow = detect_workflow_type(str(project_file))
    except ValueError as exc:
        raise ValueError(
            f"cannot launch {purpose}: unable to detect VCS workflow for "
            f"{project_file}: {exc}"
        ) from exc

    return VCSLaunchContext(vcs_workflow=vcs_workflow, project_name=project_name)


def expected_agent_names(plan: EpicWorkPlan) -> set[str]:
    names = {a.agent_name for wave in plan.waves for a in wave}
    names.add(plan.land_agent_name)
    return names


def _legacy_land_agent_name(plan: EpicWorkPlan) -> str | None:
    name = f"{plan.epic_id}.land"
    if name == plan.land_agent_name:
        return None
    return name


def _legacy_epic_cleanup_names(plan: EpicWorkPlan) -> frozenset[str]:
    """Return legacy deterministic owners to wipe that the prompt no longer names.

    Epic land agents now reuse ``<epic_id>``; older runs used ``<epic_id>.land``.
    The legacy name is not rendered in the new prompt, so it is an extra wipe
    target rather than an expected ``%name:!`` directive.
    """
    legacy = _legacy_land_agent_name(plan)
    return frozenset({legacy}) if legacy else frozenset()


def find_live_name_collisions(plan: EpicWorkPlan) -> dict[str, str]:
    """Return ``{agent_name: artifact_dir}`` for plan names owned by live agents."""
    from sase.agent.names import get_live_agent_name_subset

    expected = expected_agent_names(plan)
    legacy_land_name = _legacy_land_agent_name(plan)
    if legacy_land_name:
        expected.add(legacy_land_name)
    return get_live_agent_name_subset(expected)


def _expected_legend_agent_names(plan: LegendWorkPlan) -> set[str]:
    names = {assignment.agent_name for assignment in plan.assignments}
    names.add(plan.land_agent_name)
    return names


def _find_live_legend_name_collisions(plan: LegendWorkPlan) -> dict[str, str]:
    """Return live collisions for legend epic-planning agent names."""
    from sase.agent.names import get_live_agent_name_subset

    expected = _expected_legend_agent_names(plan)
    return get_live_agent_name_subset(expected)


def print_work_plan_summary(epic_id: str, title: str, plan: EpicWorkPlan) -> None:
    phase_count = sum(len(w) for w in plan.waves)
    wave_count = len(plan.waves)
    print(
        f"Epic {epic_id} — {title}: {phase_count} phase agent(s) in "
        f"{wave_count} wave(s) plus 1 land agent ({plan.land_agent_name})."
    )
    for i, wave in enumerate(plan.waves):
        names = ", ".join(f"{a.bead_id} → {a.agent_name}" for a in wave)
        print(f"  Wave {i}: {names}")
    if plan.land_waits_on:
        print(f"  Land waits on: {', '.join(plan.land_waits_on)}")


def _print_legend_work_plan_summary(
    legend_id: str,
    title: str,
    plan: LegendWorkPlan,
) -> None:
    agent_count = len(plan.assignments)
    print(
        f"Legend {legend_id} — {title}: {agent_count} epic agent(s) plus "
        f"1 land agent ({plan.land_agent_name})."
    )
    for assignment in plan.assignments:
        print(f"  Epic #{assignment.epic_number}: {assignment.agent_name}")
    wait_edges = [
        f"{assignment.agent_name} waits on {', '.join(assignment.waits_on)}"
        for assignment in plan.assignments
        if assignment.waits_on
    ]
    if wait_edges:
        print(f"  Wait chain: {'; '.join(wait_edges)}")
    if plan.land_waits_on:
        print(f"  Land waits on: {', '.join(plan.land_waits_on)}")


def confirm_launch() -> bool:
    answer = input("Launch these agents? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _resolve_push_mode(no_push: bool) -> str:
    """Resolve the post-commit push mode: ``"sync"``, ``"async"`` or ``"off"``.

    ``--no-push`` always wins. Otherwise ``bead.push_after_commit`` selects the
    behavior: ``true`` (default) pushes synchronously, ``false`` skips the push,
    and ``async`` launches a detached push helper so the command returns without
    waiting on remote network/credential latency. Unknown string values fall
    back to the conservative synchronous push.
    """
    if no_push:
        return "off"

    from sase.config import load_merged_config

    raw = load_merged_config().get("bead", {}).get("push_after_commit", True)
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized == "async":
            return "async"
        if normalized in {"false", "no", "off", "0"}:
            return "off"
        return "sync"
    return "sync" if bool(raw) else "off"


def _commit_successful_work_launch(
    beads_dir: Path,
    bead_id: str,
    title: str,
    *,
    kind: str,
    no_push: bool,
    timer: LaunchTimingRecorder,
) -> None:
    from sase.bead.sync import (
        BeadWorkLaunchCommitError,
        commit_bead_work_launch,
        push_bead_work_launch,
        push_bead_work_launch_async,
    )

    with timer.stage("commit"):
        try:
            committed = commit_bead_work_launch(beads_dir, bead_id, title, kind=kind)
        except BeadWorkLaunchCommitError as exc:
            print(
                f"Error: agents launched for {kind} {bead_id}, but committing "
                f"bead state failed: {exc}",
                file=sys.stderr,
            )
            sys.exit(1)

    if not committed:
        return

    push_mode = _resolve_push_mode(no_push)
    suffix = ""
    with timer.stage("push", mode=push_mode):
        if push_mode == "sync":
            outcome = push_bead_work_launch(beads_dir)
            if outcome.pushed:
                suffix = " Pushed to remote."
            elif outcome.error is not None:
                print(
                    f"Warning: committed bead state for {kind} {bead_id}, "
                    f"but {outcome.error}. Push manually with "
                    f"`cd {beads_dir.parent.parent} && git push`.",
                    file=sys.stderr,
                )
        elif push_mode == "async":
            handle = push_bead_work_launch_async(beads_dir)
            if handle is not None:
                suffix = (
                    f" Pushing to remote in the background (pid {handle.pid}); "
                    f"output logged to {handle.log_path}."
                )
    print(f"Committed bead state for {kind} {bead_id}.{suffix}")


def rollback_work_launch(
    proj: BeadProject,
    epic_id: str,
    claimed: list[tuple[str, Status, str]],
    *,
    unmark_ready: bool,
    launched_pids: list[int] | None = None,
) -> None:
    """Best-effort: terminate already-spawned agents and revert pre-claims."""
    if launched_pids:
        import signal

        for pid in launched_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError) as exc:
                print(
                    f"Warning: failed to terminate partially-launched pid {pid}: {exc}",
                    file=sys.stderr,
                )

    target = "pre-claims and is_ready_to_work flag" if unmark_ready else "pre-claims"
    print(
        f"Rolling back {target}. If rollback also fails, fix the affected "
        "bead status/assignee fields manually.",
        file=sys.stderr,
    )
    for bead_id, prior_status, prior_assignee in reversed(claimed):
        try:
            proj.update(
                bead_id,
                status=prior_status.value,
                assignee=prior_assignee,
            )
        except Exception as exc:  # noqa: BLE001
            print(
                f"Warning: failed to roll back pre-claim on {bead_id}: {exc}",
                file=sys.stderr,
            )
    if unmark_ready:
        try:
            proj.unmark_ready_to_work(epic_id)
        except Exception as exc:  # noqa: BLE001
            print(
                f"Warning: failed to roll back is_ready_to_work on {epic_id}: {exc}",
                file=sys.stderr,
            )


class _ForcedReuseCleanupError(RuntimeError):
    """Raised when forced bead-work name reuse cleanup cannot be completed."""


def _warn_force_reuse_collisions(collisions: dict[str, str]) -> None:
    """Warn (for ``--dry-run``) which live agents a real launch would replace."""
    if not collisions:
        return
    print(
        "\nWarning: these live agents would be force-reused (terminated) "
        "on a live launch:",
        file=sys.stderr,
    )
    for name, path in sorted(collisions.items()):
        print(f"  {name} (already running at {path})", file=sys.stderr)


def _prepare_bead_work_force_reuse(
    query: str,
    *,
    expected_names: set[str],
    extra_cleanup_names: frozenset[str] = frozenset(),
) -> str:
    """Wipe deterministic bead-work owners and rewrite the prompt for the launcher.

    Bead work is a trusted, confirmed relaunch surface: it deliberately reuses
    the deterministic phase/land names it just computed. This parses the
    ``%name:!<n>`` directives out of *query*, verifies they match the plan's
    *expected_names*, then wipes each owner (plus any *extra_cleanup_names* such
    as a legacy land owner that the new prompt no longer names). Old owners are
    replaced regardless of state — completed, dismissed, or still live (the wipe
    terminates live owners).

    Unlike a best-effort wipe, this fails *before* the caller performs any bead
    mutation: it raises :class:`_ForcedReuseCleanupError` when a wipe raises, when
    an :class:`AgentNameWipeResult` reports errors, or when the registry still
    reports an owner for a force-reused name after the rebuild. On success it
    rewrites ``%name:!<n>`` to ordinary ``%name:<n>`` so
    ``validate_launch_name_requests`` accepts the prompt.
    """
    from sase.agent.launch_validation import (
        force_reuse_owner_names,
        rewrite_force_reuse_name_directives,
    )

    segments = query.split("\n---\n")
    directive_names = force_reuse_owner_names(segments)
    if set(directive_names) != set(expected_names):
        raise _ForcedReuseCleanupError(
            "rendered bead-work prompt force-reuse names "
            f"{sorted(directive_names)} do not match the planned agent names "
            f"{sorted(expected_names)}; aborting forced reuse cleanup"
        )

    cleanup_order = list(directive_names)
    cleanup_order.extend(
        name for name in sorted(extra_cleanup_names) if name not in directive_names
    )
    for name in cleanup_order:
        _wipe_force_reuse_owner(name)
    return rewrite_force_reuse_name_directives(query)


def _wipe_force_reuse_owner(name: str) -> None:
    """Wipe a single deterministic owner, raising on any cleanup failure."""
    from sase.agent.names import wipe_agent_name_for_reuse

    try:
        result = wipe_agent_name_for_reuse(name)
    except Exception as exc:  # noqa: BLE001
        raise _ForcedReuseCleanupError(
            f"forced reuse cleanup for agent name '{name}' failed: {exc}"
        ) from exc
    if result.errors:
        raise _ForcedReuseCleanupError(
            f"forced reuse cleanup for agent name '{name}' reported errors: "
            + "; ".join(result.errors)
        )
    if result.found and name not in result.registry_names_removed:
        raise _ForcedReuseCleanupError(
            f"forced reuse cleanup left agent name '{name}' reserved after "
            "rebuild; resolve the conflicting owner and retry"
        )


def _rollback_legend_work_launch(
    proj: BeadProject,
    legend_id: str,
    *,
    unmark_ready: bool,
    launched_pids: list[int] | None = None,
) -> None:
    """Best-effort: terminate already-spawned agents and revert legend readiness."""
    if launched_pids:
        import signal

        for pid in launched_pids:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError, OSError) as exc:
                print(
                    f"Warning: failed to terminate partially-launched pid {pid}: {exc}",
                    file=sys.stderr,
                )

    if not unmark_ready:
        return

    print(
        "Rolling back is_ready_to_work flag. If rollback also fails, fix the "
        "legend bead manually.",
        file=sys.stderr,
    )
    try:
        proj.unmark_ready_to_work(legend_id)
    except Exception as exc:  # noqa: BLE001
        print(
            f"Warning: failed to roll back is_ready_to_work on {legend_id}: {exc}",
            file=sys.stderr,
        )
