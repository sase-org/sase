"""Mentor field operations - writing and updating MENTORS entries."""

from sase.sase_utils import generate_timestamp as gen_timestamp
from sase.status_state_machine import remove_workspace_suffix

from .changespec import (
    MentorEntry,
    MentorStatusLine,
    changespec_lock,
    is_error_suffix,
    is_running_agent_suffix,
    parse_commit_entry_id,
    parse_project_file,
    write_changespec_atomic,
)


def _format_profile_with_count(
    profile_name: str,
    status_lines: list[MentorStatusLine] | None,
) -> str:
    """Format profile name with [started/total] count.

    Args:
        profile_name: Name of the profile.
        status_lines: List of MentorStatusLine objects to count started mentors.

    Returns:
        Formatted string like "profile[2/3]".
    """
    from sase.config.mentor import get_mentor_profile_by_name

    profile_config = get_mentor_profile_by_name(profile_name)
    if profile_config is None:
        return profile_name  # Fallback if profile not found in config

    total = len(profile_config.mentors)

    started = 0
    if status_lines:
        for sl in status_lines:
            if sl.profile_name == profile_name:
                started += 1

    return f"{profile_name}[{started}/{total}]"


def _format_mentors_field(mentors: list[MentorEntry]) -> list[str]:
    """Format mentors as lines for the MENTORS field.

    Args:
        mentors: List of MentorEntry objects.

    Returns:
        List of formatted lines including "MENTORS:\n" header.
    """
    if not mentors:
        return []

    lines = ["MENTORS:\n"]
    for entry in mentors:
        visible_profiles = entry.profiles

        # Skip entry entirely if no visible profiles
        if not visible_profiles:
            continue

        # Format entry header: (<id>) <profile1>[x/y] [<profile2>[x/y] ...]
        profiles_with_counts = [
            _format_profile_with_count(p, entry.status_lines) for p in visible_profiles
        ]
        profiles_str = " ".join(profiles_with_counts)
        draft_suffix = " #Draft" if entry.is_draft else ""
        lines.append(f"  ({entry.entry_id}) {profiles_str}{draft_suffix}\n")

        # Format status lines
        if entry.status_lines:
            for sl in entry.status_lines:
                # Build the line parts with optional timestamp prefix
                # Only show timestamp for completed mentors (not RUNNING)
                if sl.timestamp and sl.status != "RUNNING":
                    line_parts = [
                        f"      | [{sl.timestamp}] "
                        f"{sl.profile_name}:{sl.mentor_name} - {sl.status}"
                    ]
                else:
                    line_parts = [
                        f"      | {sl.profile_name}:{sl.mentor_name} - {sl.status}"
                    ]

                # Add suffix
                if sl.suffix is not None or sl.duration is not None:
                    suffix_content = ""
                    if sl.suffix is not None and sl.suffix != "":
                        # Use suffix_type if available
                        if sl.suffix_type == "error" or (
                            sl.suffix_type is None and is_error_suffix(sl.suffix)
                        ):
                            suffix_content = f"!: {sl.suffix}"
                        elif sl.suffix_type == "running_agent" or (
                            sl.suffix_type is None
                            and is_running_agent_suffix(sl.suffix)
                        ):
                            suffix_content = f"@: {sl.suffix}" if sl.suffix else "@"
                        elif sl.suffix_type == "entry_ref":
                            # Entry reference (e.g., "2a") - no prefix needed
                            suffix_content = sl.suffix
                        else:
                            suffix_content = sl.suffix
                    elif sl.duration:
                        # Plain duration suffix
                        suffix_content = sl.duration

                    if suffix_content:
                        line_parts.append(f" - ({suffix_content})")

                line_parts.append("\n")
                lines.append("".join(line_parts))

    return lines


def _apply_mentors_update(
    lines: list[str],
    changespec_name: str,
    mentors: list[MentorEntry],
) -> list[str]:
    """Apply MENTORS field update to file lines.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        mentors: List of MentorEntry objects to write.

    Returns:
        Updated lines with MENTORS field modified.
    """
    updated_lines: list[str] = []
    in_target_changespec = False
    found_mentors = False
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is a NAME field
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            was_in_target = in_target_changespec
            in_target_changespec = current_name == changespec_name

            # If we were in target and didn't find MENTORS, insert before NAME
            if was_in_target and not found_mentors and mentors:
                # Remove trailing blank lines before inserting MENTORS
                # (parser treats 2+ blank lines as end of changespec)
                while updated_lines and updated_lines[-1].strip() == "":
                    updated_lines.pop()
                updated_lines.extend(_format_mentors_field(mentors))
                # Add two blank lines before next changespec (codebase convention)
                updated_lines.append("\n")
                updated_lines.append("\n")
                found_mentors = True

            updated_lines.append(line)
            i += 1
            continue

        # If we're in the target ChangeSpec
        if in_target_changespec:
            # Check for MENTORS field
            if line.startswith("MENTORS:"):
                found_mentors = True
                # Skip old MENTORS content and write new content
                updated_lines.extend(_format_mentors_field(mentors))
                i += 1
                # Skip old mentors content
                while i < len(lines):
                    next_line = lines[i]
                    stripped = next_line.strip()
                    # Check if still in mentors field:
                    # - 2-space indented entry lines (start with "(" after stripping)
                    # - 6-space "| " prefixed status lines
                    if next_line.startswith("      | "):
                        # Status line
                        i += 1
                    elif (
                        next_line.startswith("  ")
                        and not next_line.startswith("      ")
                        and stripped.startswith("(")
                    ):
                        # Entry line
                        i += 1
                    else:
                        # End of MENTORS field
                        break
                continue

        updated_lines.append(line)
        i += 1

    # If we were in target at end and didn't find MENTORS, append it
    if in_target_changespec and not found_mentors and mentors:
        updated_lines.extend(_format_mentors_field(mentors))

    return updated_lines


