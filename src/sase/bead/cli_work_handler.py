"""Top-level orchestration for ``sase bead work``."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, NoReturn

from sase.bead.cli_common import get_project
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
from sase.bead.model import BeadTier, IssueType
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


def _epic_plan_source_path(proj: BeadProject, plan_ref: str) -> Path:
    """Resolve an epic's approved plan from its authoritative bead store."""
    expanded = Path(plan_ref).expanduser()
    if expanded.is_absolute():
        return expanded.resolve(strict=False)
    if not plan_ref.strip():
        raise ValueError("the epic has no approved plan reference")

    root = proj.root_dir.expanduser().resolve(strict=False)
    beads_dir = proj.beads_dir.expanduser().resolve(strict=False)
    try:
        beads_relative = beads_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("the bead store is outside its project root") from exc

    parts = tuple(part for part in Path(plan_ref.replace("\\", "/")).parts if part)
    if beads_relative == Path("sdd/beads"):
        plans_root = root / "sdd" / "plans"
        relative = _plan_ref_after_marker(parts, ("sdd", "plans"))
        if relative is None:
            relative = _plan_ref_after_marker(parts, ("plans",)) or parts
    elif beads_relative == Path("beads"):
        sidecar_relative = _plan_ref_after_marker(
            parts,
            ("sase", "repos", "plans"),
        )
        local_relative = _plan_ref_after_marker(
            parts,
            (".sase", "sdd", "plans"),
        )
        if sidecar_relative is not None:
            plans_root = root
            relative = sidecar_relative
        elif local_relative is not None:
            plans_root = root / "plans"
            relative = local_relative
        else:
            plans_relative = _plan_ref_after_marker(parts, ("plans",))
            local_layout = root.name == "sdd" and root.parent.name == ".sase"
            if plans_relative is not None or local_layout or (root / "plans").is_dir():
                plans_root = root / "plans"
                relative = plans_relative or parts
            else:
                plans_root = root
                relative = parts
    else:
        raise ValueError(f"unsupported bead store layout: {beads_relative}")

    resolved_root = plans_root.resolve(strict=False)
    source = resolved_root.joinpath(*relative).resolve(strict=False)
    try:
        source.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError("the relative plan reference escapes its plans store") from exc
    return source


def _plan_ref_after_marker(
    parts: tuple[str, ...],
    marker: tuple[str, ...],
) -> tuple[str, ...] | None:
    """Return the suffix after a known storage marker in a plan reference."""
    marker_length = len(marker)
    for index in range(len(parts) - marker_length + 1):
        if parts[index : index + marker_length] == marker:
            return parts[index + marker_length :]
    return None


def _epic_plan_snapshot_destination(project_name: str, epic_id: str) -> Path:
    """Return a project-scoped snapshot path confined to one safe filename."""
    from sase.core.paths import sase_projects_dir, validate_sase_project_name

    validate_sase_project_name(project_name)
    if (
        not epic_id
        or epic_id in {".", ".."}
        or "\x00" in epic_id
        or "/" in epic_id
        or "\\" in epic_id
    ):
        raise ValueError(f"invalid epic identifier for snapshot: {epic_id!r}")
    filename = f"{epic_id}.md"
    destination = (
        sase_projects_dir() / project_name / "artifacts" / "epic-plans" / filename
    )
    return destination.expanduser().resolve(strict=False)


