"""Shared utilities for axe runner scripts."""

import json
import logging
import os
import signal
import sys
from collections.abc import Callable

from sase.ace.agent_tags import REVIEW_AGENT_TAG
from sase.ace.changespec import ChangeSpec, parse_project_file
from sase.vcs_provider import get_vcs_provider

logger = logging.getLogger(__name__)

# Global state for SIGTERM handler
_killed_state: dict[str, bool] = {"killed": False}


def was_killed() -> bool:
    """Check if the process received SIGTERM."""
    return _killed_state["killed"]


def install_sigterm_handler(
    description: str = "process", *, soft: bool = False
) -> None:
    """Install a SIGTERM handler that sets killed flag and exits gracefully.

    The handler uses sys.exit() instead of re-raising SIGTERM so that
    finally blocks run, ensuring workspace cleanup happens before exit.

    Args:
        description: What was killed (e.g., "agent", "mentor", "workflow").
        soft: When True, set the killed flag but don't call sys.exit().
            This allows the caller to detect the kill and handle it
            (e.g., check for marker files before deciding what to do).
    """

    def _handler(_signum: int, _frame: object) -> None:
        _killed_state["killed"] = True
        print(f"\nReceived SIGTERM - {description} was killed", file=sys.stderr)
        if not soft:
            sys.exit(128 + signal.SIGTERM)

    signal.signal(signal.SIGTERM, _handler)


def reset_killed() -> None:
    """Clear the killed flag between follow-up loop iterations."""
    _killed_state["killed"] = False


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
    from sase.workflows.commit_utils import run_sase_hg_clean

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
    """Check if every step that actually ran in a workflow was hidden.

    Reads workflow_state.json from the artifacts directory and returns True
    when all steps that ran have ``hidden: true``.  Skipped steps (e.g. due
    to an ``if`` condition evaluating to false) are not considered since they
    did not actually run.  Returns False when the state file is missing,
    unreadable, or contains at least one visible step that ran.
    """
    state_path = os.path.join(artifacts_dir, "workflow_state.json")
    try:
        with open(state_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        logger.debug(
            "all_steps_hidden: state file missing or unreadable: %s", state_path
        )
        return False
    steps = data.get("steps", [])
    if not steps:
        logger.debug("all_steps_hidden: no steps in %s", state_path)
        return False
    result = all(
        step.get("hidden", False) or step.get("status") == "skipped" for step in steps
    )
    logger.debug(
        "all_steps_hidden: %s — steps: %s",
        result,
        [(s.get("name"), s.get("status"), s.get("hidden")) for s in steps],
    )
    return result


def _write_agent_meta(
    artifacts_dir: str,
    *,
    model: str | None = None,
    llm_provider: str | None = None,
    vcs_provider: str | None = None,
    tag: str | None = None,
) -> None:
    """Write agent_meta.json to an axe runner's artifacts directory.

    This provides model/VCS metadata so the Agents tab can display it
    for axe-spawned agents (mentor, fix-hook, crs, summarize-hook).

    Args:
        artifacts_dir: Path to the artifacts directory.
        model: Model name (e.g., "gemini-3.1-pro-preview").
        llm_provider: LLM provider name (e.g., "gemini").
        vcs_provider: VCS provider display name (e.g., "Mercurial").
        tag: Optional Agents-tab grouping tag.
    """
    meta: dict[str, object] = {"pid": os.getpid()}
    if model:
        meta["model"] = model
    if llm_provider:
        meta["llm_provider"] = llm_provider
    if vcs_provider:
        meta["vcs_provider"] = vcs_provider
    if tag:
        meta["tag"] = tag

    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    try:
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)
    except Exception as e:
        print(f"Warning: Failed to write agent_meta.json: {e}")


def detect_and_write_agent_meta(
    artifacts_dir: str,
    project_file: str,
    *,
    tag: str | None = None,
) -> None:
    """Detect model/VCS metadata and write agent_meta.json.

    Convenience wrapper that detects the current LLM provider, model, and
    VCS provider from the project file, then writes agent_meta.json.

    Args:
        artifacts_dir: Path to the artifacts directory.
        project_file: Path to the project file (used for VCS detection).
        tag: Optional Agents-tab grouping tag.
    """
    from sase.llm_provider.registry import get_default_provider_name, get_provider
    from sase.workspace_provider import detect_workflow_type, get_display_name

    # Detect model and LLM provider
    llm_provider = get_default_provider_name()
    try:
        provider = get_provider()
        model = provider.resolve_model_name()
    except Exception:
        model = None

    # Detect VCS provider
    try:
        vcs_type = detect_workflow_type(project_file)
        vcs_provider = get_display_name(vcs_type)
    except (ValueError, Exception):
        vcs_provider = None

    _write_agent_meta(
        artifacts_dir,
        model=model,
        llm_provider=llm_provider,
        vcs_provider=vcs_provider,
        tag=tag,
    )


