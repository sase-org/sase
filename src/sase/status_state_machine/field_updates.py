"""
Field update functions for ChangeSpec files.

Pure-transform functions for STATUS, CL, PARENT, and DESCRIPTION fields.
These are used by the spec_writer handlers to apply updates to file content.
"""

from sase.workspace_provider import get_change_label


def apply_status_update(lines: list[str], changespec_name: str, new_status: str) -> str:
    """Apply STATUS field update to file lines.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        new_status: New STATUS value.

    Returns:
        Updated file content as a string.
    """
    updated_lines = []
    in_target_changespec = False

    for line in lines:
        # Check if this is a NAME field
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_changespec = current_name == changespec_name

        # Update STATUS if we're in the target ChangeSpec
        if in_target_changespec and line.startswith("STATUS:"):
            # Replace the STATUS line
            updated_lines.append(f"STATUS: {new_status}\n")
            in_target_changespec = False  # Done updating this ChangeSpec
        else:
            updated_lines.append(line)

    return "".join(updated_lines)


def apply_cl_update(
    lines: list[str], changespec_name: str, new_cl: str | None, project_file: str
) -> str:
    """Apply CL field update to file lines.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        new_cl: New CL value (None to reset/remove).
        project_file: Path to the project file (used to determine CL/PR label).

    Returns:
        Updated file content as a string.
    """
    updated_lines = []
    in_target_changespec = False
    found_cl_line = False

    for line in lines:
        # Check if this is a NAME field
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_changespec = current_name == changespec_name
            found_cl_line = False  # Reset for new ChangeSpec

        # Update CL/PR if we're in the target ChangeSpec
        if in_target_changespec and line.startswith(("CL:", "PR:")):
            found_cl_line = True
            # Replace the CL/PR line, or skip it entirely if resetting to None
            if new_cl is not None:
                prefix = "PR" if line.startswith("PR:") else "CL"
                updated_lines.append(f"{prefix}: {new_cl}\n")
            # When new_cl is None, we simply skip this line (don't append it)
        elif in_target_changespec and line.startswith("STATUS:") and not found_cl_line:
            # CL/PR field doesn't exist - add it before STATUS if we have a new value
            if new_cl is not None:
                label = get_change_label(project_file)
                updated_lines.append(f"{label}: {new_cl}\n")
                found_cl_line = True
            updated_lines.append(line)
        else:
            updated_lines.append(line)

    return "".join(updated_lines)


def read_status_from_lines(lines: list[str], changespec_name: str) -> str | None:
    """Read STATUS from file lines (unlocked helper).

    Args:
        lines: File lines to search.
        changespec_name: NAME of the ChangeSpec to find.

    Returns:
        Current STATUS value, or None if not found.
    """
    in_target_changespec = False
    for line in lines:
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_changespec = current_name == changespec_name
        if in_target_changespec and line.startswith("STATUS:"):
            return line.split(":", 1)[1].strip()
    return None


def apply_parent_update(
    lines: list[str], changespec_name: str, new_parent: str | None
) -> str:
    """Apply PARENT field update to file lines.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        new_parent: New PARENT value (None to remove).

    Returns:
        Updated file content as a string.
    """
    updated_lines = []
    in_target_changespec = False
    found_parent_line = False
    in_description = False

    for line in lines:
        # Check if this is a NAME field
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_changespec = current_name == changespec_name
            found_parent_line = False
            in_description = False

        # Track when we're in the DESCRIPTION field
        if in_target_changespec and line.startswith("DESCRIPTION:"):
            in_description = True

        # Update PARENT if we're in the target ChangeSpec
        if in_target_changespec and line.startswith("PARENT:"):
            found_parent_line = True
            # Replace the PARENT line, or skip it entirely if resetting to None
            if new_parent is not None:
                updated_lines.append(f"PARENT: {new_parent}\n")
            # When new_parent is None, we simply skip this line (don't append it)
        elif (
            in_target_changespec
            and in_description
            and (line.startswith(("CL:", "PR:")) or line.startswith("STATUS:"))
            and not found_parent_line
        ):
            # PARENT field doesn't exist - add it before CL or STATUS if we have value
            if new_parent is not None:
                updated_lines.append(f"PARENT: {new_parent}\n")
                found_parent_line = True
            in_description = False
            updated_lines.append(line)
        else:
            # End description section when we hit another field
            if (
                in_target_changespec
                and in_description
                and line.startswith(
                    ("PARENT:", "CL:", "PR:", "STATUS:", "TEST TARGETS:", "KICKSTART:")
                )
            ):
                in_description = False
            updated_lines.append(line)

    return "".join(updated_lines)


_FIELD_HEADERS = (
    "NAME:",
    "DESCRIPTION:",
    "PARENT:",
    "CL:",
    "BUG:",
    "STATUS:",
    "KICKSTART:",
    "TEST TARGETS:",
    "COMMITS:",
    "HOOKS:",
    "COMMENTS:",
    "MENTORS:",
)


def _is_field_or_section_header(line: str) -> bool:
    """Check if a line starts with a known ChangeSpec field/section header."""
    return line.startswith(_FIELD_HEADERS)


def _format_description_field(description: str) -> list[str]:
    """Format a plain-text description into DESCRIPTION field lines.

    Produces a ``DESCRIPTION:\\n`` header followed by 2-space-indented
    continuation lines, matching the parser format.

    Args:
        description: Plain-text description (may contain newlines).

    Returns:
        List of formatted lines (each ending with ``\\n``).
    """
    result = ["DESCRIPTION:\n"]
    for line in description.splitlines():
        if line:
            result.append(f"  {line}\n")
        else:
            result.append("\n")
    return result


def apply_description_update(
    lines: list[str], changespec_name: str, new_description: str
) -> str:
    """Apply DESCRIPTION field update to file lines.

    Finds the target ChangeSpec by NAME, then replaces the DESCRIPTION header
    and all its continuation lines (2-space-indented and blank lines) with
    the newly formatted description.  Stops consuming old description lines
    when it hits a known field header.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        new_description: New plain-text description.

    Returns:
        Updated file content as a string.
    """
    updated_lines: list[str] = []
    in_target_changespec = False
    skipping_old_description = False

    for line in lines:
        # Track which ChangeSpec we're in
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_changespec = current_name == changespec_name

        # When skipping old description lines, check for end of description
        if skipping_old_description:
            if _is_field_or_section_header(line):
                # Hit the next field — stop skipping, emit this line normally
                skipping_old_description = False
                updated_lines.append(line)
            # Otherwise it's a continuation line (2-space-indented or blank) — skip it
            continue

        # Replace DESCRIPTION header in the target ChangeSpec
        if in_target_changespec and line.startswith("DESCRIPTION:"):
            updated_lines.extend(_format_description_field(new_description))
            skipping_old_description = True
            continue

        updated_lines.append(line)

    return "".join(updated_lines)
