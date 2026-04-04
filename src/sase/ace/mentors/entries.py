"""Mentor entry operations - adding, removing, and managing draft flags."""

import logging

from sase.ace.changespec import (
    MentorEntry,
    changespec_lock,
    parse_commit_entry_id,
    parse_project_file,
    write_changespec_atomic,
)
from sase.ace.mentors.formatting import apply_mentors_update
from sase.ace.mentors.status import update_changespec_mentors_field

logger = logging.getLogger(__name__)


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

            updated_lines = apply_mentors_update(
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
        logger.warning(
            "Failed to add mentor entry (%s) for %s",
            entry_id,
            changespec_name,
            exc_info=True,
        )
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
                        if profile_matches_any_commit(profile, matching_commits, cs):
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
        logger.warning(
            "Failed to clear mentor draft flags for %s",
            changespec_name,
            exc_info=True,
        )
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
        logger.warning(
            "Failed to set mentor draft flags for %s",
            changespec_name,
            exc_info=True,
        )
        return False


def remove_mentor_data(
    project_file: str,
    changespec_name: str,
    *,
    delete_field: bool = False,
    entry_ids_to_delete: set[str] | None = None,
    lines_to_delete: dict[str, set[tuple[str, str]]] | None = None,
) -> bool:
    """Remove mentor entries, status lines, or the entire MENTORS field.

    Unlike update_changespec_mentors_field which merges status_lines from
    disk, this function performs direct deletions without merge-back.

    Args:
        project_file: Path to the project file.
        changespec_name: Name of the ChangeSpec.
        delete_field: If True, remove the entire MENTORS field.
        entry_ids_to_delete: Set of entry IDs to completely remove.
        lines_to_delete: Dict mapping entry_id to set of
            (mentor_name, profile_name) tuples to remove.

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
                return True

            if delete_field:
                updated_mentors: list[MentorEntry] = []
            else:
                updated_mentors = []
                for entry in current_mentors:
                    if entry_ids_to_delete and entry.entry_id in entry_ids_to_delete:
                        continue
                    if lines_to_delete and entry.entry_id in lines_to_delete:
                        if entry.status_lines:
                            entry.status_lines = [
                                sl
                                for sl in entry.status_lines
                                if (sl.mentor_name, sl.profile_name)
                                not in lines_to_delete[entry.entry_id]
                            ]
                    updated_mentors.append(entry)

            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            updated_lines = apply_mentors_update(
                lines, changespec_name, updated_mentors
            )
            content = "".join(updated_lines)

            write_changespec_atomic(
                project_file,
                content,
                f"Remove mentor data for {changespec_name}",
            )
            return True
    except Exception:
        logger.warning(
            "Failed to remove mentor data for %s",
            changespec_name,
            exc_info=True,
        )
        return False
