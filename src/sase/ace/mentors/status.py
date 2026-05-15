"""Mentor status operations - setting, merging, and clearing status lines."""

from sase.core.time import generate_timestamp as gen_timestamp
from sase.status_state_machine import remove_workspace_suffix

from sase.ace.changespec import (
    MentorEntry,
    MentorStatusLine,
    changespec_lock,
    parse_project_file,
    write_changespec_atomic,
)

from sase.ace.mentors.formatting import apply_mentors_update


def set_mentor_status(
    project_file: str,
    changespec_name: str,
    entry_id: str,
    profile_name: str,
    mentor_name: str,
    status: str,
    timestamp: str | None = None,
    suffix: str | None = None,
    suffix_type: str | None = None,
    duration: str | None = None,
) -> bool:
    """Set or update the status for a specific mentor in a profile.

    Args:
        project_file: Path to the project file.
        changespec_name: Name of the ChangeSpec.
        entry_id: The commit entry ID (e.g., "1", "2").
        profile_name: The profile name.
        mentor_name: The mentor name.
        status: The status (RUNNING, PASSED, FAILED).
        timestamp: Optional timestamp in YYmmdd_HHMMSS format for chat file link.
        suffix: Optional suffix (e.g., "mentor_complete-12345-251230_1530").
        suffix_type: Optional suffix type ("running_agent", "error", "plain").
        duration: Optional duration string (e.g., "0h2m15s").

    Returns:
        True if successful, False otherwise.
    """
    try:
        with changespec_lock(project_file):
            changespecs = parse_project_file(project_file)
            current_mentors: list[MentorEntry] = []
            changespec_status: str | None = None
            for cs in changespecs:
                if cs.name == changespec_name:
                    current_mentors = list(cs.mentors) if cs.mentors else []
                    changespec_status = cs.status
                    break

            # Determine if changespec is in Draft status
            is_draft_status = (
                changespec_status is not None
                and remove_workspace_suffix(changespec_status) == "Draft"
            )

            # Find the entry
            target_entry: MentorEntry | None = None
            for entry in current_mentors:
                if entry.entry_id == entry_id:
                    target_entry = entry
                    break

            if target_entry is None:
                # Entry doesn't exist - create it
                target_entry = MentorEntry(
                    entry_id=entry_id,
                    profiles=[profile_name],
                    status_lines=[],
                    is_draft=is_draft_status,
                )
                current_mentors.append(target_entry)

            # Find or create the status line
            if target_entry.status_lines is None:
                target_entry.status_lines = []

            existing_status_line: MentorStatusLine | None = None
            for sl in target_entry.status_lines:
                if sl.profile_name == profile_name and sl.mentor_name == mentor_name:
                    existing_status_line = sl
                    break

            if existing_status_line:
                # Don't overwrite killed_agent status - this prevents a killed mentor
                # from overwriting its status if it survives the SIGTERM
                if existing_status_line.suffix_type == "killed_agent":
                    return True

                # Update existing status line
                existing_status_line.status = status
                # Only update timestamp if provided (preserve existing if not)
                if timestamp is not None:
                    existing_status_line.timestamp = timestamp
                existing_status_line.suffix = suffix
                existing_status_line.suffix_type = suffix_type
                existing_status_line.duration = duration
            else:
                # Create new status line (generate timestamp if not provided)
                new_status_line = MentorStatusLine(
                    profile_name=profile_name,
                    mentor_name=mentor_name,
                    status=status,
                    timestamp=timestamp if timestamp else gen_timestamp(),
                    duration=duration,
                    suffix=suffix,
                    suffix_type=suffix_type,
                )
                target_entry.status_lines.append(new_status_line)

            # Write updated mentors
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            updated_lines = apply_mentors_update(
                lines, changespec_name, current_mentors
            )
            content = "".join(updated_lines)

            write_changespec_atomic(
                project_file,
                content,
                f"Set mentor status {profile_name}:{mentor_name} -> {status}",
            )
            return True
    except Exception:
        return False


_TERMINAL_MENTOR_STATUSES = frozenset(
    {"PASSED", "COMMENTED", "FAILED", "DEAD", "KILLED"}
)


