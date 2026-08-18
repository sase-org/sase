"""Workflow starting/launching logic for the axe scheduler."""

import os
import subprocess
import sys
import time
from collections.abc import Callable

from sase.workflows.commit_utils import run_sase_hg_clean
from sase.core.patch import strip_reverted_suffix
from sase.core.paths import make_safe_filename, sharded_path
from sase.running_field import (
    WorkspaceClaimError,
    claim_next_axe_workspace,
    get_workspace_directory_for_num,
    release_workspace,
    transfer_workspace_claim,
)
from sase.vcs_provider import get_vcs_provider

from ...patch import (
    Patch,
    CommentEntry,
    HookEntry,
    count_agent_runners_global,
    get_current_and_proposal_entry_ids,
)
from ...comments import (
    set_comment_suffix,
)
from ...hooks import (
    generate_timestamp,
    get_failing_hook_entries_for_fix,
    get_failing_hook_entries_for_summarize,
    get_hook_output_path,
    set_hook_suffix,
)

# Type alias for logging callback
LogCallback = Callable[[str, str | None], None]


def get_workflow_output_path(name: str, workflow_type: str, timestamp: str) -> str:
    """Get the output file path for a workflow run.

    Args:
        name: The Patch name.
        workflow_type: The workflow type ("crs" or "fix-hook").
        timestamp: The timestamp in YYmmdd_HHMMSS format.

    Returns:
        Full path to the workflow output file.
    """
    safe_name = make_safe_filename(strip_reverted_suffix(name))
    filename = f"{safe_name}_{workflow_type}-{timestamp}.txt"
    return sharded_path("workflows", filename)


def get_project_basename(patch: Patch) -> str:
    """Extract project basename from Patch file path."""
    return patch.project_basename


def _crs_workflow_eligible(patch: Patch) -> list[CommentEntry]:
    """Get CRS-eligible comment entries (no suffix).

    Args:
        patch: The Patch to check.

    Returns:
        List of CommentEntry objects eligible for CRS workflow.
    """
    eligible: list[CommentEntry] = []
    if patch.comments:
        for entry in patch.comments:
            if entry.reviewer == "critique" and entry.suffix is None:
                eligible.append(entry)
    return eligible


def _fix_hook_workflow_eligible(
    patch: Patch,
) -> list[tuple[HookEntry, str]]:
    """Get fix-hook-eligible hooks (FAILED status, no suffix) for all non-historical entries.

    Args:
        patch: The Patch to check.

    Returns:
        List of (HookEntry, entry_id) tuples eligible for fix-hook workflow.
    """
    if not patch.hooks:
        return []
    entry_ids = get_current_and_proposal_entry_ids(patch)
    return get_failing_hook_entries_for_fix(patch.hooks, entry_ids)


def _summarize_hook_workflow_eligible(
    patch: Patch,
) -> list[tuple[HookEntry, str]]:
    """Get summarize-hook-eligible hooks (FAILED status, proposal entry, no suffix).

    Args:
        patch: The Patch to check.

    Returns:
        List of (HookEntry, entry_id) tuples eligible for summarize-hook workflow.
    """
    if not patch.hooks:
        return []
    entry_ids = get_current_and_proposal_entry_ids(patch)
    return get_failing_hook_entries_for_summarize(patch.hooks, entry_ids)