def _atomic_copy_epic_plan(source: Path, destination: Path) -> None:
    """Replace *destination* with a complete copy of *source*."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temporary_path = Path(temporary)
    try:
        shutil.copyfile(source, temporary_path)
        os.replace(temporary_path, destination)
    finally:
        temporary_path.unlink(missing_ok=True)


def _snapshot_epic_plan(
    proj: BeadProject,
    epic_id: str,
    *,
    plan_ref: str,
    launch_context: VCSLaunchContext | None,
) -> str | None:
    """Best-effort copy of an approved plan into durable project state."""
    project_name = launch_context.project_name if launch_context is not None else None
    if not project_name:
        from sase.bead.project_name import infer_project_name_from_cwd

        project_name = infer_project_name_from_cwd()

    try:
        if not project_name:
            raise ValueError("the current SASE project could not be inferred")
        source = _epic_plan_source_path(proj, plan_ref)
        destination = _epic_plan_snapshot_destination(project_name, epic_id)
        _atomic_copy_epic_plan(source, destination)
    except Exception as exc:
        destination_context = project_name or "unknown project"
        failure = type(exc).__name__
        if isinstance(exc, ValueError):
            failure = f"{failure}: {exc}"
        print(
            f"Warning: could not snapshot approved plan for epic {epic_id!r} "
            f"from reference {plan_ref!r} into project "
            f"{destination_context!r}: {failure}",
            file=sys.stderr,
        )
        return None
    return str(destination)


def handle_bead_work(args: argparse.Namespace) -> None:
    artifacts_dir = getattr(args, "artifacts_dir", None)
    cl_name = getattr(args, "cl_name", None)
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    no_push = bool(getattr(args, "no_push", False))
    json_output = bool(getattr(args, "json", False))
    yes_to_all = bool(getattr(args, "yes_to_all", False)) or json_output
    parent = getattr(args, "parent", None)
    target = str(getattr(args, "target", getattr(args, "id", "")))

    from sase.bead.cli_work_from_plan import (
        PlanFileWorkError,
        is_plan_file_target,
        work_from_plan_file,
    )
    from sase.bead.epic_launch import finish_epic_launch

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
                    yes=yes,
                    yes_to_all=yes_to_all,
                    no_push=no_push,
                    parent=parent,
                    render=not json_output,
                )
        except PlanFileWorkError as exc:
            finish_epic_launch(
                target,
                artifacts_dir=artifacts_dir,
                cl_name=cl_name,
                error=exc,
            )
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
        except Exception as exc:
            finish_epic_launch(
                target,
                artifacts_dir=artifacts_dir,
                cl_name=cl_name,
                error=exc,
            )
            raise
        finish_epic_launch(
            target,
            artifacts_dir=artifacts_dir,
            cl_name=cl_name,
            result=result,
        )
        if json_output:
            print(json.dumps(result.to_json(), sort_keys=True))
        return

    plan_file_only_flags = [
        flag
        for flag, value in (
            ("--parent", parent),
            ("--artifacts-dir", artifacts_dir),
            ("--cl-name", cl_name),
        )
        if value is not None
    ]
    if plan_file_only_flags:
        flags = ", ".join(plan_file_only_flags)
        noun = "option" if len(plan_file_only_flags) == 1 else "options"
        _exit_bead_id_error(
            f"{flags} {noun} only applies when the bead work target is a plan file",
            target=target,
            json_output=json_output,
        )

    timer = _make_bead_work_timer(target, dry_run=dry_run)
    with timer, contextlib.ExitStack() as stack:
        with timer.stage("project_open"):
            proj = stack.enter_context(get_project())
        with timer.stage("initial_show"):
            try:
                issue = proj.show(target)
            except KeyError:
                _exit_bead_id_error(
                    f"issue not found: {target}",
                    target=target,
                    json_output=json_output,
                )
        if issue.issue_type != IssueType.PLAN:
            _exit_bead_id_error(
                "sase bead work only applies to plan beads "
                f"(got {issue.issue_type.value} for {target})",
                target=target,
                json_output=json_output,
            )
        if issue.tier == BeadTier.EPIC:
            from sase.bead.cli_work_from_plan_store import epic_plan_launch_lock

            captured = io.StringIO()
            output_context = (
                contextlib.redirect_stdout(captured)
                if json_output
                else contextlib.nullcontext()
            )
            try:
                with epic_plan_launch_lock(proj.root_dir), output_context:
                    launched = launch_epic_bead_work(
                        proj,
                        target,
                        dry_run=dry_run,
                        yes=yes,
                        no_push=no_push,
                        yes_to_all=yes_to_all,
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
                phase_ids = [
                    phase.id
                    for phase in proj.get_epic_children(target)
                    if phase.issue_type is IssueType.PHASE
                ]
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
        _exit_bead_id_error(
            f"sase bead work only applies to epic plan beads (got {tier} for {target})",
            target=target,
            json_output=json_output,
        )


def _exit_bead_id_error(
    message: str,
    *,
    target: str,
    json_output: bool,
) -> NoReturn:
    if json_output:
        print(
            json.dumps(
                {
                    "ok": False,
                    "mode": "bead_id",
                    "epic_id": target,
                    "error": message,
                },
                sort_keys=True,
            )
        )
    else:
        print(f"Error: {message}", file=sys.stderr)
    raise SystemExit(1)


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
            issue.title,
            kind="epic",
            no_push=no_push or defer_push,
            timer=timer,
        )
    except BeadWorkLaunchCommitError as exc:
        raise _post_launch_commit_error(
            epic_id,
            exc,
            graph_published=graph_published,
        ) from exc
    except Exception as exc:
        raise _post_launch_commit_error(
            epic_id,
            exc,
            graph_published=graph_published,
        ) from exc
    return True


# Compatibility alias for callers/tests that imported the former private helper.
_handle_epic_bead_work = launch_epic_bead_work