def merge_mentor_status_lines(
    current_mentors: list[MentorEntry],
    caller_mentors: list[MentorEntry],
) -> list[MentorEntry]:
    """Merge status_lines from disk that the caller doesn't have.

    Preserves any (profile_name, mentor_name) status_lines that exist on disk
    but NOT in the caller's data (they were added after the caller's read).

    Also preserves terminal statuses from disk: if the disk has a completed
    status (PASSED/FAILED/DEAD/KILLED) or killed_agent suffix_type for a
    status line that the caller still shows as non-terminal, the disk version
    wins.  This prevents stale reads from overwriting status updates made by
    ``set_mentor_status()`` between the caller's read and write.

    Args:
        current_mentors: Mentor entries freshly read from disk inside the lock.
        caller_mentors: Mentor entries provided by the caller (possibly stale).

    Returns:
        The caller_mentors list with missing/newer status_lines merged in.
    """
    # Build lookup of caller's status line keys and objects per entry_id
    caller_status_keys: dict[str, set[tuple[str, str]]] = {}
    caller_entry_lookup: dict[str, MentorEntry] = {}
    caller_sl_lookup: dict[str, dict[tuple[str, str], MentorStatusLine]] = {}
    for entry in caller_mentors:
        keys: set[tuple[str, str]] = set()
        sl_map: dict[tuple[str, str], MentorStatusLine] = {}
        if entry.status_lines:
            for sl in entry.status_lines:
                key = (sl.profile_name, sl.mentor_name)
                keys.add(key)
                sl_map[key] = sl
        caller_status_keys[entry.entry_id] = keys
        caller_entry_lookup[entry.entry_id] = entry
        caller_sl_lookup[entry.entry_id] = sl_map

    # For each entry on disk, merge status_lines into caller's data
    for disk_entry in current_mentors:
        if disk_entry.entry_id not in caller_entry_lookup:
            continue  # Caller doesn't have this entry, skip
        if not disk_entry.status_lines:
            continue

        caller_keys = caller_status_keys[disk_entry.entry_id]
        caller_entry = caller_entry_lookup[disk_entry.entry_id]
        caller_sls = caller_sl_lookup[disk_entry.entry_id]

        for disk_sl in disk_entry.status_lines:
            key = (disk_sl.profile_name, disk_sl.mentor_name)
            if key not in caller_keys:
                # Status line exists on disk but not in caller's data
                if caller_entry.status_lines is None:
                    caller_entry.status_lines = []
                caller_entry.status_lines.append(disk_sl)
            else:
                # Status line exists in both — prefer disk if it has a
                # terminal status that the caller's stale read might miss
                disk_is_terminal = (
                    disk_sl.status in _TERMINAL_MENTOR_STATUSES
                    or disk_sl.suffix_type == "killed_agent"
                )
                caller_sl = caller_sls[key]
                caller_is_terminal = (
                    caller_sl.status in _TERMINAL_MENTOR_STATUSES
                    or caller_sl.suffix_type == "killed_agent"
                )
                if disk_is_terminal and not caller_is_terminal:
                    # Disk has a newer terminal status — replace caller's
                    # stale version with the disk version
                    if caller_entry.status_lines:
                        caller_entry.status_lines = [
                            disk_sl if (s.profile_name, s.mentor_name) == key else s
                            for s in caller_entry.status_lines
                        ]

    return caller_mentors


def update_changespec_mentors_field(
    project_file: str,
    changespec_name: str,
    mentors: list[MentorEntry],
) -> bool:
    """Update the MENTORS field for a ChangeSpec.

    Replaces the entire MENTORS field with the provided mentor entries.
    Uses locking and merges status_lines from disk that the caller may
    not have (added by concurrent set_mentor_status calls).

    Args:
        project_file: Path to the project file.
        changespec_name: NAME of the ChangeSpec to update.
        mentors: List of MentorEntry objects to write.

    Returns:
        True if successful, False otherwise.
    """
    try:
        with changespec_lock(project_file):
            # Re-read current state inside the lock
            current_changespecs = parse_project_file(project_file)
            current_mentors: list[MentorEntry] = []
            for cs in current_changespecs:
                if cs.name == changespec_name:
                    current_mentors = list(cs.mentors) if cs.mentors else []
                    break

            # Merge status_lines from disk that caller doesn't have
            merged = merge_mentor_status_lines(current_mentors, mentors)

            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            updated_lines = apply_mentors_update(lines, changespec_name, merged)
            content = "".join(updated_lines)

            write_changespec_atomic(
                project_file,
                content,
                f"Update MENTORS field for {changespec_name}",
            )
            return True
    except Exception:
        return False


def clear_mentor_status_lines(
    project_file: str,
    changespec_name: str,
    mentors_to_clear: dict[str, set[tuple[str, str]]],
) -> bool:
    """Remove status lines for specific mentors (to allow rerun).

    Args:
        project_file: Path to the project file.
        changespec_name: Name of the ChangeSpec.
        mentors_to_clear: Dict mapping entry_id to set of (mentor_name, profile_name)
            tuples to clear.

    Returns:
        True if successful, False otherwise.
    """
    try:
        with changespec_lock(project_file):
            changespecs = parse_project_file(project_file)
            current_mentors: list[MentorEntry] = []
            for cs in changespecs:
                if cs.name == changespec_name:
                    current_mentors = list(cs.mentors) if cs.mentors else []
                    break

            if not current_mentors:
                return True  # Nothing to clear

            # Remove specified status lines
            for entry in current_mentors:
                if entry.entry_id not in mentors_to_clear:
                    continue
                if not entry.status_lines:
                    continue

                mentors_to_remove = mentors_to_clear[entry.entry_id]
                entry.status_lines = [
                    sl
                    for sl in entry.status_lines
                    if (sl.mentor_name, sl.profile_name) not in mentors_to_remove
                ]

            # Write updated mentors
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            updated_lines = apply_mentors_update(
                lines, changespec_name, current_mentors
            )
            content = "".join(updated_lines)

            write_changespec_atomic(
                project_file,
                content,
                f"Clear mentor status lines for {changespec_name}",
            )
            return True
    except Exception:
        return False