def _start_crs_workflow(
    patch: Patch,
    comment_entry: CommentEntry,
    log: LogCallback,
) -> str | None:
    """Start CRS workflow as a background process.

    Claims the workspace atomically under this process, materializes the
    checkout, then transfers the claim to the spawned child PID. If spawn
    or transfer fails, the claim is released and any child is terminated.

    Args:
        patch: The Patch to run CRS for.
        comment_entry: The comment entry to process.
        log: Logging callback.

    Returns:
        Update message if started, None if failed.
    """
    from sase.vcs_provider import detect_vcs_family
    from sase.workspace_provider.utils import (
        ensure_workspace_checkout,
        parse_workspace_dir,
    )

    project_basename = get_project_basename(patch)
    timestamp = generate_timestamp()
    workflow_name = f"axe(crs)-{comment_entry.reviewer}-{timestamp}"
    parent_pid = os.getpid()
    try:
        workspace_num = claim_next_axe_workspace(
            patch.file_path,
            workflow_name,
            parent_pid,
            patch.name,
            artifacts_timestamp=timestamp,
        )
    except WorkspaceClaimError as exc:
        log(
            f"Warning: Failed to claim workspace for CRS on {patch.name}: {exc}",
            "yellow",
        )
        return None

    def _release_crs_claim() -> None:
        release_workspace(patch.file_path, workspace_num, workflow_name, patch.name)

    # Detect VCS type and resolve workspace directory accordingly
    primary_dir = parse_workspace_dir(patch.file_path)
    raw_vcs = detect_vcs_family(primary_dir) if primary_dir else None

    if raw_vcs == "git":
        # Git: use clones from WORKSPACE_DIR
        if not primary_dir:
            log(
                f"[WS#{workspace_num}] Warning: WORKSPACE_DIR not set for git project",
                "yellow",
            )
            _release_crs_claim()
            return None
        try:
            workspace_dir = ensure_workspace_checkout(primary_dir, workspace_num)
        except RuntimeError as e:
            log(
                f"[WS#{workspace_num}] Warning: Failed to get git clone workspace: {e}",
                "yellow",
            )
            _release_crs_claim()
            return None

        # Clean workspace using VCS provider
        provider = get_vcs_provider(workspace_dir)
        clean_success, clean_error = provider.stash_and_clean(
            f"{patch.name}-crs", workspace_dir
        )
        if not clean_success:
            log(
                f"[WS#{workspace_num}] Warning: stash_and_clean failed: {clean_error}",
                "yellow",
            )
    else:
        # Hg: use existing workspace directory logic
        try:
            workspace_dir, _ = get_workspace_directory_for_num(
                workspace_num, project_basename
            )
        except RuntimeError as e:
            log(
                f"[WS#{workspace_num}] Warning: Failed to get workspace directory: {e}",
                "yellow",
            )
            _release_crs_claim()
            return None

        if not os.path.isdir(workspace_dir):
            log(
                f"[WS#{workspace_num}] Warning: Workspace directory not found: {workspace_dir}",
                "yellow",
            )
            _release_crs_claim()
            return None

        # Clean workspace before switching branches
        clean_success, clean_error = run_sase_hg_clean(
            workspace_dir, f"{patch.name}-crs"
        )
        if not clean_success:
            log(
                f"[WS#{workspace_num}] Warning: sase_hg_clean failed: {clean_error}",
                "yellow",
            )

        provider = get_vcs_provider(workspace_dir)

    # Switch to the Patch's branch
    resolved = provider.resolve_revision(patch.name, project_basename, workspace_dir)
    checkout_ok, checkout_err = provider.checkout(resolved, workspace_dir)
    if not checkout_ok:
        log(
            f"[WS#{workspace_num}] Warning: sase_hg_update failed for "
            f"{patch.name}: {checkout_err}",
            "yellow",
        )
        _release_crs_claim()
        return None

    # Expand the comments file path (replace ~ with home directory)
    comments_file = comment_entry.file_path
    if comments_file and comments_file.startswith("~"):
        comments_file = os.path.expanduser(comments_file)

    # Get output file path
    output_path = get_workflow_output_path(patch.name, "crs", timestamp)

    # Build the runner script path (use abspath to handle relative __file__)
    runner_script = os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ),
        "axe",
        "crs_runner.py",
    )

    # Start the background process first to get actual PID
    try:
        env = {**os.environ, "SASE_AGENT_OUTPUT_PATH": output_path}
        with open(output_path, "w") as output_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    runner_script,
                    patch.name,
                    patch.file_path,
                    comments_file or "",
                    comment_entry.reviewer,
                    timestamp,
                ],
                cwd=workspace_dir,
                stdout=output_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
            pid = proc.pid
    except Exception as e:
        log(
            f"[WS#{workspace_num}] Warning: Failed to start CRS subprocess: {e}",
            "yellow",
        )
        _release_crs_claim()
        return None

    claim_result = transfer_workspace_claim(
        patch.file_path,
        workspace_num,
        from_pid=parent_pid,
        to_pid=pid,
        new_workflow=workflow_name,
        new_artifacts_timestamp=timestamp,
        cl_name=patch.name,
    )
    if not claim_result.success:
        log(
            f"[WS#{workspace_num}] Warning: Failed to transfer workspace for CRS on "
            f"{patch.name}: {claim_result.error or 'unknown reason'}, "
            "terminating subprocess",
            "yellow",
        )
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
        _release_crs_claim()
        return None

    # Set timestamp suffix on comment entry to indicate workflow is running
    # Include PID in suffix for process management
    if patch.comments:
        set_comment_suffix(
            patch.file_path,
            patch.name,
            comment_entry.reviewer,
            f"crs-{pid}-{timestamp}",
            patch.comments,
            suffix_type="running_agent",
        )

    return f"CRS workflow -> RUNNING for [{comment_entry.reviewer}]"


