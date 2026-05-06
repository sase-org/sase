"""Epic work launch handler for the bead CLI."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.cli_common import get_project
from sase.bead.model import BeadTier, IssueType, Status
from sase.bead.project import AlreadyReadyError, BeadProject, NotAPlanError
from sase.axe.artifact_metadata import SASE_AGENT_WORKFLOW_LINKS_ENV

if TYPE_CHECKING:
    from sase.bead.work import (
        ChangeSpecLaunchContext,
        EpicWorkPlan,
        LegendWorkPlan,
        VCSLaunchContext,
    )


def handle_bead_work(args: argparse.Namespace) -> None:
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))

    with get_project() as proj:
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
            _handle_epic_bead_work(proj, args.id, dry_run=dry_run, yes=yes)
            return
        if issue.tier == BeadTier.LEGEND:
            _handle_legend_bead_work(proj, args.id, dry_run=dry_run, yes=yes)
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
) -> None:
    from sase.bead.work import (
        ChangeSpecLaunchContext,
        EpicPlanError,
        build_epic_work_plan_from_beads_dir,
        render_multi_prompt,
    )
    from sase.bead.xprompts import (
        BeadXPromptNotFoundError,
        resolve_land_epic_xprompt,
        resolve_work_phase_xprompt,
    )

    try:
        work_phase_xprompt = resolve_work_phase_xprompt()
        land_epic_xprompt = resolve_land_epic_xprompt()
    except (BeadXPromptNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    issue = proj.show(epic_id)
    try:
        plan = build_epic_work_plan_from_beads_dir(proj.beads_dir, epic_id)
    except EpicPlanError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    vcs_context: VCSLaunchContext | None = None
    changespec_context: ChangeSpecLaunchContext | None = None
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

    collisions = find_live_name_collisions(plan)
    if collisions and not dry_run:
        print(
            "Error: refusing to launch; these agent names are still live:",
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
        vcs_context=vcs_context,
        changespec_context=changespec_context,
    )

    if issue.is_ready_to_work:
        print(f"Epic {epic_id} is already ready; retrying remaining non-closed phases.")
    print_work_plan_summary(epic_id, issue.title, plan)

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

    if not yes and not confirm_launch():
        print("Aborted.")
        return

    marked_ready_this_run = False
    if not issue.is_ready_to_work:
        try:
            proj.mark_ready_to_work(epic_id)
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
                claimed.append((assignment.bead_id, prior.status, prior.assignee or ""))
    except (KeyError, ValueError) as e:
        print(f"Error: pre-claim failed for epic {epic_id}: {e}", file=sys.stderr)
        rollback_work_launch(proj, epic_id, claimed, unmark_ready=marked_ready_this_run)
        sys.exit(1)

    try:
        from sase.agent import launcher as _launcher

        result = _launcher.launch_agent_from_cwd(
            query,
            extra_env=_epic_workflow_link_env(plan, changespec_context),
        )
    except Exception as e:
        print(
            f"Error: agent launch failed for epic {epic_id}: {e}",
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
        f"(workspace {result.workspace_num})"
    )


def _handle_legend_bead_work(
    proj: BeadProject,
    legend_id: str,
    *,
    dry_run: bool,
    yes: bool,
) -> None:
    from sase.bead.work import (
        LegendPlanError,
        build_legend_work_plan_from_beads_dir,
        render_legend_multi_prompt,
    )
    from sase.bead.xprompts import (
        BeadXPromptNotFoundError,
        resolve_land_legend_xprompt,
    )

    try:
        land_legend_xprompt = resolve_land_legend_xprompt()
    except (BeadXPromptNotFoundError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    issue = proj.show(legend_id)
    try:
        plan = build_legend_work_plan_from_beads_dir(proj.beads_dir, legend_id)
    except LegendPlanError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    vcs_context = _resolve_vcs_launch_context()
    collisions = _find_live_legend_name_collisions(plan)
    if collisions and not dry_run:
        print(
            "Error: refusing to launch; these agent names are still live:",
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

    query = render_legend_multi_prompt(
        plan,
        land_legend_xprompt=land_legend_xprompt,
        vcs_context=vcs_context,
    )

    if issue.is_ready_to_work:
        print(f"Legend {legend_id} is already ready; retrying epic agent launch.")
    _print_legend_work_plan_summary(legend_id, issue.title, plan)

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

    if not yes and not confirm_launch():
        print("Aborted.")
        return

    marked_ready_this_run = False
    if not issue.is_ready_to_work:
        try:
            proj.mark_ready_to_work(legend_id)
            marked_ready_this_run = True
        except AlreadyReadyError:
            marked_ready_this_run = False
        except (KeyError, NotAPlanError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    try:
        from sase.agent import launcher as _launcher

        result = _launcher.launch_agent_from_cwd(
            query,
            extra_env=_legend_workflow_link_env(plan),
        )
    except Exception as e:
        print(
            f"Error: agent launch failed for legend {legend_id}: {e}",
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
        f"workspace {result.workspace_num})"
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

    project_file = (
        Path.home() / ".sase" / "projects" / project_name / f"{project_name}.gp"
    )
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


def find_live_name_collisions(plan: EpicWorkPlan) -> dict[str, str]:
    """Return ``{agent_name: artifact_dir}`` for plan names owned by live agents."""
    from sase.agent.names import get_live_agent_name_map

    expected = expected_agent_names(plan)
    legacy_land_name = _legacy_land_agent_name(plan)
    if legacy_land_name:
        expected.add(legacy_land_name)
    live = get_live_agent_name_map()
    return {name: live[name] for name in expected if name in live}


def _expected_legend_agent_names(plan: LegendWorkPlan) -> set[str]:
    names = {assignment.agent_name for assignment in plan.assignments}
    names.add(plan.land_agent_name)
    return names


def _find_live_legend_name_collisions(plan: LegendWorkPlan) -> dict[str, str]:
    """Return live collisions for legend epic-planning agent names."""
    from sase.agent.names import get_live_agent_name_map

    expected = _expected_legend_agent_names(plan)
    live = get_live_agent_name_map()
    return {name: live[name] for name in expected if name in live}


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


def _epic_workflow_link_env(
    plan: EpicWorkPlan,
    changespec_context: ChangeSpecLaunchContext | None,
) -> dict[str, str]:
    links: dict[str, dict[str, str]] = {}
    common: dict[str, str] = {"epic_bead_id": plan.epic_id}
    legend_bead_id = plan.launch_tag_id if plan.launch_tag_id != plan.epic_id else None
    if legend_bead_id is not None:
        common["legend_bead_id"] = legend_bead_id
    if changespec_context is not None:
        common["changespec_name"] = changespec_context.changespec_name
    links["*"] = common
    for wave in plan.waves:
        for assignment in wave:
            links[assignment.agent_name] = {
                "epic_bead_id": plan.epic_id,
                "phase_bead_id": assignment.bead_id,
                "bead_id": assignment.bead_id,
            }
            if legend_bead_id is not None:
                links[assignment.agent_name]["legend_bead_id"] = legend_bead_id
            if changespec_context is not None:
                links[assignment.agent_name]["changespec_name"] = (
                    changespec_context.changespec_name
                )
    links[plan.land_agent_name] = {
        "epic_bead_id": plan.epic_id,
        "bead_id": plan.epic_id,
    }
    if legend_bead_id is not None:
        links[plan.land_agent_name]["legend_bead_id"] = legend_bead_id
    if changespec_context is not None:
        links[plan.land_agent_name]["changespec_name"] = (
            changespec_context.changespec_name
        )
    return {SASE_AGENT_WORKFLOW_LINKS_ENV: json.dumps(links, sort_keys=True)}


def _legend_workflow_link_env(plan: LegendWorkPlan) -> dict[str, str]:
    links: dict[str, dict[str, str]] = {"*": {"legend_bead_id": plan.legend_id}}
    for assignment in plan.assignments:
        links[assignment.agent_name] = {
            "legend_bead_id": plan.legend_id,
            "bead_id": plan.legend_id,
            "epic_number": str(assignment.epic_number),
            "sdd_plan_path": plan.plan_file,
        }
    links[plan.land_agent_name] = {
        "legend_bead_id": plan.legend_id,
        "bead_id": plan.legend_id,
        "sdd_plan_path": plan.plan_file,
    }
    return {SASE_AGENT_WORKFLOW_LINKS_ENV: json.dumps(links, sort_keys=True)}


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
