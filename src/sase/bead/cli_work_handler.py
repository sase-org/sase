"""Top-level orchestration for ``sase bead work``."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from typing import TYPE_CHECKING, Any

from sase.bead.cli_common import get_project
from sase.bead.cli_work_cleanup import (
    ForcedReuseCleanupError,
    prepare_bead_work_force_reuse,
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
    find_live_name_collisions,
    legacy_epic_cleanup_names,
    print_work_plan_summary,
)
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError
from sase.bead.sync import BeadWorkLaunchCommitError

if TYPE_CHECKING:
    from sase.agent.launch_timing import LaunchTimingRecorder
    from sase.bead.work import (
        ChangeSpecLaunchContext,
        VCSLaunchContext,
    )


BEAD_WORK_TIMING_ENV = "SASE_BEAD_WORK_TIMING"


class BeadWorkError(RuntimeError):
    """A recoverable ``sase bead work`` orchestration failure.

    ``agents_launched`` distinguishes failures after every requested agent was
    successfully started (currently the final bead-state commit) from failures
    where the existing rollback path already terminated partial launches and
    restored pre-claims.
    """

    def __init__(self, message: str, *, agents_launched: bool = False) -> None:
        super().__init__(message)
        self.agents_launched = agents_launched


def _post_launch_commit_error(epic_id: str, exc: Exception) -> BeadWorkError:
    return BeadWorkError(
        f"agents launched for epic {epic_id}, but committing bead state failed: {exc}",
        agents_launched=True,
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
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    no_push = bool(getattr(args, "no_push", False))
    json_output = bool(getattr(args, "json", False))
    target = str(getattr(args, "target", getattr(args, "id", "")))

    from sase.bead.cli_work_from_plan import (
        PlanFileWorkError,
        is_plan_file_target,
        work_from_plan_file,
    )

    if is_plan_file_target(target):
        captured = io.StringIO()
        output_context = (
            contextlib.redirect_stdout(captured)
            if json_output
            else contextlib.nullcontext()
        )
        try:
            with output_context:
                result = work_from_plan_file(
                    target,
                    dry_run=dry_run,
                    yes=yes or json_output,
                    no_push=no_push,
                    render=not json_output,
                )
        except PlanFileWorkError as exc:
            if json_output:
                payload: dict[str, object] = {
                    "ok": False,
                    "mode": "plan_file",
                    "error": str(exc),
                }
                if exc.resume_command is not None:
                    payload["resume_command"] = exc.resume_command
                if exc.validation is not None:
                    payload["diagnostics"] = [
                        {
                            "severity": diagnostic.severity.value,
                            "code": diagnostic.code,
                            "field_path": diagnostic.field_path,
                            "message": diagnostic.message,
                            "line": diagnostic.line,
                        }
                        for diagnostic in exc.validation.diagnostics
                    ]
                print(json.dumps(payload, sort_keys=True))
            else:
                print(f"Error: {exc}", file=sys.stderr)
                if exc.resume_command is not None:
                    print(
                        f"Resume with:\n  {exc.resume_command}",
                        file=sys.stderr,
                    )
            raise SystemExit(1) from exc
        if json_output:
            print(json.dumps(result.to_json(), sort_keys=True))
        return

    timer = _make_bead_work_timer(target, dry_run=dry_run)
    with timer, contextlib.ExitStack() as stack:
        with timer.stage("project_open"):
            proj = stack.enter_context(get_project())
        with timer.stage("initial_show"):
            try:
                issue = proj.show(target)
            except KeyError:
                print(f"Error: issue not found: {target}", file=sys.stderr)
                sys.exit(1)
        if issue.issue_type != IssueType.PLAN:
            print(
                f"Error: is_ready_to_work only applies to plan beads "
                f"(got {issue.issue_type.value} for {target})",
                file=sys.stderr,
            )
            sys.exit(1)
        if issue.tier == BeadTier.EPIC:
            captured = io.StringIO()
            output_context = (
                contextlib.redirect_stdout(captured)
                if json_output
                else contextlib.nullcontext()
            )
            try:
                with output_context:
                    launched = launch_epic_bead_work(
                        proj,
                        target,
                        dry_run=dry_run,
                        yes=yes or json_output,
                        no_push=no_push,
                        timer=timer,
                    )
            except BeadWorkError as exc:
                if json_output:
                    print(
                        json.dumps(
                            {
                                "ok": False,
                                "mode": "bead_id",
                                "epic_id": target,
                                "error": str(exc),
                            },
                            sort_keys=True,
                        )
                    )
                else:
                    print(f"Error: {exc}", file=sys.stderr)
                raise SystemExit(1) from exc
            if json_output:
                phase_ids = [phase.id for phase in proj.get_epic_children(target)]
                print(
                    json.dumps(
                        {
                            "ok": True,
                            "mode": "bead_id",
                            "dry_run": dry_run,
                            "epic_id": target,
                            "phase_bead_ids": phase_ids,
                            "launched": launched,
                        },
                        sort_keys=True,
                    )
                )
            return

        tier = issue.tier.value if issue.tier else "missing tier"
        print(
            "Error: sase bead work only applies to epic plan beads "
            f"(got {tier} for {target})",
            file=sys.stderr,
        )
        sys.exit(1)


def launch_epic_bead_work(
    proj: BeadProject,
    epic_id: str,
    *,
    dry_run: bool,
    yes: bool,
    no_push: bool,
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
                timer=owned_timer,
            )

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
        return False

    if not yes and not confirm_launch():
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
            rollback_work_launch(
                proj, epic_id, claimed, unmark_ready=marked_ready_this_run
            )
            raise BeadWorkError(f"pre-claim failed for epic {epic_id}: {e}") from e

    try:
        with timer.stage("agent_launch"):
            results = launch_bead_work_agents(
                query,
                segment_extra_env=epic_work_segment_env(plan),
                expected_names=expected_agent_names(plan),
                launch_context=changespec_context or vcs_context,
            )
    except Exception as e:
        launched_results = list(getattr(e, "results", []))
        launched_pids = [r.pid for r in launched_results]
        rollback_work_launch(
            proj,
            epic_id,
            claimed,
            unmark_ready=marked_ready_this_run,
            launched_pids=launched_pids,
            launched_results=launched_results,
        )
        raise BeadWorkError(
            f"agent launch failed for epic {epic_id}: {e}\n"
            "For broader diagnostics, run `sase doctor -v`."
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
            issue.title,
            kind="epic",
            no_push=no_push,
            timer=timer,
        )
    except BeadWorkLaunchCommitError as exc:
        raise _post_launch_commit_error(epic_id, exc) from exc
    except Exception as exc:
        raise _post_launch_commit_error(epic_id, exc) from exc
    return True


# Compatibility alias for callers/tests that imported the former private helper.
_handle_epic_bead_work = launch_epic_bead_work