def detect_write_and_persist_review_agent_meta(
    artifacts_dir: str,
    project_file: str,
    cl_name: str,
    *,
    raw_suffix: str | None = None,
) -> None:
    """Write review-tagged metadata and persist the tag for a runner identity.

    Specialized review runners (CRS, mentor, fix-hook) bypass the generic
    prompt directive parser, so they need to write the same observable tag
    state that a ``%tag:review`` launch would have produced.
    """
    detect_and_write_agent_meta(artifacts_dir, project_file, tag=REVIEW_AGENT_TAG)

    from sase.ace.agent_tags import update_agent_tag
    from sase.ace.tui.models.agent import AgentType

    identity_suffix = raw_suffix
    if identity_suffix is None:
        identity_suffix = os.path.basename(artifacts_dir.rstrip(os.sep)) or None
    update_agent_tag((AgentType.RUNNING, cl_name, identity_suffix), REVIEW_AGENT_TAG)


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
    error: str | None = None,
    traceback_str: str | None = None,
    output_path: str | None = None,
    hidden: bool = True,
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
        error: Optional error summary string.
        traceback_str: Optional formatted traceback string.
        output_path: Optional path to the stdout/stderr output log.
        hidden: Whether the completed row should be hidden by default.
    """
    from sase.artifacts import convert_timestamp_to_artifacts_format

    artifacts_timestamp = convert_timestamp_to_artifacts_format(timestamp)
    outcome = "completed" if exit_code == 0 else "failed"

    done_data: dict[str, object] = {
        "cl_name": cl_name,
        "project_file": project_file,
        "timestamp": timestamp,
        "artifacts_timestamp": artifacts_timestamp,
        "outcome": outcome,
    }
    if hidden:
        done_data["hidden"] = True
    if workspace_num is not None:
        done_data["workspace_num"] = workspace_num
    if response_path:
        done_data["response_path"] = response_path
    if diff_path:
        done_data["diff_path"] = diff_path
    if error:
        done_data["error"] = error
    if traceback_str:
        done_data["traceback"] = traceback_str
    if output_path:
        done_data["output_path"] = output_path

    done_path = os.path.join(artifacts_dir, "done.json")
    try:
        with open(done_path, "w", encoding="utf-8") as f:
            json.dump(done_data, f, indent=2)
        print(f"Done marker written to: {done_path}")
    except Exception as e:
        print(f"Warning: Failed to write done marker: {e}")


def read_agent_meta(artifacts_dir: str) -> dict[str, str | None]:
    """Read agent_meta.json and return model/provider info.

    Returns:
        Dict with ``model`` and ``llm_provider`` keys (values may be None).
    """
    meta_path = os.path.join(artifacts_dir, "agent_meta.json")
    result: dict[str, str | None] = {"model": None, "llm_provider": None}
    try:
        with open(meta_path, encoding="utf-8") as f:
            data = json.load(f)
        result["model"] = data.get("model")
        result["llm_provider"] = data.get("llm_provider")
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return result


def write_error_report(
    artifacts_dir: str,
    *,
    agent_model: str | None,
    agent_llm_provider: str | None,
    workflow_name: str,
    cl_name: str,
    duration: str,
    error_summary: str,
    error_traceback: str | None,
) -> str | None:
    """Write a formatted error report to the artifacts directory.

    Returns the file path, or None if writing failed.
    """
    try:
        from sase.llm_provider.registry import format_provider_model_label

        report_path = os.path.join(artifacts_dir, "error_report.md")
        label = format_provider_model_label(agent_llm_provider, agent_model)

        lines = [
            "# Agent Error Report",
            "",
            "## Summary",
            "",
            "| Field | Value |",
            "|-------|-------|",
            f"| Model | {label} |",
            f"| Workflow | {workflow_name} |",
            f"| CL | {cl_name} |",
            f"| Duration | {duration} |",
            "",
            "## Error",
            "",
            "```",
            error_summary,
            "```",
        ]

        if error_traceback:
            lines.extend(
                [
                    "",
                    "## Traceback",
                    "",
                    "```",
                    error_traceback.rstrip(),
                    "```",
                ]
            )

        lines.append("")
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return report_path
    except Exception:
        return None


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
