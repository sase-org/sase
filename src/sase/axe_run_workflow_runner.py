#!/usr/bin/env python3
"""Background workflow runner for sase ace TUI.

This script is launched by the ace TUI to run workflows in the background
with proper workspace management. It handles workspace cleanup and releases
the workspace upon completion.
"""

import json
import os
import sys
from datetime import datetime
from typing import Any

from sase.axe_runner_utils import (
    all_steps_hidden,
    install_sigterm_handler,
    prepare_workspace,
    was_killed,
)
from sase.running_field import release_workspace

install_sigterm_handler("workflow")


def _write_workflow_state(
    artifacts_dir: str,
    workflow_name: str,
    cl_name: str,
    status: str,
    error: str | None = None,
    traceback_str: str | None = None,
) -> None:
    """Write a workflow_state.json so the TUI can track this workflow.

    This is called early (before execute_workflow) to ensure the TUI can
    always find and display the workflow entry, even if the process dies
    before WorkflowExecutor creates its own state file.

    Args:
        artifacts_dir: Directory for workflow artifacts.
        workflow_name: Name of the workflow being run.
        cl_name: CL name for context.
        status: Workflow status ("running" or "failed").
        error: Optional error message (for "failed" status).
        traceback_str: Optional traceback string (for "failed" status).
    """
    os.makedirs(artifacts_dir, exist_ok=True)
    state_dict: dict[str, object] = {
        "workflow_name": workflow_name,
        "status": status,
        "current_step_index": 0,
        "steps": [],
        "context": {"cl_name": cl_name},
        "artifacts_dir": artifacts_dir,
        "start_time": datetime.now().isoformat(),
        "pid": os.getpid(),
    }
    if error is not None:
        state_dict["error"] = error
    if traceback_str is not None:
        state_dict["traceback"] = traceback_str
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state_dict, f, indent=2)


