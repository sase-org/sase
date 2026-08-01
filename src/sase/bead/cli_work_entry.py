"""CLI target dispatch and output handling for ``sase bead work``."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
from collections.abc import Callable
from typing import Any, NoReturn

from sase.bead.cli_common import get_project
from sase.bead.model import BeadTier, IssueType


def handle_bead_work(
    args: argparse.Namespace,
    *,
    timer_factory: Callable[..., Any],
) -> None:
    """Dispatch a plan-file or bead-id work target."""
    artifacts_dir = getattr(args, "artifacts_dir", None)
    cl_name = getattr(args, "cl_name", None)
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))
    no_push = bool(getattr(args, "no_push", False))
    json_output = bool(getattr(args, "json", False))
    yes_to_all = bool(getattr(args, "yes_to_all", False)) or json_output
    parent = getattr(args, "parent", None)
    launch_feedback = getattr(args, "launch_feedback", None)
    expect_prompt_snapshot = bool(getattr(args, "expect_prompt_snapshot", False))
    target = str(getattr(args, "target", getattr(args, "id", "")))

    from sase.bead.cli_work_from_plan import (
        PlanFileWorkError,
        is_plan_file_target,
        work_from_plan_file,
    )
    from sase.bead.epic_launch import finish_epic_launch

    if is_plan_file_target(target):
        if launch_feedback:
            if json_output:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "mode": "plan_file",
                            "error": (
                                "--launch-feedback only applies when the bead "
                                "work target is a task bead"
                            ),
                        },
                        sort_keys=True,
                    )
                )
            else:
                print(
                    "Error: --launch-feedback only applies when the bead work "
                    "target is a task bead",
                    file=sys.stderr,
                )
            raise SystemExit(1)
        captured = io.StringIO()
        output_context = (
            contextlib.redirect_stdout(captured)
            if json_output
            else contextlib.nullcontext()
        )
        timer = timer_factory(target, dry_run=dry_run)
        try:
            with timer, output_context:
                result = work_from_plan_file(
                    target,
                    dry_run=dry_run,
                    yes=yes,
                    yes_to_all=yes_to_all,
                    no_push=no_push,
                    parent=parent,
                    render=not json_output,
                    expect_prompt_snapshot=expect_prompt_snapshot,
                    timer=timer,
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

    # Resolve through the compatibility module at call time so callers that
    # replace its launch helper continue to affect CLI dispatch.
    from sase.bead import cli_work_handler

    timer = timer_factory(target, dry_run=dry_run)
    with timer, contextlib.ExitStack() as stack:
        with timer.stage("project_open"):
            proj = stack.enter_context(get_project())
        with timer.stage("initial_show"):
            try:
                issue = proj.show(target)
                target = issue.id
            except KeyError:
                _exit_bead_id_error(
                    f"issue not found: {target}",
                    target=target,
                    json_output=json_output,
                )
            except ValueError as exc:
                _exit_bead_id_error(
                    str(exc),
                    target=target,
                    json_output=json_output,
                )
        if issue.issue_type != IssueType.PLAN:
            if issue.issue_type is IssueType.TASK:
                from sase.bead.cli_work_from_plan_store import epic_plan_launch_lock

                captured = io.StringIO()
                output_context = (
                    contextlib.redirect_stdout(captured)
                    if json_output
                    else contextlib.nullcontext()
                )
                try:
                    with contextlib.ExitStack() as lock_stack:
                        with timer.stage("plan_launch_lock"):
                            lock_stack.enter_context(
                                epic_plan_launch_lock(proj.root_dir)
                            )
                        lock_stack.enter_context(output_context)
                        task_result = cli_work_handler.launch_task_bead_work(
                            proj,
                            target,
                            dry_run=dry_run,
                            yes=yes,
                            no_push=no_push,
                            yes_to_all=yes_to_all,
                            feedback=launch_feedback,
                            timer=timer,
                        )
                except cli_work_handler.TaskBeadWorkError as exc:
                    if json_output:
                        print(
                            json.dumps(
                                {
                                    "ok": False,
                                    "mode": "bead_id",
                                    "task_id": target,
                                    "error": str(exc),
                                },
                                sort_keys=True,
                            )
                        )
                    else:
                        print(f"Error: {exc}", file=sys.stderr)
                    raise SystemExit(1) from exc
                if json_output:
                    print(
                        json.dumps(
                            {
                                "ok": True,
                                "mode": "bead_id",
                                "dry_run": dry_run,
                                "task_id": task_result.task_id,
                                "agent_name": task_result.agent_name,
                                "launch_state": task_result.launch_state,
                                "launched": task_result.launched,
                                "workspace_num": task_result.workspace_num,
                            },
                            sort_keys=True,
                        )
                    )
                return
            _exit_bead_id_error(
                "sase bead work only applies to epic plan or task beads "
                f"(got {issue.issue_type.value} for {target})",
                target=target,
                json_output=json_output,
            )
        if launch_feedback:
            _exit_bead_id_error(
                "--launch-feedback only applies when the bead work target is "
                "a task bead",
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
                with contextlib.ExitStack() as lock_stack:
                    with timer.stage("plan_launch_lock"):
                        lock_stack.enter_context(epic_plan_launch_lock(proj.root_dir))
                    lock_stack.enter_context(output_context)
                    launched = cli_work_handler.launch_epic_bead_work(
                        proj,
                        target,
                        dry_run=dry_run,
                        yes=yes,
                        no_push=no_push,
                        yes_to_all=yes_to_all,
                        timer=timer,
                    )
            except cli_work_handler.BeadWorkError as exc:
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
