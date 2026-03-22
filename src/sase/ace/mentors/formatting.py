"""Mentor field formatting - rendering MentorEntry data into file lines."""

from sase.ace.changespec import (
    MentorEntry,
    MentorStatusLine,
    is_error_suffix,
    is_running_agent_suffix,
)


def format_profile_with_count(
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


def format_mentors_field(mentors: list[MentorEntry]) -> list[str]:
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
            format_profile_with_count(p, entry.status_lines) for p in visible_profiles
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


def apply_mentors_update(
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
                updated_lines.extend(format_mentors_field(mentors))
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
                updated_lines.extend(format_mentors_field(mentors))
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
        # Strip trailing blank lines so MENTORS stays inside the ChangeSpec
        # boundary (parser treats 2+ blank lines as end of ChangeSpec)
        while updated_lines and updated_lines[-1].strip() == "":
            updated_lines.pop()
        updated_lines.extend(format_mentors_field(mentors))

    return updated_lines
