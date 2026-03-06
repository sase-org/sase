"""Shared utilities for axe runner scripts."""

import json
import os
import signal
import sys
from collections.abc import Callable

from sase.ace.changespec import ChangeSpec, parse_project_file
from sase.vcs_provider import get_vcs_provider

# Global state for SIGTERM handler
_killed_state: dict[str, bool] = {"killed": False}


def was_killed() -> bool:
    """Check if the process received SIGTERM."""
    return _killed_state["killed"]


def install_sigterm_handler(description: str = "process") -> None:
    """Install a SIGTERM handler that sets killed flag and exits gracefully.

    The handler uses sys.exit() instead of re-raising SIGTERM so that
    finally blocks run, ensuring workspace cleanup happens before exit.

    Args:
        description: What was killed (e.g., "agent", "mentor", "workflow").
    """

    def _handler(_signum: int, _frame: object) -> None:
        _killed_state["killed"] = True
        print(f"\nReceived SIGTERM - {description} was killed", file=sys.stderr)
        sys.exit(128 + signal.SIGTERM)

    signal.signal(signal.SIGTERM, _handler)


def prepare_workspace(
    workspace_dir: str,
    cl_name: str,
    update_target: str,
    backup_suffix: str = "ace",
    project_basename: str = "",
) -> bool:
    """Clean and update workspace before running agent or workflow.

    Args:
        workspace_dir: The workspace directory.
        cl_name: Display name for the CL/project (used for backup diff name).
        update_target: What to checkout (CL name or "p4head").
        backup_suffix: Suffix appended to cl_name for the backup diff name
            (e.g., "ace" produces "{cl_name}-ace").
        project_basename: Project basename for resolving changespec names to
            git branch names.

    Returns:
        True if successful, False otherwise.
    """
    from sase.commit_utils import run_sase_hg_clean

    # Clean workspace (saves any existing changes to a diff file)
    print("Cleaning workspace...")
    success, error = run_sase_hg_clean(workspace_dir, f"{cl_name}-{backup_suffix}")
    if not success:
        print(f"sase_hg_clean failed: {error}", file=sys.stderr)
        return False

    # Update workspace to target
    from sase.vcs_provider import VCS_DEFAULT_REVISION

    provider = get_vcs_provider(workspace_dir)
    if update_target == VCS_DEFAULT_REVISION:
        update_target = provider.get_default_parent_revision(workspace_dir)
    elif project_basename:
        update_target = provider.resolve_revision(
            update_target, project_basename, workspace_dir
        )
    print(f"Updating workspace to {update_target}...")
    checkout_ok, checkout_err = provider.checkout(update_target, workspace_dir)
    if not checkout_ok:
        print(f"sase_hg_update failed: {checkout_err}", file=sys.stderr)
        return False

    print("Workspace ready")
    return True


def all_steps_hidden(artifacts_dir: str) -> bool:
    """Check if every step in a workflow was hidden.

    Reads workflow_state.json from the artifacts directory and returns True
    when all steps have ``hidden: true``.  Returns False when the state file
    is missing, unreadable, or contains at least one visible step.
    """
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return False
    steps = data.get("steps", [])
    if not steps:
        return False
    return all(step.get("hidden", False) for step in steps)


def write_done_marker(
    artifacts_dir: str,
    cl_name: str,
    project_file: str,
    timestamp: str,
    exit_code: int,
    *,
    workspace_num: int | None = None,
    response_path: str | None = None,
    diff_path: str | None = None,
) -> None:
    """Write a done.json marker to an axe runner's artifacts directory.

    Args:
        artifacts_dir: Path to the artifacts directory.
        cl_name: Name of the ChangeSpec / CL.
        project_file: Path to the project file.
        timestamp: Timestamp in YYmmdd_HHMMSS format.
        exit_code: Exit code (0 for success).
        workspace_num: Optional workspace number.
        response_path: Optional path to the response/chat file.
        diff_path: Optional path to the diff file.
    """
    from sase.shared_utils import convert_timestamp_to_artifacts_format

    artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
    outcome = "completed" if exit_code == 0 else "failed"

    done_data: dict[str, object] = {
        "cl_name": cl_name,
        "project_file": project_file,
        "timestamp": timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "outcome": outcome,
        "hidden": True,
    }
    if workspace_num is not None:
        done_data["workspace_num"] = workspace_num
    if response_path:
        done_data["response_path"] = response_path
    if diff_path:
        done_data["diff_path"] = diff_path

    done_path = os.path.join(artifacts_dir, "done.json")
    try:
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(done_data, f, indent=2)
        print(f"Done marker written to: {done_path}")
    except Exception as e:
        print(f"Warning: Failed to write done marker: {e}")


def finalize_axe_runner(
    project_file: str,
    changespec_name: str,
    proposal_id: str | None,
    exit_code: int,
    update_suffix_fn: Callable[[ChangeSpec, str, str | None, int], None],
) -> None:
    """Common finalization logic for axe runners.

    Args:
        project_file: Path to the project file.
        changespec_name: Name of the ChangeSpec.
        proposal_id: Proposal ID if successful, None otherwise.
        exit_code: Exit code (0 for success).
        update_suffix_fn: Callback to update the suffix (hook or comment).
            Receives (changespec, project_file, proposal_id, exit_code).
    """
    # Update suffix based on result
    try:
        changespecs = parse_project_file(project_file)
        for cs in changespecs:
            if cs.name == changespec_name:
                update_suffix_fn(cs, project_file, proposal_id, exit_code)
                break
    except Exception as e:
        print(f"Warning: Failed to update suffix: {e}")

    # Write completion marker
    print()
    print(f"===WORKFLOW_COMPLETE=== PROPOSAL_ID: {proposal_id} EXIT_CODE: {exit_code}")
