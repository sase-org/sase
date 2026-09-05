"""Process management utilities for hooks."""

import os
import re
import signal
import subprocess
from collections.abc import Callable

from ..patch import (
    Patch,
    CommentEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
    extract_pid_from_agent_suffix,
)
from .timestamps import get_current_timestamp

_SUBPROCESS_POPEN = subprocess.Popen


def _try_kill_process_group(pid: int) -> bool:
    """Try to kill a process group via SIGTERM.

    Args:
        pid: The process group ID to kill.

    Returns:
        True always (process was killed, already dead, or inaccessible).
    """
    try:
        os.killpg(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        pass
    return True


def is_process_running(pid: int) -> bool:
    """Check if a process with the given PID is still running.

    Also detects zombie processes, which appear alive to ``os.kill(pid, 0)``
    but are effectively dead.

    Args:
        pid: The process ID to check.

    Returns:
        True if the process is running, False otherwise.
    """
    try:
        os.kill(pid, 0)  # Signal 0 doesn't kill, just checks existence
    except ProcessLookupError:
        return False
    except PermissionError:
        # Process exists but we don't have permission to signal it
        return True

    # On Linux, check /proc/<pid>/status for zombie state.
    # Zombies have exited but haven't been reaped by their parent;
    # os.kill(pid, 0) still succeeds for them.
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("State:"):
                    return "Z" not in line
    except (FileNotFoundError, PermissionError, OSError):
        state = _ps_process_state(pid)
        if state is not None:
            return bool(state) and "Z" not in state

    return True


def _ps_process_state(pid: int) -> str | None:
    """Return a portable process state from ``ps`` when ``/proc`` is absent."""
    try:
        process = _SUBPROCESS_POPEN(
            ["ps", "-o", "stat=", "-p", str(pid)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            stdout, _stderr = process.communicate(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate()
            return None
    except Exception:  # noqa: BLE001 - process liveness is best-effort metadata
        return None
    if process.returncode != 0:
        return ""
    return stdout.strip()


def kill_running_hook_processes(
    patch: Patch,
    skip_dollar: bool = False,
) -> list[tuple[HookEntry, HookStatusLine, int]]:
    """Kill all running hook processes for a Patch.

    Finds all hooks with suffix_type="running_process", extracts the PID,
    and sends SIGTERM to terminate the process group.

    Args:
        patch: The Patch to kill running hooks for.
        skip_dollar: If True, skip $-prefixed hooks (skip_proposal_runs).

    Returns:
        List of (hook, status_line, pid) tuples for processes that were killed
        (or attempted to kill). Used to update suffix to killed_process.
    """
    killed: list[tuple[HookEntry, HookStatusLine, int]] = []

    if not patch.hooks:
        return killed

    for hook in patch.hooks:
        if skip_dollar and hook.skip_proposal_runs:
            continue
        if not hook.status_lines:
            continue
        for sl in hook.status_lines:
            if sl.suffix_type == "running_process" and sl.suffix:
                try:
                    pid = int(sl.suffix)
                except ValueError:
                    continue

                _try_kill_process_group(pid)
                killed.append((hook, sl, pid))

    return killed


def mark_hooks_as_killed(
    hooks: list[HookEntry],
    killed_processes: list[tuple[HookEntry, HookStatusLine, int]],
    description: str,
) -> list[HookEntry]:
    """Update hook status lines to mark killed processes as DEAD.

    Changes suffix_type from "running_process" to "killed_process" and
    updates the suffix to include a timestamped description.

    Args:
        hooks: List of all HookEntry objects.
        killed_processes: List of (hook, status_line, pid) from kill operation.
        description: Description of why the hook was killed
            (e.g., "Killed hook running on reverted Patch.").

    Returns:
        Updated list of HookEntry objects with modified suffix_type.
    """
    timestamp = get_current_timestamp()
    formatted_description = f"[{timestamp}] {description}"

    # Build lookup set of (command, stitch_num, pid) for killed processes
    killed_lookup: set[tuple[str, str, str]] = {
        (hook.command, sl.stitch_num, str(pid)) for hook, sl, pid in killed_processes
    }

    updated_hooks: list[HookEntry] = []
    for hook in hooks:
        if not hook.status_lines:
            updated_hooks.append(hook)
            continue

        updated_status_lines: list[HookStatusLine] = []
        for sl in hook.status_lines:
            if (hook.command, sl.stitch_num, sl.suffix) in killed_lookup:
                # Create new status line with DEAD status and description
                new_suffix = f"{sl.suffix} | {formatted_description}"
                updated_sl = HookStatusLine(
                    stitch_num=sl.stitch_num,
                    timestamp=sl.timestamp,
                    status="DEAD",
                    duration=sl.duration,
                    suffix=new_suffix,
                    suffix_type="killed_process",
                )
                updated_status_lines.append(updated_sl)
            else:
                updated_status_lines.append(sl)

        updated_hook = HookEntry(
            command=hook.command,
            status_lines=updated_status_lines,
        )
        updated_hooks.append(updated_hook)

    return updated_hooks


def kill_running_agent_processes(
    patch: Patch,
) -> tuple[
    list[tuple[HookEntry, HookStatusLine, int]],
    list[tuple[CommentEntry, int]],
]:
    """Kill all running agent processes for a Patch.

    Finds all hooks and comment entries with suffix_type="running_agent",
    extracts the PID from the suffix (format: <agent>-<PID>-<timestamp>),
    and sends SIGTERM to terminate the process group.

    Args:
        patch: The Patch to kill running agents for.

    Returns:
        Tuple of:
        - List of (hook, status_line, pid) tuples for killed hook agents
        - List of (stitch, pid) tuples for killed comment agents
    """
    killed_hooks: list[tuple[HookEntry, HookStatusLine, int]] = []
    killed_comments: list[tuple[CommentEntry, int]] = []

    # Kill agent processes on hooks (fix_hook, summarize_hook workflows)
    if patch.hooks:
        for hook in patch.hooks:
            if not hook.status_lines:
                continue
            for sl in hook.status_lines:
                if sl.suffix_type == "running_agent" and sl.suffix:
                    pid = extract_pid_from_agent_suffix(sl.suffix)
                    if pid is None:
                        continue

                    _try_kill_process_group(pid)
                    killed_hooks.append((hook, sl, pid))

    # Kill agent processes on comments (crs workflow)
    if patch.comments:
        for comment in patch.comments:
            if comment.suffix_type == "running_agent" and comment.suffix:
                pid = extract_pid_from_agent_suffix(comment.suffix)
                if pid is None:
                    continue

                _try_kill_process_group(pid)
                killed_comments.append((comment, pid))

    return killed_hooks, killed_comments


def mark_hook_agents_as_killed(
    hooks: list[HookEntry],
    killed_agents: list[tuple[HookEntry, HookStatusLine, int]],
) -> list[HookEntry]:
    """Update hook status lines to mark killed agent processes.

    Changes suffix_type from "running_agent" to "killed_agent" for
    the specified status lines.

    Args:
        hooks: List of all HookEntry objects.
        killed_agents: List of (hook, status_line, pid) from kill operation.

    Returns:
        Updated list of HookEntry objects with modified suffix_type.
    """
    # Build lookup set of (command, stitch_num, suffix) for killed agents
    killed_lookup: set[tuple[str, str, str]] = {
        (hook.command, sl.stitch_num, sl.suffix or "")
        for hook, sl, pid in killed_agents
    }

    updated_hooks: list[HookEntry] = []
    for hook in hooks:
        if not hook.status_lines:
            updated_hooks.append(hook)
            continue

        updated_status_lines: list[HookStatusLine] = []
        for sl in hook.status_lines:
            if (hook.command, sl.stitch_num, sl.suffix or "") in killed_lookup:
                # Create new status line with killed_agent type
                updated_sl = HookStatusLine(
                    stitch_num=sl.stitch_num,
                    timestamp=sl.timestamp,
                    status=sl.status,
                    duration=sl.duration,
                    suffix=sl.suffix,
                    suffix_type="killed_agent",
                )
                updated_status_lines.append(updated_sl)
            else:
                updated_status_lines.append(sl)

        updated_hook = HookEntry(
            command=hook.command,
            status_lines=updated_status_lines,
        )
        updated_hooks.append(updated_hook)

    return updated_hooks


def kill_running_processes_for_hooks(
    hooks: list[HookEntry] | None,
    hook_indices: set[int],
) -> int:
    """Kill running processes/agents for specific hooks by index.

    This function is used when removing hook status lines via the "h" option
    (rerun or delete). It kills any processes/agents associated with the
    hooks being modified.

    Unlike kill_running_hook_processes() and kill_running_agent_processes()
    which operate on ALL hooks in a Patch, this function targets only
    specific hooks by index.

    Args:
        hooks: List of all HookEntry objects.
        hook_indices: Set of hook indices to check and kill.

    Returns:
        Count of processes/agents killed.
    """
    if not hooks:
        return 0

    killed_count = 0

    for idx in hook_indices:
        if idx < 0 or idx >= len(hooks):
            continue

        hook = hooks[idx]
        if not hook.status_lines:
            continue

        for sl in hook.status_lines:
            pid: int | None = None

            if sl.suffix_type == "running_process" and sl.suffix:
                try:
                    pid = int(sl.suffix)
                except ValueError:
                    continue
            elif sl.suffix_type == "running_agent" and sl.suffix:
                pid = extract_pid_from_agent_suffix(sl.suffix)

            if pid is not None:
                _try_kill_process_group(pid)
                killed_count += 1

    return killed_count


def kill_running_mentor_processes(
    patch: Patch,
    only_entry_ids: set[str] | None = None,
) -> list[tuple[MentorEntry, MentorStatusLine, int]]:
    """Kill running mentor processes for a Patch.

    Finds mentors with suffix_type="running_agent", extracts the PID
    from the suffix (format: mentor_<name>-<PID>-<timestamp>),
    and sends SIGTERM to terminate the process group.

    Args:
        patch: The Patch to kill running mentors for.
        only_entry_ids: If provided, only kill mentors for these entry IDs.
            If None, kills ALL running mentors.

    Returns:
        List of (mentor_entry, status_line, pid) tuples for processes that
        were killed (or attempted to kill).
    """
    killed: list[tuple[MentorEntry, MentorStatusLine, int]] = []

    if not patch.mentors:
        return killed

    for entry in patch.mentors:
        if only_entry_ids is not None and entry.entry_id not in only_entry_ids:
            continue
        if not entry.status_lines:
            continue
        for sl in entry.status_lines:
            if sl.suffix_type == "running_agent" and sl.suffix:
                pid = extract_pid_from_agent_suffix(sl.suffix)
                if pid is None:
                    continue

                _try_kill_process_group(pid)
                killed.append((entry, sl, pid))

    return killed


def mark_mentor_agents_as_killed(
    mentors: list[MentorEntry],
    killed_agents: list[tuple[MentorEntry, MentorStatusLine, int]],
) -> list[MentorEntry]:
    """Update mentor status lines to mark killed agent processes.

    Changes suffix_type from "running_agent" to "killed_agent" for
    the specified status lines.

    Args:
        mentors: List of all MentorEntry objects.
        killed_agents: List of (mentor_entry, status_line, pid) from kill operation.

    Returns:
        Updated list of MentorEntry objects with modified suffix_type.
    """
    # Build lookup set of (entry_id, profile_name, mentor_name, suffix) for killed agents
    killed_lookup: set[tuple[str, str, str, str]] = {
        (entry.entry_id, sl.profile_name, sl.mentor_name, sl.suffix or "")
        for entry, sl, pid in killed_agents
    }

    updated_mentors: list[MentorEntry] = []
    for entry in mentors:
        if not entry.status_lines:
            updated_mentors.append(entry)
            continue

        updated_status_lines: list[MentorStatusLine] = []
        for sl in entry.status_lines:
            key = (entry.entry_id, sl.profile_name, sl.mentor_name, sl.suffix or "")
            if key in killed_lookup:
                # Create new status line with killed_agent type
                updated_sl = MentorStatusLine(
                    profile_name=sl.profile_name,
                    mentor_name=sl.mentor_name,
                    status=sl.status,
                    timestamp=sl.timestamp,
                    duration=sl.duration,
                    suffix=sl.suffix,
                    suffix_type="killed_agent",
                )
                updated_status_lines.append(updated_sl)
            else:
                updated_status_lines.append(sl)

        updated_entry = MentorEntry(
            entry_id=entry.entry_id,
            profiles=entry.profiles,
            status_lines=updated_status_lines,
        )
        updated_mentors.append(updated_entry)

    return updated_mentors


def extract_mentor_workflow_from_suffix(suffix: str) -> str | None:
    """Extract workflow name from mentor suffix.

    Args:
        suffix: Mentor suffix in format "mentor_{name}-{PID}-{timestamp}"

    Returns:
        Workflow name in format "axe(mentor)-{name}-{timestamp}" or None
    """
    match = re.match(r"^mentor_(.+)-\d+-(\d{6}_\d{6})$", suffix)
    if match:
        mentor_name = match.group(1)
        timestamp = match.group(2)
        return f"axe(mentor)-{mentor_name}-{timestamp}"
    return None


def kill_and_persist_all_running_processes(
    patch: Patch,
    project_file: str,
    cl_name: str,
    kill_reason: str,
    log_fn: Callable[[str], None] | None = None,
) -> None:
    """Kill all running hook/agent/mentor processes and persist updates.

    This is a convenience function that orchestrates killing all running
    processes (hooks, agents, mentors) for a Patch, marking them as
    killed, persisting updates to the project file, and releasing any
    workspaces claimed by killed mentor processes.

    Args:
        patch: The Patch to kill processes for.
        project_file: Path to the project file.
        cl_name: The Patch name.
        kill_reason: Description of why processes are being killed
            (e.g., "Killed hook running on reverted Patch.").
        log_fn: Optional callback for logging messages.
    """
    # Lazy imports to avoid circular dependencies
    from ..comments.operations import (
        mark_comment_agents_as_killed,
        update_patch_comments_field,
    )
    from ..mentors import update_patch_mentors_field
    from .persistence import update_patch_hooks_field

    # Kill running hook processes
    killed_processes = kill_running_hook_processes(patch)
    if killed_processes:
        if log_fn:
            log_fn(f"Killed {len(killed_processes)} running hook process(es)")
        if patch.hooks:
            updated_hooks = mark_hooks_as_killed(
                patch.hooks, killed_processes, kill_reason
            )
            update_patch_hooks_field(project_file, cl_name, updated_hooks)

    # Kill running agent processes
    killed_hook_agents, killed_comment_agents = kill_running_agent_processes(patch)
    total_killed_agents = len(killed_hook_agents) + len(killed_comment_agents)
    if total_killed_agents:
        if log_fn:
            log_fn(f"Killed {total_killed_agents} running agent process(es)")
        if killed_hook_agents and patch.hooks:
            updated_hooks = mark_hook_agents_as_killed(patch.hooks, killed_hook_agents)
            update_patch_hooks_field(project_file, cl_name, updated_hooks)
        if killed_comment_agents and patch.comments:
            updated_comments = mark_comment_agents_as_killed(
                patch.comments, killed_comment_agents
            )
            update_patch_comments_field(project_file, cl_name, updated_comments)

    # Kill running mentor processes
    killed_mentors = kill_running_mentor_processes(patch)
    if killed_mentors:
        if log_fn:
            log_fn(f"Killed {len(killed_mentors)} running mentor process(es)")
        if patch.mentors:
            updated_mentors = mark_mentor_agents_as_killed(
                patch.mentors, killed_mentors
            )
            update_patch_mentors_field(project_file, cl_name, updated_mentors)

        # Release workspaces claimed by killed mentor processes
        from sase.running_field import get_claimed_workspaces, release_workspace

        for _entry, status_line, _pid in killed_mentors:
            if not status_line.suffix:
                continue

            workflow = extract_mentor_workflow_from_suffix(status_line.suffix)
            if not workflow:
                continue

            for claim in get_claimed_workspaces(project_file):
                if claim.workflow == workflow and claim.cl_name == cl_name:
                    release_workspace(
                        project_file, claim.workspace_num, workflow, cl_name
                    )
                    if log_fn:
                        log_fn(
                            f"Released workspace #{claim.workspace_num} "
                            f"for killed mentor"
                        )
                    break