def start_fix_hook_workflow(
    patch: Patch,
    hook: HookEntry,
    entry_id: str,
    log: LogCallback,
) -> str | None:
    """Start fix-hook workflow as a background process.

    The runner uses the project provider's embedded workflow for workspace management.

    Args:
        patch: The Patch to run fix-hook for.
        hook: The hook to fix.
        entry_id: The history entry ID for the failing status line.
        log: Logging callback.

    Returns:
        Update message if started, None if failed.
    """
    timestamp = generate_timestamp()

    # ATOMIC CLAIM: Check eligibility and claim hook under lock to prevent race condition
    # where two processes both see "summarize_complete" and start fix-hook agents
    from ...hooks import try_claim_hook_for_fix

    claiming_suffix = f"claiming-{timestamp}"
    existing_summary = try_claim_hook_for_fix(
        patch.file_path,
        patch.name,
        hook.command,
        entry_id,
        claiming_suffix,
    )
    if not existing_summary:
        # Either not eligible or already claimed by another process
        log(
            f"Fix-hook for {hook.display_command} ({entry_id}) "
            "not eligible or already claimed",
            "dim",
        )
        return None

    # Get hook output path for the failing hook's specific entry
    hook_output_path = ""
    sl = hook.get_status_line_for_stitch(entry_id)
    if sl and sl.timestamp:
        hook_output_path = get_hook_output_path(patch.name, sl.timestamp)

    # Get output file path for workflow
    output_path = get_workflow_output_path(patch.name, "fix-hook", timestamp)

    # Build the runner script path (use abspath to handle relative __file__)
    runner_script = os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ),
        "axe",
        "fix_hook_runner.py",
    )

    # Start the background process first to get actual PID
    try:
        env = {**os.environ, "SASE_AGENT_OUTPUT_PATH": output_path}
        with open(output_path, "w") as output_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    runner_script,
                    patch.name,
                    patch.file_path,
                    hook.command,
                    hook_output_path,
                    output_path,
                    entry_id,
                    timestamp,  # Pass timestamp for artifacts directory sync
                ],
                cwd=os.path.expanduser("~"),
                stdout=output_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
            pid = proc.pid
    except Exception as e:
        log(
            f"Warning: Failed to start fix-hook subprocess: {e}",
            "yellow",
        )
        return None

    # Set timestamp suffix on hook status line to indicate workflow is running
    # Include PID in suffix for process management, preserve summary in compound suffix
    # Pass hooks=None to force re-read with lock, avoiding stale data race condition
    # when multiple fix-hooks are started in the same loop cycle
    set_hook_suffix(
        patch.file_path,
        patch.name,
        hook.command,
        f"fix_hook-{pid}-{timestamp}",
        hooks=None,  # Re-read fresh data under lock
        entry_id=entry_id,
        suffix_type="running_agent",
        summary=existing_summary,
    )

    return f"fix-hook workflow -> RUNNING for '{hook.display_command}' ({entry_id})"


def _start_summarize_hook_workflow(
    patch: Patch,
    hook: HookEntry,
    entry_id: str,
    log: LogCallback,
) -> str | None:
    """Start summarize-hook workflow as a background process.

    This workflow does NOT require a workspace - it only reads the hook output
    file and calls the summarize agent.

    Args:
        patch: The Patch to run summarize-hook for.
        hook: The hook to summarize.
        entry_id: The history entry ID for the failing status line.
        log: Logging callback.

    Returns:
        Update message if started, None if failed.
    """
    timestamp = generate_timestamp()

    # Get hook output path for the failing hook's specific entry
    hook_output_path = ""
    sl = hook.get_status_line_for_stitch(entry_id)
    if sl and sl.timestamp:
        hook_output_path = get_hook_output_path(patch.name, sl.timestamp)

    if not hook_output_path or not os.path.exists(hook_output_path):
        # No output file to summarize - set a default suffix
        log(
            f"Warning: No hook output file for summarize-hook on {patch.name}",
            "yellow",
        )
        set_hook_suffix(
            patch.file_path,
            patch.name,
            hook.command,
            "Hook Command Failed",
            hooks=None,  # Re-read fresh data under lock
            entry_id=entry_id,
            suffix_type="error",
        )
        return f"summarize-hook workflow '{hook.display_command}' ({entry_id}) -> no output to summarize"

    # Get output file path for workflow
    output_path = get_workflow_output_path(patch.name, "summarize-hook", timestamp)

    # Build the runner script path (use abspath to handle relative __file__)
    runner_script = os.path.join(
        os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        ),
        "axe",
        "summarize_hook_runner.py",
    )

    try:
        # Start the background process and capture PID
        env = {**os.environ, "SASE_AGENT_OUTPUT_PATH": output_path}
        with open(output_path, "w") as output_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    runner_script,
                    patch.name,
                    patch.file_path,
                    hook.command,
                    hook_output_path,
                    output_path,
                    entry_id,
                    timestamp,  # Pass timestamp for artifacts directory sync
                ],
                stdout=output_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=env,
            )
            pid = proc.pid

        # Set timestamp suffix on hook status line to indicate workflow is running
        # Include PID in suffix for process management
        set_hook_suffix(
            patch.file_path,
            patch.name,
            hook.command,
            f"summarize_hook-{pid}-{timestamp}",
            hooks=None,  # Re-read fresh data under lock
            entry_id=entry_id,
            suffix_type="running_agent",
        )

        return f"summarize-hook workflow -> RUNNING for '{hook.display_command}' ({entry_id})"

    except Exception as e:
        log(f"Warning: Error starting summarize-hook workflow: {e}", "yellow")
        return None


