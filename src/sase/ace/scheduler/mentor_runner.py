"""Mentor starting and workspace management for the axe scheduler."""

import os
import subprocess
import sys
import time
from collections.abc import Callable

from sase.sase_utils import (
    ensure_sase_directory,
    get_sase_directory,
    make_safe_filename,
    strip_reverted_suffix,
)
from sase.mentor_config import MentorProfileConfig

from ..changespec import ChangeSpec
from ..hooks import generate_timestamp
from ..mentors import set_mentor_status

# Type alias for logging callback
LogCallback = Callable[[str, str | None], None]


def _get_mentor_output_path(name: str, mentor_name: str, timestamp: str) -> str:
    """Get the output file path for a mentor run.

    Args:
        name: The ChangeSpec name.
        mentor_name: The mentor name.
        timestamp: The timestamp in YYmmdd_HHMMSS format.

    Returns:
        Full path to the mentor output file.
    """
    mentors_dir = ensure_sase_directory("mentors")
    safe_name = make_safe_filename(strip_reverted_suffix(name))
    filename = f"{safe_name}-{mentor_name}-{timestamp}.txt"
    return os.path.join(mentors_dir, filename)


def get_mentor_chat_path(cl_name: str, mentor_name: str, timestamp: str) -> str:
    """Get the chat file path for a mentor run.

    The chat file is created by invoke_agent() when the mentor runs.

    Args:
        cl_name: The ChangeSpec name (used as branch_or_workspace).
        mentor_name: The mentor name.
        timestamp: The timestamp in YYmmdd_HHMMSS format.

    Returns:
        Full path to the chat file (e.g., ~/.sase/chats/{cl_name}-mentor_{mentor_name}-{timestamp}.md)
    """
    chats_dir = get_sase_directory("chats")
    # Format matches chat_history._generate_chat_filename() with:
    # - branch_or_workspace = cl_name (used as-is, NOT stripped)
    # - workflow = "mentor-{mentor_name}" (normalized to "mentor_{mentor_name}")
    # NOTE: Do NOT apply strip_reverted_suffix here — save_chat_history() uses
    # the branch_or_workspace value as-is when it's explicitly provided (which
    # MentorWorkflow always does). Stripping here would cause a naming mismatch.
    filename = f"{cl_name}-mentor_{mentor_name}-{timestamp}.md"
    return os.path.join(chats_dir, filename)


def _start_single_mentor(
    changespec: ChangeSpec,
    entry_id: str,
    profile: MentorProfileConfig,
    mentor_name: str,
    log: LogCallback,
) -> str | None:
    """Start a single mentor workflow as a background process.

    The ``#hg`` embedded workflow handles workspace claiming, checkout, and
    release.  This function only launches the subprocess and tracks status.

    Args:
        changespec: The ChangeSpec to run mentor for.
        entry_id: The commit entry ID.
        profile: The mentor profile configuration.
        mentor_name: The specific mentor to run.
        log: Logging callback.

    Returns:
        Update message if started, None if failed.
    """
    timestamp = generate_timestamp()

    # EARLY REGISTRATION: Mark as STARTING before subprocess launch
    # This prevents other loop cycles from starting the same mentor (race condition fix)
    set_mentor_status(
        changespec.file_path,
        changespec.name,
        entry_id,
        profile.profile_name,
        mentor_name,
        status="STARTING",
        timestamp=timestamp,
    )

    # Get output file path
    output_path = _get_mentor_output_path(changespec.name, mentor_name, timestamp)

    # Build the runner script path (use abspath to handle relative __file__)
    runner_script = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "axe",
        "mentor_runner.py",
    )

    # Start the background process
    try:
        with open(output_path, "w") as output_file:
            proc = subprocess.Popen(
                [
                    sys.executable,
                    runner_script,
                    changespec.name,
                    changespec.file_path,
                    mentor_name,
                    output_path,
                    entry_id,
                    profile.profile_name,
                    timestamp,
                ],
                cwd=os.path.expanduser("~"),
                stdout=output_file,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                env=os.environ,
            )
            pid = proc.pid
    except Exception as e:
        set_mentor_status(
            changespec.file_path,
            changespec.name,
            entry_id,
            profile.profile_name,
            mentor_name,
            status="FAILED",
            timestamp=timestamp,
            suffix="subprocess_start_failed",
            suffix_type="error",
        )
        log(
            f"Warning: Failed to start mentor subprocess: {e}",
            "yellow",
        )
        return None

    # Set mentor status to RUNNING with timestamp
    set_mentor_status(
        changespec.file_path,
        changespec.name,
        entry_id,
        profile.profile_name,
        mentor_name,
        status="RUNNING",
        timestamp=timestamp,
        suffix=f"mentor_{mentor_name}-{pid}-{timestamp}",
        suffix_type="running_agent",
    )

    return f"mentor {profile.profile_name}:{mentor_name} -> RUNNING for ({entry_id})"


def start_mentors_for_profile(
    changespec: ChangeSpec,
    entry_id: str,
    profile: MentorProfileConfig,
    log: LogCallback,
    max_to_start: int,
    started_mentors: set[tuple[str, str]] | None = None,
) -> tuple[int, list[str]]:
    """Start mentor workflows for a profile.

    Args:
        changespec: The ChangeSpec to run mentors for.
        entry_id: The commit entry ID.
        profile: The mentor profile configuration.
        log: Logging callback.
        max_to_start: Maximum number of mentors to start.
        started_mentors: Set of (profile_name, mentor_name) tuples that have
            already been started. If None, no mentors are skipped.

    Returns:
        Tuple of (number_started, update_messages).
    """
    updates: list[str] = []
    started = 0

    # Start each mentor in the profile
    # Note: Profile entry is already added upfront by _add_matching_profiles_upfront()
    for mentor in profile.mentors:
        if started >= max_to_start:
            break

        # Skip mentors that have already been started
        if (
            started_mentors
            and (profile.profile_name, mentor.mentor_name) in started_mentors
        ):
            continue

        result = _start_single_mentor(
            changespec, entry_id, profile, mentor.mentor_name, log
        )
        if result:
            updates.append(result)
            started += 1

            # Small delay between mentor starts to ensure unique timestamps
            time.sleep(1)

    return started, updates
