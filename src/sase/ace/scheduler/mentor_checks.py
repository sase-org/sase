"""Mentor lifecycle management and orchestration for the axe scheduler."""

from sase.mentor_config import (
    MentorProfileConfig,
    get_all_mentor_profiles,
)

from ..changespec import (
    ChangeSpec,
    extract_pid_from_agent_suffix,
)
from ..display_helpers import is_entry_ref_suffix
from ..hooks.processes import (
    is_process_running,
    kill_running_mentor_processes,
)
from ..mentors import set_mentor_status
from .mentor_profile_matching import (
    LogCallback,
    add_matching_profiles_upfront,
    get_profiles_registered_for_entry,
)


def _get_started_mentors_for_entry(
    changespec: ChangeSpec, entry_id: str
) -> set[tuple[str, str]]:
    """Get set of (profile_name, mentor_name) tuples that have been started.

    Args:
        changespec: The ChangeSpec to check.
        entry_id: The commit entry ID.

    Returns:
        Set of (profile_name, mentor_name) tuples that have status lines.
    """
    started: set[tuple[str, str]] = set()
    if not changespec.mentors:
        return started

    for me in changespec.mentors:
        if me.entry_id == entry_id and me.status_lines:
            for sl in me.status_lines:
                started.add((sl.profile_name, sl.mentor_name))

    return started


def _all_non_skip_hooks_ready(changespec: ChangeSpec, entry_id: str) -> bool:
    """Check if all non-skip hooks are ready for mentors to run.

    Only checks hook status for the given entry_id (the latest commit).
    Status from older commits is irrelevant.

    A hook is "ready" for the given entry if it has either:
    - PASSED status for this entry, or
    - FAILED status for this entry with an entry_ref suffix (proposal attached), or
    - FAILED status with summarization complete (%: or ^: prefix)

    Hooks with skip_fix_hook (! prefix) are completely ignored.

    Args:
        changespec: The ChangeSpec to check.
        entry_id: The LATEST commit entry ID to check hooks for.

    Returns:
        True if all non-skip hooks are ready for this entry, False otherwise.
    """
    if not changespec.hooks:
        return False  # Hooks not yet added, wait for them

    checked_any = False
    for hook in changespec.hooks:
        # Skip hooks with ! prefix - they don't affect mentor eligibility
        if hook.skip_fix_hook:
            continue

        checked_any = True

        # Get status line for this entry
        status_line = hook.get_status_line_for_commit_entry(entry_id)

        if status_line is None:
            # Hook hasn't run for this entry yet
            return False

        if status_line.status == "RUNNING":
            # Hook still running
            return False

        if status_line.status == "FAILED":
            # Failed hooks are ready if:
            # - fix-hook is running (@:), OR
            # - has a proposal (entry_ref like 2a), OR
            # - summarization is complete (%: or ^:)
            if status_line.suffix_type in (
                "running_agent",
                "summarize_complete",
                "metahook_complete",
            ):
                continue  # Hook has been processed, ready
            if not is_entry_ref_suffix(status_line.suffix):
                return False  # fix-hook hasn't started yet
            # Has entry_ref suffix - ready

        # PASSED, KILLED, DEAD, or FAILED with entry_ref - considered ready

    if not checked_any:
        return False  # All hooks were !-prefixed, wait for non-! hooks

    return True


def _get_mentor_profiles_to_run(
    changespec: ChangeSpec,
) -> list[tuple[str, MentorProfileConfig]]:
    """Get list of (entry_id, profile) tuples that should run mentors.

    Checks ALL commits since the last MENTORS entry.
    Returns profiles that have unstarted mentors for the latest entry.

    Args:
        changespec: The ChangeSpec to check.

    Returns:
        List of (entry_id, profile) tuples to run.
    """
    result: list[tuple[str, MentorProfileConfig]] = []

    if not changespec.commits:
        return result

    # Get the latest non-proposal commit entry
    latest_entry_id = None
    for entry in reversed(changespec.commits):
        if entry.display_number.isdigit():
            latest_entry_id = entry.display_number
            break

    if latest_entry_id is None:
        return result

    # Check if all non-skip hooks are ready before running mentors
    if not _all_non_skip_hooks_ready(changespec, latest_entry_id):
        return result

    # Get profiles already registered in MENTORS for this entry
    # (profiles are added by _add_matching_profiles_upfront or clear_mentor_draft_flags)
    registered_profiles = get_profiles_registered_for_entry(changespec, latest_entry_id)

    # Get mentors already started for this entry
    started_mentors = _get_started_mentors_for_entry(changespec, latest_entry_id)

    for profile in get_all_mentor_profiles():
        # Only run mentors for profiles that are registered for this entry
        if profile.profile_name not in registered_profiles:
            continue

        # Check if any mentors in this profile are unstarted
        has_unstarted = False
        for mentor in profile.mentors:
            if (profile.profile_name, mentor.mentor_name) not in started_mentors:
                has_unstarted = True
                break

        if has_unstarted:
            result.append((latest_entry_id, profile))

    return result


