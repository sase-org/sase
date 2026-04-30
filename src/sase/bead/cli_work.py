"""Epic work launch handler for the bead CLI."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.cli_common import get_project
from sase.bead.model import IssueType, Status
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError

if TYPE_CHECKING:
    from sase.bead.work import ChangeSpecLaunchContext, EpicWorkPlan


def handle_bead_work(args: argparse.Namespace) -> None:
    from sase.bead.work import (
        ChangeSpecLaunchContext,
        EpicPlanError,
        build_epic_work_plan,
        render_multi_prompt,
    )
    from sase.bead.xprompts import (
        BeadXPromptNotFoundError,
        resolve_land_epic_xprompt,
        resolve_work_phase_xprompt,
    )

    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))

    with get_project() as proj:
        try:
            work_phase_xprompt = resolve_work_phase_xprompt()
            land_epic_xprompt = resolve_land_epic_xprompt()
        except (BeadXPromptNotFoundError, ValueError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

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
        try:
            plan = build_epic_work_plan(proj._conn, args.id)
        except EpicPlanError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        changespec_context: ChangeSpecLaunchContext | None = None
        if issue.changespec_name:
            try:
                changespec_context = _resolve_changespec_launch_context(
                    changespec_name=issue.changespec_name,
                    bug_id=issue.changespec_bug_id,
                )
            except ValueError as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

        collisions = _find_live_name_collisions(plan)
        if collisions and not dry_run:
            print(
                "Error: refusing to launch; these phase agent names are still live:",
                file=sys.stderr,
            )
            for name, path in sorted(collisions.items()):
                print(f"  {name} (running at {path})", file=sys.stderr)
            print(
                "\nKill or dismiss those agents before retrying, or wait for "
                "them to finish.",
                file=sys.stderr,
            )
            sys.exit(1)

        query = render_multi_prompt(
            plan,
            work_phase_xprompt=work_phase_xprompt,
            land_epic_xprompt=land_epic_xprompt,
            changespec_context=changespec_context,
        )

        if issue.is_ready_to_work:
            print(
                f"Epic {args.id} is already ready; retrying remaining "
                "non-closed phases."
            )
        _print_work_plan_summary(args.id, issue.title, plan)

        if dry_run:
            if collisions:
                print(
                    "\nWarning: agent-name collisions would block live launch:",
                    file=sys.stderr,
                )
                for name, path in sorted(collisions.items()):
                    print(f"  {name} (already running at {path})", file=sys.stderr)
            print("\n--- Multi-prompt (dry run) ---")
            print(query)
            return

        if not yes and not _confirm_launch():
            print("Aborted.")
            return

        marked_ready_this_run = False
        if not issue.is_ready_to_work:
            try:
                proj.mark_ready_to_work(args.id)
                marked_ready_this_run = True
            except AlreadyReadyError:
                marked_ready_this_run = False
            except (KeyError, NotAPlanError) as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)

        claimed: list[tuple[str, Status, str]] = []
        try:
            for wave in plan.waves:
                for assignment in wave:
                    prior = proj.show(assignment.bead_id)
                    proj.update(
                        assignment.bead_id,
                        status="in_progress",
                        assignee=assignment.agent_name,
                    )
                    claimed.append(
                        (assignment.bead_id, prior.status, prior.assignee or "")
                    )
        except (KeyError, ValueError) as e:
            print(f"Error: pre-claim failed for epic {args.id}: {e}", file=sys.stderr)
            _rollback_work_launch(
                proj, args.id, claimed, unmark_ready=marked_ready_this_run
            )
            sys.exit(1)

        try:
            from sase.agent import launcher as _launcher

            result = _launcher.launch_agent_from_cwd(query)
        except Exception as e:
            print(
                f"Error: agent launch failed for epic {args.id}: {e}",
                file=sys.stderr,
            )
            launched_pids = [r.pid for r in getattr(e, "results", [])]
            _rollback_work_launch(
                proj,
                args.id,
                claimed,
                unmark_ready=marked_ready_this_run,
                launched_pids=launched_pids,
            )
            sys.exit(1)

    agent_count = sum(len(w) for w in plan.waves) + 1
    print(
        f"✓ Launched {agent_count} agents for epic {args.id} — {issue.title} "
        f"(workspace {result.workspace_num})"
    )


def _resolve_changespec_launch_context(
    *,
    changespec_name: str,
    bug_id: str,
) -> ChangeSpecLaunchContext:
    """Resolve VCS/project context for a ChangeSpec-attached epic launch."""
    from sase.bead.project_name import infer_project_name_from_cwd
    from sase.bead.work import ChangeSpecLaunchContext
    from sase.workspace_provider import detect_workflow_type

    project_name = infer_project_name_from_cwd()
    if not project_name:
        raise ValueError(
            "cannot launch ChangeSpec-attached epic: unable to infer the "
            "current SASE project from this workspace"
        )

    project_file = (
        Path.home() / ".sase" / "projects" / project_name / f"{project_name}.gp"
    )
    if not project_file.exists():
        raise ValueError(
            "cannot launch ChangeSpec-attached epic: project file not found at "
            f"{project_file}"
        )

    try:
        vcs_workflow = detect_workflow_type(str(project_file))
    except ValueError as exc:
        raise ValueError(
            "cannot launch ChangeSpec-attached epic: unable to detect VCS "
            f"workflow for {project_file}: {exc}"
        ) from exc

    return ChangeSpecLaunchContext(
        changespec_name=changespec_name,
        bug_id=bug_id,
        vcs_workflow=vcs_workflow,
        project_name=project_name,
    )


def _expected_agent_names(plan: EpicWorkPlan) -> set[str]:
    names = {a.agent_name for wave in plan.waves for a in wave}
    names.add(plan.land_agent_name)
    return names


def _find_live_name_collisions(plan: EpicWorkPlan) -> dict[str, str]:
    """Return ``{agent_name: artifact_dir}`` for plan names owned by live agents."""
    from sase.agent.names import get_live_agent_name_map

    expected = _expected_agent_names(plan)
    live = get_live_agent_name_map()
    return {name: live[name] for name in expected if name in live}


def _print_work_plan_summary(epic_id: str, title: str, plan: EpicWorkPlan) -> None:
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


def _confirm_launch() -> bool:
    answer = input("Launch these agents? [y/N] ").strip().lower()
    return answer in ("y", "yes")


def _rollback_work_launch(
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
