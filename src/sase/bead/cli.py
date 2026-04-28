"""CLI handlers for the 'sase bead' subcommand."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from sase.bead.model import IssueType, Status
from sase.bead.project import (
    BEADS_DIRNAME,
    BEADS_DIRNAME_NON_VC,
    AlreadyReadyError,
    BeadProject,
    NotAPlanError,
)
from sase.bead.workspace import MergedBeadView, get_project_beads_dirs

if TYPE_CHECKING:
    from sase.bead.work import EpicWorkPlan


def _find_beads_location() -> tuple[Path, str]:
    """Determine the beads root directory and subdirectory name.

    Uses the primary workspace and ``sdd.version_controlled`` config to choose:
      - Non-VC (default): ``primary/.sase/sdd/beads/``
      - VC: ``.sase_beads/`` in CWD (or primary workspace)

    Falls back to legacy walk-up-from-cwd when no primary workspace is found.

    Returns (root_dir, beads_dirname) where root_dir / beads_dirname is the
    beads directory.
    """
    from sase.bead.workspace import resolve_primary_workspace

    cwd = Path.cwd()

    primary = resolve_primary_workspace()
    if primary:
        from sase.sdd.beads import get_sdd_config

        if get_sdd_config():
            # VC mode: .sase_beads/ — prefer CWD copy, then primary.
            if (cwd / BEADS_DIRNAME).is_dir():
                return cwd, BEADS_DIRNAME
            return primary, BEADS_DIRNAME
        else:
            # Non-VC mode: always primary/.sase/sdd/beads/
            return primary / ".sase" / "sdd", BEADS_DIRNAME_NON_VC

    # No primary workspace — legacy walk-up from cwd.
    for parent in [cwd, *cwd.parents]:
        if (parent / BEADS_DIRNAME).is_dir():
            return parent, BEADS_DIRNAME
        non_vc = parent / ".sase" / "sdd" / BEADS_DIRNAME_NON_VC
        if non_vc.is_dir():
            return parent / ".sase" / "sdd", BEADS_DIRNAME_NON_VC

    return cwd, BEADS_DIRNAME


def _init_beads(root: Path, beads_dirname: str) -> None:
    """Initialize beads at the given location.

    For non-VC mode, bootstraps a standalone git repo inside the SDD directory.
    """
    if beads_dirname == BEADS_DIRNAME_NON_VC:
        import subprocess

        root.mkdir(parents=True, exist_ok=True)
        if not (root / ".git").is_dir():
            subprocess.run(
                ["git", "init"],
                cwd=root,
                check=True,
                capture_output=True,
                stdin=subprocess.DEVNULL,
            )
        gitignore = root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text("beads/beads.db\n", encoding="utf-8")
    with BeadProject.init(root, beads_dirname=beads_dirname):
        pass
    if beads_dirname == BEADS_DIRNAME_NON_VC:
        from sase.sdd.files import commit_sdd_files

        commit_sdd_files(root, "Initialize beads")


def _get_project() -> BeadProject:
    """Open the BeadProject for write operations, auto-initializing if needed."""
    root, beads_dirname = _find_beads_location()
    beads_path = root / beads_dirname
    if not beads_path.exists():
        _init_beads(root, beads_dirname)
    return BeadProject(root, beads_dirname=beads_dirname)


def _get_read_view() -> MergedBeadView | BeadProject:
    """Get a merged read view across all workspaces.

    Falls back to the local BeadProject if workspace resolution fails.
    """
    beads_dirs = get_project_beads_dirs()
    if beads_dirs:
        return MergedBeadView(beads_dirs)
    return _get_project()


def _normalize_workspace_path(resolved: Path) -> Path:
    """Normalize a path from an ephemeral workspace to the primary workspace.

    If ``resolved`` is inside a sibling workspace (same parent directory as the
    primary workspace), rewrite it to be rooted at the primary workspace instead.
    This prevents ephemeral ``sase_<N>`` prefixes from leaking into stored paths.
    """
    from sase.bead.workspace import resolve_primary_workspace

    primary = resolve_primary_workspace()
    if not primary:
        return resolved

    try:
        resolved.relative_to(primary)
        return resolved  # already inside primary
    except ValueError:
        pass

    # Check if inside a sibling workspace (same parent directory)
    try:
        rel_to_parent = resolved.relative_to(primary.parent)
    except ValueError:
        return resolved  # not in a sibling workspace

    parts = rel_to_parent.parts
    if len(parts) > 1:
        return primary / Path(*parts[1:])
    return resolved


def _status_icon(status: Status) -> str:
    return {"open": "○", "in_progress": "◐", "closed": "✓"}[status.value]


# --- Subcommand handlers ---


def handle_bead_init(args: argparse.Namespace) -> None:
    root, beads_dirname = _find_beads_location()
    beads_path = root / beads_dirname
    if beads_path.exists():
        print(f"Already initialized: {beads_path}")
        return
    _init_beads(root, beads_dirname)
    print(f"Initialized {beads_dirname}/ in {root}")


def _parse_type_arg(value: str) -> tuple[IssueType, str | None, str | None]:
    """Parse the ``--type`` argument into (issue_type, plan_path, parent_id).

    Accepted forms:
    - ``plan(<path>)``                → PLAN, design=path, parent_id=None
    - ``plan(<path>,<parent_id>)``    → PLAN, design=path, parent_id=parent_id
    - ``phase(<parent_id>)``          → PHASE, design=None, parent_id=parent_id
    """
    m = re.match(r"^(plan|phase)\((.+)\)$", value)
    if not m:
        print(
            f"Error: invalid --type value: {value}\n"
            "Expected: plan(<plan_file>), plan(<plan_file>,<parent_id>), or phase(<parent_id>)",
            file=sys.stderr,
        )
        sys.exit(1)

    kind, inner = m.group(1), m.group(2)
    parts = [p.strip() for p in inner.split(",")]

    if kind == "plan":
        if len(parts) == 1:
            return IssueType.PLAN, parts[0], None
        if len(parts) == 2:
            return IssueType.PLAN, parts[0], parts[1]
        print(
            f"Error: plan() expects 1 or 2 arguments, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)
    else:  # phase
        if len(parts) == 1:
            return IssueType.PHASE, None, parts[0]
        print(
            f"Error: phase() expects exactly 1 argument, got {len(parts)}",
            file=sys.stderr,
        )
        sys.exit(1)


def handle_bead_create(args: argparse.Namespace) -> None:
    issue_type, plan_path, parent_id = _parse_type_arg(args.type)

    # Validate plan file exists and resolve path for the design field
    design = ""
    if plan_path:
        plan_file = Path(plan_path)
        if not plan_file.exists():
            print(f"Error: plan file not found: {plan_path}", file=sys.stderr)
            sys.exit(1)
        design = str(_normalize_workspace_path(plan_file.resolve()))

    with _get_project() as proj:
        # Validate parent exists
        if parent_id:
            try:
                proj.show(parent_id)
            except KeyError:
                print(f"Error: parent bead not found: {parent_id}", file=sys.stderr)
                sys.exit(1)

        issue = proj.create(
            title=args.title,
            issue_type=issue_type,
            parent_id=parent_id,
            description=args.description or "",
            assignee=args.assignee or "",
            design=design,
        )
        print(f"Created {issue.issue_type.value}: {issue.id} — {issue.title}")


def handle_bead_list(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
        statuses = (
            [Status(s) for s in args.status]
            if args.status
            else [Status.OPEN, Status.IN_PROGRESS]
        )
        issue_types = [IssueType(t) for t in args.type] if args.type else None
        issues = view.list_issues(statuses=statuses, issue_types=issue_types)
        if not issues:
            print("No issues found.")
            return
        for issue in issues:
            icon = _status_icon(issue.status)
            parent = f" ← {issue.parent_id}" if issue.parent_id else ""
            print(f"{icon} {issue.id} · {issue.title}{parent}")


def handle_bead_show(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
        try:
            issue = view.show(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)

        icon = _status_icon(issue.status)
        print(f"{icon} {issue.id} · {issue.title}   [{issue.status.value.upper()}]")
        print(f"Type: {issue.issue_type.value} · Owner: {issue.owner or '(none)'}")
        if issue.assignee:
            print(f"Assignee: {issue.assignee}")
        if issue.parent_id:
            try:
                parent = view.show(issue.parent_id)
                print(
                    f"\nPARENT\n  ↑ {parent.id} · {parent.title}"
                    f"   [{parent.status.value.upper()}]"
                )
            except KeyError:
                print(f"\nPARENT\n  ↑ {issue.parent_id}")
        # Show children if plan
        if issue.issue_type == IssueType.PLAN:
            children = view.get_epic_children(issue.id)
            if children:
                print("\nCHILDREN")
                for c in children:
                    ci = _status_icon(c.status)
                    print(f"  {ci} {c.id}: {c.title}")
        # Show dependencies
        deps_on = list(issue.dependencies)
        if deps_on:
            print("\nDEPENDS ON")
            for d in deps_on:
                try:
                    dep_issue = view.show(d.depends_on_id)
                    di = _status_icon(dep_issue.status)
                    print(
                        f"  → {di} {dep_issue.id}: {dep_issue.title}"
                        f"   [{dep_issue.status.value.upper()}]"
                    )
                except KeyError:
                    print(f"  → {d.depends_on_id} (not found)")
        # Show what this blocks
        all_issues = view.list_issues()
        blocks: list[str] = []
        for other in all_issues:
            for d in other.dependencies:
                if d.depends_on_id == issue.id:
                    blocks.append(other.id)
        if blocks:
            print("\nBLOCKS")
            for bid in blocks:
                try:
                    b = view.show(bid)
                    bi = _status_icon(b.status)
                    print(f"  ← {bi} {b.id}: {b.title}   [{b.status.value.upper()}]")
                except KeyError:
                    print(f"  ← {bid} (not found)")
        if issue.description:
            print(f"\nDESCRIPTION\n  {issue.description}")
        if issue.notes:
            print(f"\nNOTES\n  {issue.notes}")
        if issue.design:
            from sase.sdd.beads import get_sdd_config

            if get_sdd_config():
                display = os.path.relpath(issue.design)
            else:
                display = issue.design
            print(f"\nPLAN\n  {display}")


def handle_bead_ready(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
        issues = view.ready()
        if not issues:
            print("No issues ready (all blocked or none open).")
            return
        for issue in issues:
            parent = f" ← {issue.parent_id}" if issue.parent_id else ""
            print(f"○ {issue.id} · {issue.title}{parent}")
        print(f"\n{'-' * 60}")
        print(f"Ready: {len(issues)} issues with no active blockers")


def handle_bead_work(args: argparse.Namespace) -> None:
    from sase.bead.work import (
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

    with _get_project() as proj:
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
        if issue.is_ready_to_work:
            print(
                f"Error: {args.id} is already marked is_ready_to_work=True",
                file=sys.stderr,
            )
            sys.exit(1)

        try:
            plan = build_epic_work_plan(proj._conn, args.id)
        except EpicPlanError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        collisions = _find_name_collisions(plan)
        if collisions and not dry_run:
            print(
                "Error: refusing to launch — these agent names are already in use:",
                file=sys.stderr,
            )
            for name, path in sorted(collisions.items()):
                print(f"  {name} (running at {path})", file=sys.stderr)
            print(
                "\nDismiss or kill those agents in the TUI (or `sase run --kill ...`) "
                "before retrying.",
                file=sys.stderr,
            )
            sys.exit(1)

        query = render_multi_prompt(
            plan,
            work_phase_xprompt=work_phase_xprompt,
            land_epic_xprompt=land_epic_xprompt,
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

        try:
            proj.mark_ready_to_work(args.id)
        except (KeyError, NotAPlanError, AlreadyReadyError) as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

        claimed: list[tuple[str, str]] = []
        try:
            for wave in plan.waves:
                for assignment in wave:
                    prior = proj.show(assignment.bead_id)
                    proj.update(
                        assignment.bead_id,
                        status="in_progress",
                        assignee=assignment.agent_name,
                    )
                    claimed.append((assignment.bead_id, prior.assignee or ""))
        except (KeyError, ValueError) as e:
            print(f"Error: pre-claim failed for epic {args.id}: {e}", file=sys.stderr)
            _rollback_work_launch(proj, args.id, claimed)
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
            _rollback_work_launch(proj, args.id, claimed, launched_pids=launched_pids)
            sys.exit(1)

    agent_count = sum(len(w) for w in plan.waves) + 1
    print(
        f"✓ Launched {agent_count} agents for epic {args.id} — {issue.title} "
        f"(workspace {result.workspace_num})"
    )


def _expected_agent_names(plan: EpicWorkPlan) -> set[str]:
    names = {a.agent_name for wave in plan.waves for a in wave}
    names.add(plan.land_agent_name)
    return names


def _find_name_collisions(plan: EpicWorkPlan) -> dict[str, str]:
    """Return ``{agent_name: artifact_dir}`` for plan names already claimed."""
    from sase.agent.names import get_active_agent_name_map

    expected = _expected_agent_names(plan)
    active = get_active_agent_name_map()
    return {name: active[name] for name in expected if name in active}


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
    claimed: list[tuple[str, str]],
    *,
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

    print(
        "Rolling back pre-claims and is_ready_to_work flag. If rollback also "
        "fails, fix the affected bead status/assignee fields manually.",
        file=sys.stderr,
    )
    for bead_id, prior_assignee in reversed(claimed):
        try:
            proj.update(bead_id, status="open", assignee=prior_assignee)
        except Exception as exc:  # noqa: BLE001
            print(
                f"Warning: failed to roll back pre-claim on {bead_id}: {exc}",
                file=sys.stderr,
            )
    try:
        proj.unmark_ready_to_work(epic_id)
    except Exception as exc:  # noqa: BLE001
        print(
            f"Warning: failed to roll back is_ready_to_work on {epic_id}: {exc}",
            file=sys.stderr,
        )


def handle_bead_update(args: argparse.Namespace) -> None:
    with _get_project() as proj:
        fields: dict[str, str | None] = {}
        if args.status:
            fields["status"] = args.status
        if args.title:
            fields["title"] = args.title
        if args.description is not None:
            fields["description"] = args.description
        if args.notes is not None:
            fields["notes"] = args.notes
        if args.design is not None:
            fields["design"] = args.design
        if args.assignee is not None:
            fields["assignee"] = args.assignee
        if not fields:
            print("No fields to update.", file=sys.stderr)
            sys.exit(1)
        try:
            issue = proj.update(args.id, **fields)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        print(f"✓ Updated issue: {issue.id} — {issue.title}")


def handle_bead_close(args: argparse.Namespace) -> None:
    with _get_project() as proj:
        try:
            closed = proj.close(args.ids, reason=args.reason)
        except KeyError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        for issue in closed:
            print(f"✓ Closed: {issue.id} — {issue.title}")


def handle_bead_dep(args: argparse.Namespace) -> None:
    if args.dep_action == "add":
        with _get_project() as proj:
            dep = proj.add_dependency(args.issue, args.depends_on)
            print(f"✓ Added dependency: {dep.issue_id} depends on {dep.depends_on_id}")
    else:
        print(f"Unknown dep action: {args.dep_action}", file=sys.stderr)
        sys.exit(1)


def handle_bead_blocked(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
        issues = view.blocked()
        if not issues:
            print("No blocked issues.")
            return
        for issue in issues:
            blockers = [d.depends_on_id for d in issue.dependencies]
            blocker_str = ", ".join(blockers)
            print(f"● {issue.id} · {issue.title}  [blocked by: {blocker_str}]")


def handle_bead_sync(args: argparse.Namespace) -> None:
    with _get_project() as proj:
        if args.status:
            clean = proj.sync_is_clean()
            if clean:
                print("✓ JSONL is in sync with git")
            else:
                print("○ JSONL has uncommitted changes")
            return
        proj.sync()
        print("✓ Synced issues to git")


def handle_bead_stats(args: argparse.Namespace) -> None:
    with _get_read_view() as view:
        s = view.stats()
        print("Issue Statistics")
        print(f"  Total:       {s.get('total', 0)}")
        print(f"  Open:        {s.get('open', 0)}")
        print(f"  In Progress: {s.get('in_progress', 0)}")
        print(f"  Closed:      {s.get('closed', 0)}")
        print(f"  Plans:       {s.get('plan', 0)}")
        print(f"  Phases:      {s.get('phase', 0)}")


def handle_bead_doctor(args: argparse.Namespace) -> None:
    with _get_project() as proj:
        messages = proj.doctor()
        for msg in messages:
            print(msg)


def handle_bead_rm(args: argparse.Namespace) -> None:
    with _get_project() as proj:
        try:
            removed = proj.remove(args.id)
        except KeyError:
            print(f"Error: issue not found: {args.id}", file=sys.stderr)
            sys.exit(1)
        for issue in removed:
            print(f"✗ Removed: {issue.id} — {issue.title}")


def handle_bead_onboard(args: argparse.Namespace) -> None:
    print("""sase bead — Lightweight git-native issue tracking

Quick Start:
  sase bead init                                 Create .sase_beads/ in current directory
  sase bead create -t "Fix bug" --type phase(<plan-id>)
  sase bead create -t "New feature" --type plan(plan.md)
  sase bead create -t "Sub-plan" --type plan(plan.md,<plan-id>)
  sase bead list                                 List all issues
  sase bead list --status=open                   List open issues
  sase bead ready                                Show issues ready to work
  sase bead show <id>                            View issue details
  sase bead update <id> --status=in_progress     Claim an issue
  sase bead close <id>                           Close an issue
  sase bead rm <id>                              Remove an issue (and children)
  sase bead dep add <issue> <depends-on>         Add dependency
  sase bead blocked                              Show blocked issues
  sase bead sync                                 Commit JSONL to git
  sase bead stats                                Project statistics
  sase bead doctor                               Health check
  sase bead work <epic>                          Mark an epic plan ready to work""")