def _kill_stale_mentors(
    changespec: ChangeSpec,
    log: LogCallback,
) -> list[str]:
    """Kill mentor processes running for older commits when a newer commit exists.

    When a new commit is added (e.g., manually), mentors from the previous
    commit become stale and should be terminated. This prevents old mentors
    from continuing to run after new code has been committed.

    Args:
        changespec: The ChangeSpec to check.
        log: Logging callback.

    Returns:
        List of update messages.
    """
    updates: list[str] = []

    if not changespec.mentors or not changespec.commits:
        return updates

    # Find the latest regular (non-proposal) commit entry ID
    latest_entry_id = None
    for entry in reversed(changespec.commits):
        if entry.display_number.isdigit():
            latest_entry_id = entry.display_number
            break

    if latest_entry_id is None:
        return updates

    # Collect entry IDs that are older than the latest
    stale_entry_ids: set[str] = set()
    for me in changespec.mentors:
        if me.entry_id != latest_entry_id and me.entry_id.isdigit():
            # Check if this entry actually has running mentors
            if me.status_lines:
                for sl in me.status_lines:
                    if sl.suffix_type == "running_agent":
                        stale_entry_ids.add(me.entry_id)
                        break

    if not stale_entry_ids:
        return updates

    # Kill only mentors for stale entries
    killed = kill_running_mentor_processes(changespec, only_entry_ids=stale_entry_ids)

    if not killed:
        return updates

    # Mark killed mentors via set_mentor_status (atomic, lock-safe)
    for kill_entry, kill_sl, _kill_pid in killed:
        set_mentor_status(
            changespec.file_path,
            changespec.name,
            kill_entry.entry_id,
            kill_sl.profile_name,
            kill_sl.mentor_name,
            kill_sl.status,
            timestamp=kill_sl.timestamp,
            suffix=kill_sl.suffix,
            suffix_type="killed_agent",
            duration=kill_sl.duration,
        )

    # Release workspaces claimed by killed mentor processes
    from sase.running_field import get_claimed_workspaces, release_workspace

    from ..hooks.processes import extract_mentor_workflow_from_suffix

    for _entry, status_line, _pid in killed:
        if not status_line.suffix:
            continue

        workflow = extract_mentor_workflow_from_suffix(status_line.suffix)
        if not workflow:
            continue

        for claim in get_claimed_workspaces(changespec.file_path):
            if claim.workflow == workflow and claim.cl_name == changespec.name:
                release_workspace(
                    changespec.file_path,
                    claim.workspace_num,
                    workflow,
                    changespec.name,
                )
                log(
                    f"Released workspace #{claim.workspace_num} for stale mentor",
                    "dim",
                )
                break

    for _entry, sl, _pid in killed:
        msg = (
            f"Killed stale MENTOR '{sl.profile_name}:{sl.mentor_name}' "
            f"({_entry.entry_id}) - newer commit {latest_entry_id} exists"
        )
        updates.append(msg)
        log(msg, "cyan")

    return updates


def _is_mentor_process(pid: int) -> bool:
    """Check if a PID belongs to a mentor runner process.

    Uses /proc/<pid>/cmdline on Linux to verify the process is actually
    a mentor_runner.  This guards against PID reuse: after a mentor
    process exits, a completely unrelated process may receive the same
    PID, causing ``is_process_running()`` to return True.

    Args:
        pid: The process ID to check.

    Returns:
        True if the process appears to be a mentor runner, or if the
        check cannot be performed (non-Linux). False if the PID clearly
        belongs to a different process.
    """
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().decode("utf-8", errors="replace")
        return "mentor_runner" in cmdline
    except (FileNotFoundError, PermissionError, OSError):
        return True  # Can't check — assume it's the mentor