def main() -> None:
    """Run workflow and release workspace on completion."""
    # Accept 9 required args + 1 optional: workflow_name, positional_args_json,
    # named_args_json, project_file, workspace_dir, workspace_num, artifacts_dir,
    # update_target, is_home_mode[, hitl_override]
    if not (10 <= len(sys.argv) <= 11):
        print(
            f"Usage: {sys.argv[0]} <workflow_name> <positional_args_json> "
            "<named_args_json> <project_file> <workspace_dir> <workspace_num> "
            "<artifacts_dir> <update_target> <is_home_mode> [<hitl_override>]",
            file=sys.stderr,
        )
        sys.exit(1)

    workflow_name = sys.argv[1]
    positional_args_json = sys.argv[2]
    named_args_json = sys.argv[3]
    project_file = sys.argv[4]
    workspace_dir = sys.argv[5]
    workspace_num = int(sys.argv[6])
    artifacts_dir = sys.argv[7]
    update_target = sys.argv[8]
    is_home_mode_arg = sys.argv[9]
    project_basename = os.path.basename(project_file).replace(".gp", "")

    # Parse JSON args
    positional_args: list[str] = json.loads(positional_args_json)
    named_args: dict[str, str] = json.loads(named_args_json)
    is_home_mode: bool = bool(is_home_mode_arg)

    # Parse optional hitl_override: "1" → True, "0" → False, "" or missing → None
    hitl_override: bool | None = None
    if len(sys.argv) == 11 and sys.argv[10]:
        hitl_override = sys.argv[10] == "1"

    # Get CL name: prefer named_args (injected by launcher with the display
    # name), fall back to update_target, then generic "workflow" sentinel.
    cl_name = named_args.get("cl_name", "") or update_target or "workflow"

    # Extract project from workflow_name (e.g., "eval/amend_commit_propose" → "eval")
    project: str | None = None
    if "/" in workflow_name:
        project = workflow_name.split("/")[0]

    print(f"Starting workflow: {workflow_name}")
    print(f"Workspace: {workspace_dir}")
    print(f"Arguments: {positional_args}, {named_args}")
    print()

    # Write initial workflow state so the TUI can track this entry immediately.
    # WorkflowExecutor.execute() will overwrite this with its own richer state.
    _write_workflow_state(artifacts_dir, workflow_name, cl_name, status="running")

    success = False
    try:
        # Prepare workspace before running workflow (skip for home mode)
        if update_target and not is_home_mode:
            print("=== Preparing Workspace ===")
            if not prepare_workspace(
                workspace_dir,
                cl_name,
                update_target,
                backup_suffix="workflow",
                project_basename=project_basename,
            ):
                print("Failed to prepare workspace", file=sys.stderr)
                _write_workflow_state(
                    artifacts_dir,
                    workflow_name,
                    cl_name,
                    status="failed",
                    error="Failed to prepare workspace",
                )
                sys.exit(1)
            print("===========================")
            print()

        # Change to workspace directory
        os.chdir(workspace_dir)

        # Ensure artifacts directory exists
        os.makedirs(artifacts_dir, exist_ok=True)

        # Execute the workflow
        from sase.xprompt import execute_workflow

        # Inject cl_name and workspace_num into named_args so they're available
        # in workflow context as implicit Jinja2 variables.
        workflow_named_args: dict[str, Any] = dict(named_args)
        workflow_named_args["cl_name"] = cl_name
        workflow_named_args["project_file"] = project_file
        workflow_named_args["workspace_num"] = workspace_num

        execute_workflow(
            workflow_name,
            positional_args,
            workflow_named_args,
            artifacts_dir=artifacts_dir,
            silent=True,
            project=project,
            hitl_override=hitl_override,
        )
        success = True
        print(f"\nWorkflow '{workflow_name}' completed successfully")

    except Exception as e:
        print(f"Error running workflow: {e}", file=sys.stderr)
        import traceback

        traceback.print_exc()
        success = False

        error_str = f"{type(e).__qualname__}: {e}"
        tb_str = traceback.format_exc()

        # Write failed state if the executor hasn't already written one
        # (e.g., workflow not found before executor even starts)
        state_path = os.path.join(artifacts_dir, "workflow_state.json")
        try:
            with open(state_path, encoding="utf-8") as f:
                existing = json.load(f)
            if existing.get("status") != "failed":
                _write_workflow_state(
                    artifacts_dir,
                    workflow_name,
                    cl_name,
                    status="failed",
                    error=error_str,
                    traceback_str=tb_str,
                )
        except (OSError, json.JSONDecodeError):
            _write_workflow_state(
                artifacts_dir,
                workflow_name,
                cl_name,
                status="failed",
                error=error_str,
                traceback_str=tb_str,
            )

    finally:
        # Release workspace (skip for home mode - no workspace to release)
        if not is_home_mode:
            # Always release workspace, even if killed via SIGTERM
            # This prevents zombie workspace claims in the RUNNING field
            try:
                # Build workflow field name to match what was used for claiming
                workflow_field_name = f"workflow({workflow_name})"
                release_workspace(
                    project_file, workspace_num, workflow_field_name, cl_name
                )
                print("Workspace released")
            except Exception as e:
                print(f"Error releasing workspace: {e}", file=sys.stderr)

        # Skip notification if the workflow was killed by the user (SIGTERM).
        # The user already knows it died because they killed it from the TUI.
        # Also skip when every step in the workflow was hidden (e.g. for-loops
        # over empty lists) — there's nothing useful to report.
        if not was_killed() and not all_steps_hidden(artifacts_dir):
            from sase.chat_history import list_chat_histories
            from sase.notifications.senders import notify_workflow_complete
            from sase.sase_utils import get_sase_directory

            # Find chat file (most recent chat history)
            extra_files: list[str] = []
            try:
                chats = list_chat_histories()
                if chats:
                    chats_dir = get_sase_directory("chats")
                    chat_path = os.path.join(chats_dir, f"{chats[0]}.md")
                    from pathlib import Path

                    extra_files.append(chat_path.replace(str(Path.home()), "~"))
            except Exception:
                pass

            # Find diff file from workflow_state.json
            try:
                state_path = os.path.join(artifacts_dir, "workflow_state.json")
                with open(state_path, encoding="utf-8") as f:
                    data = json.load(f)
                diff_path: str | None = None
                steps = data.get("steps", [])
                if steps:
                    last_step = steps[-1]
                    out_types = last_step.get("output_types") or {}
                    step_out = last_step.get("output")
                    if out_types and isinstance(step_out, dict):
                        for fname, ftype in out_types.items():
                            if ftype == "path":
                                diff_path = step_out.get(fname)
                                break
                    if not diff_path and isinstance(step_out, dict):
                        diff_path = step_out.get("diff_path")
                if diff_path:
                    extra_files.append(diff_path)
            except (OSError, json.JSONDecodeError):
                pass

            notify_workflow_complete(
                sender="user-workflow",
                cl_name=cl_name,
                success=success,
                notes=[
                    f"Workflow {'completed' if success else 'failed'}: {workflow_name}"
                ],
                action="JumpToAgent",
                action_data={
                    "cl_name": cl_name,
                    "raw_suffix": os.path.basename(artifacts_dir),
                },
                extra_files=extra_files,
            )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