def start_stale_workflows(
    patch: Patch,
    log: LogCallback,
    max_runners: int = 5,
    runners_started_this_cycle: int = 0,
) -> tuple[list[str], int, list[str]]:
    """Start all stale CRS, fix-hook, and summarize-hook workflows for a Patch.

    Args:
        patch: The Patch to check.
        log: Logging callback.
        max_runners: Maximum concurrent runners (hooks, agents, mentors) globally (default: 5).
        runners_started_this_cycle: Number of runners already started this cycle (across
            all Patches). Added to the global count to avoid exceeding the limit.

    Returns:
        Tuple of (update_messages, agents_started_count, started_workflow_identifiers).
    """
    updates: list[str] = []
    started: list[str] = []

    # Don't start workflows for terminal statuses
    if patch.status in ("Reverted", "Submitted", "Archived"):
        return updates, 0, started

    crs_eligible = _crs_workflow_eligible(patch)
    fix_hook_eligible = _fix_hook_workflow_eligible(patch)
    summarize_hook_eligible = _summarize_hook_workflow_eligible(patch)
    if not crs_eligible and not fix_hook_eligible and not summarize_hook_eligible:
        return updates, 0, started

    # Check global concurrency limit before starting any workflows
    # Include runners started this cycle (across all Patches) that aren't
    # yet written to disk
    current_running = count_agent_runners_global() + runners_started_this_cycle
    if current_running >= max_runners:
        log(
            f"Skipping workflow start: {current_running} runners running "
            f"(limit: {max_runners})",
            "dim",
        )
        return updates, 0, started

    available_slots = max_runners - current_running
    agents_started = 0

    # Start CRS workflows for eligible comment entries
    for entry in crs_eligible:
        if agents_started >= available_slots:
            log(
                f"Reached runner limit ({max_runners}), deferring remaining workflows",
                "dim",
            )
            break
        result = _start_crs_workflow(patch, entry, log)
        if result:
            updates.append(result)
            started.append(f"crs:{entry.reviewer}")
            agents_started += 1
        # Small delay between workflow starts to ensure unique timestamps
        if result:
            time.sleep(1)

    # Start fix-hook workflows for all eligible failing hooks (non-proposal entries)
    for hook, entry_id in fix_hook_eligible:
        if agents_started >= available_slots:
            log(
                f"Reached runner limit ({max_runners}), deferring remaining workflows",
                "dim",
            )
            break
        result = start_fix_hook_workflow(patch, hook, entry_id, log)
        if result:
            updates.append(result)
            started.append(f"fix-hook:{hook.command}:{entry_id}")
            agents_started += 1
        # Small delay between workflow starts to ensure unique timestamps
        if result:
            time.sleep(1)

    # Start summarize-hook workflows for proposal entry failures
    for hook, entry_id in summarize_hook_eligible:
        if agents_started >= available_slots:
            log(
                f"Reached runner limit ({max_runners}), deferring remaining workflows",
                "dim",
            )
            break
        result = _start_summarize_hook_workflow(patch, hook, entry_id, log)
        if result:
            updates.append(result)
            started.append(f"summarize-hook:{hook.command}:{entry_id}")
            agents_started += 1
        # Small delay between workflow starts to ensure unique timestamps
        if result:
            time.sleep(1)

    return updates, agents_started, started