def _check_mentor_completion(
    changespec: ChangeSpec,
    log: LogCallback,
    zombie_timeout_seconds: int,
) -> list[str]:
    """Check completion status of running mentors.

    Detects mentor processes that are no longer running and marks them as killed.
    Uses set_mentor_status() for each dead mentor to avoid race conditions with
    concurrent status updates.

    Also detects PID reuse: if the PID is alive but belongs to an unrelated
    process (not mentor_runner), the mentor is marked as DEAD.

    Args:
        changespec: The ChangeSpec to check.
        log: Logging callback.
        zombie_timeout_seconds: Timeout for detecting zombie processes.

    Returns:
        List of update messages.
    """
    del zombie_timeout_seconds  # Unused for now

    updates: list[str] = []

    if not changespec.mentors:
        return updates

    for entry in changespec.mentors:
        if not entry.status_lines:
            continue

        for msl in entry.status_lines:
            if msl.suffix_type == "running_agent" and msl.suffix:
                pid = extract_pid_from_agent_suffix(msl.suffix)
                if pid is None:
                    continue

                process_alive = is_process_running(pid)
                pid_reused = process_alive and not _is_mentor_process(pid)
                if not process_alive or pid_reused:
                    reason = "PID reused" if pid_reused else "not running"
                    # Process is dead - mark as killed via set_mentor_status
                    success = set_mentor_status(
                        changespec.file_path,
                        changespec.name,
                        entry.entry_id,
                        msl.profile_name,
                        msl.mentor_name,
                        "DEAD",
                        timestamp=msl.timestamp,
                        suffix=msl.suffix,
                        suffix_type="killed_agent",
                        duration=msl.duration,
                    )
                    if success:
                        msg = (
                            f"Marked dead MENTOR "
                            f"'{msl.profile_name}:{msl.mentor_name}' "
                            f"({entry.entry_id}) - PID {pid} {reason}"
                        )
                        updates.append(msg)
                        log(msg, "cyan")

    return updates


def check_mentors(
    changespec: ChangeSpec,
    log: LogCallback,
    zombie_timeout_seconds: int,
    max_runners: int,
    runners_started_this_cycle: int = 0,
) -> tuple[list[str], int]:
    """Check and run mentors for a ChangeSpec.

    Phase 1: Check completion status of RUNNING mentors
    Phase 2: Add matching profiles upfront (before hooks are ready)
    Phase 3: Start mentors for matching profiles (after hooks are ready)

    Args:
        changespec: The ChangeSpec to check.
        log: Logging callback.
        zombie_timeout_seconds: Zombie detection timeout in seconds.
        max_runners: Maximum concurrent runners (hooks, agents, mentors) globally.
        runners_started_this_cycle: Number of runners already started this cycle (across
            all ChangeSpecs). Added to the global count to avoid exceeding the limit.

    Returns:
        Tuple of (update messages, number of mentors started by this call).
    """
    updates: list[str] = []
    mentors_started = 0

    # Don't check mentors for non-review statuses
    if changespec.status in ("Draft", "WIP", "Reverted", "Submitted", "Archived"):
        return updates, mentors_started

    # Phase 1: Check completion of running mentors
    completion_updates = _check_mentor_completion(
        changespec, log, zombie_timeout_seconds
    )
    updates.extend(completion_updates)

    # Phase 1.5: Kill stale mentors from older commits
    stale_updates = _kill_stale_mentors(changespec, log)
    updates.extend(stale_updates)

    # Phase 2: Add matching profiles upfront (before hooks are ready)
    # This adds profiles with [0/N] counts as soon as they're detected
    profile_updates = add_matching_profiles_upfront(changespec, log)
    updates.extend(profile_updates)

    # Phase 3: Start mentors for matching profiles (requires hooks to be ready)
    profiles_to_run = _get_mentor_profiles_to_run(changespec)

    if not profiles_to_run:
        return updates, mentors_started

    # Check global concurrency limit
    # Include runners started this cycle (across all ChangeSpecs) that aren't
    # yet written to disk
    from ..changespec import count_agent_runners_global

    current_running = count_agent_runners_global() + runners_started_this_cycle

    if current_running >= max_runners:
        log(
            f"Skipping mentor start: {current_running} runners running "
            f"(limit: {max_runners})",
            "dim",
        )
        return updates, mentors_started

    available_slots = max_runners - current_running

    # Import start_mentor here to avoid circular imports
    from .mentor_runner import start_mentors_for_profile

    for entry_id, profile in profiles_to_run:
        if mentors_started >= available_slots:
            log(
                f"Reached runner limit ({max_runners}), deferring remaining mentors",
                "dim",
            )
            break

        # Get mentors already started for this entry
        started_mentors = _get_started_mentors_for_entry(changespec, entry_id)

        # Start unstarted mentors for this profile
        started_count, start_updates = start_mentors_for_profile(
            changespec,
            entry_id,
            profile,
            log,
            available_slots - mentors_started,
            started_mentors,
        )
        updates.extend(start_updates)
        mentors_started += started_count

    return updates, mentors_started