def add_mentor_entry(
    project_file: str,
    changespec_name: str,
    entry_id: str,
    profile_names: list[str],
) -> bool:
    """Add a new MENTORS entry for a ChangeSpec.

    If an entry for the given entry_id already exists, the profile_names
    will be merged with the existing entry's profiles.

    Args:
        project_file: Path to the project file.
        changespec_name: Name of the ChangeSpec.
        entry_id: The commit entry ID (e.g., "1", "2").
        profile_names: List of profile names that were triggered.

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

            # Check if entry already exists
            existing_entry: MentorEntry | None = None
            for entry in current_mentors:
                if entry.entry_id == entry_id:
                    existing_entry = entry
                    break

            if existing_entry:
                # Merge profiles
                for pname in profile_names:
                    if pname not in existing_entry.profiles:
                        existing_entry.profiles.append(pname)
            else:
                # Create new entry
                new_entry = MentorEntry(
                    entry_id=entry_id,
                    profiles=profile_names,
                    status_lines=[],
                )
                current_mentors.append(new_entry)

            # Write updated mentors
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            updated_lines = _apply_mentors_update(
                lines, changespec_name, current_mentors
            )
            content = "".join(updated_lines)

            write_changespec_atomic(
                project_file,
                content,
                f"Add MENTORS entry ({entry_id}) for {changespec_name}",
            )
            return True
    except Exception:
        return False


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

            updated_lines = _apply_mentors_update(
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


def _merge_mentor_status_lines(
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
            merged = _merge_mentor_status_lines(current_mentors, mentors)

            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            updated_lines = _apply_mentors_update(lines, changespec_name, merged)
            content = "".join(updated_lines)

            write_changespec_atomic(
                project_file,
                content,
                f"Update MENTORS field for {changespec_name}",
            )
            return True
    except Exception:
        return False


def clear_mentor_draft_flags(project_file: str, changespec_name: str) -> bool:
    """Clear is_draft flag and add all matching profiles for the LAST MENTORS entry.

    This is called when transitioning from Draft to Ready status. It:
    1. Finds the MENTORS entry with the highest entry_id that has is_draft=True
    2. Adds ALL matching profiles (not just Draft-enabled ones) to that entry
    3. Clears the is_draft flag

    Args:
        project_file: Path to the project file.
        changespec_name: NAME of the ChangeSpec to update.

    Returns:
        True if successful (or no Draft mentors to update), False on error.
    """
    from sase.config.mentor import get_all_mentor_profiles

    from sase.ace.scheduler.mentor_profile_matching import profile_matches_any_commit

    try:
        changespecs = parse_project_file(project_file)
        for cs in changespecs:
            if cs.name == changespec_name:
                if not cs.mentors:
                    return True  # No mentors, nothing to do

                # Find Draft entries and sort by entry_id
                draft_entries = [e for e in cs.mentors if e.is_draft]
                if not draft_entries:
                    return True  # No Draft entries, nothing to do

                # Sort by entry_id and get the last one
                draft_entries.sort(key=lambda e: parse_commit_entry_id(e.entry_id))
                last_draft_entry = draft_entries[-1]

                # Collect profiles with running mentors (must be preserved)
                profiles_with_running_mentors: set[str] = set()
                if last_draft_entry.status_lines:
                    for sl in last_draft_entry.status_lines:
                        profiles_with_running_mentors.add(sl.profile_name)

                # Use ALL commits for matching (not just this entry_id)
                matching_commits = list(cs.commits) if cs.commits else []

                # Rebuild profiles list from scratch (unless no commits exist)
                if matching_commits:
                    new_profiles: list[str] = []
                    for profile in get_all_mentor_profiles():
                        profile_name = profile.profile_name
                        # Include if: matches any commit OR has running mentors
                        if profile_matches_any_commit(profile, matching_commits):
                            new_profiles.append(profile_name)
                        elif profile_name in profiles_with_running_mentors:
                            new_profiles.append(profile_name)

                    last_draft_entry.profiles = new_profiles
                # If no commits, keep existing profiles (edge case / backward compat)

                # Clear the Draft flag
                last_draft_entry.is_draft = False

                # Write back
                return update_changespec_mentors_field(
                    project_file, changespec_name, cs.mentors
                )
        return True  # ChangeSpec not found, nothing to do
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

            updated_lines = _apply_mentors_update(
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


def set_mentor_draft_flags(project_file: str, changespec_name: str) -> bool:
    """Set is_draft flag for the LAST MENTORS entry.

    This is called when transitioning from Ready to Draft status. It:
    1. Finds the MENTORS entry with the highest entry_id
    2. Sets the is_draft flag to True

    Args:
        project_file: Path to the project file.
        changespec_name: NAME of the ChangeSpec to update.

    Returns:
        True if successful (or no mentors to update), False on error.
    """
    try:
        changespecs = parse_project_file(project_file)
        for cs in changespecs:
            if cs.name == changespec_name:
                if not cs.mentors:
                    return True  # No mentors, nothing to do

                # Sort by entry_id and get the last one
                sorted_entries = sorted(
                    cs.mentors, key=lambda e: parse_commit_entry_id(e.entry_id)
                )
                last_entry = sorted_entries[-1]

                # Set the Draft flag
                last_entry.is_draft = True

                # Write back
                return update_changespec_mentors_field(
                    project_file, changespec_name, cs.mentors
                )
        return True  # ChangeSpec not found, nothing to do
    except Exception:
        return False
