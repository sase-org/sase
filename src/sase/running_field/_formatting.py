"""Text formatting helpers for the RUNNING field."""


def normalize_running_field_spacing(content: str) -> str:
    """Normalize blank lines around the RUNNING field.

    Ensures exactly two blank lines between:
    - The last RUNNING entry and the first ChangeSpec (NAME field)
    - If there's no RUNNING field, clean up any orphaned blank lines at the start

    Args:
        content: The file content as a string.

    Returns:
        The content with normalized spacing.
    """
    lines = content.split("\n")
    result_lines: list[str] = []
    i = 0

    while i < len(lines):
        line = lines[i]

        # Check if this is the RUNNING field
        if line.startswith("RUNNING:"):
            result_lines.append(line)
            i += 1

            # Collect all RUNNING entries (2-space indented lines starting with #)
            while i < len(lines):
                entry_line = lines[i]
                if entry_line.startswith("  ") and entry_line.strip().startswith("#"):
                    result_lines.append(entry_line)
                    i += 1
                else:
                    break

            # Skip all blank lines after RUNNING entries
            while i < len(lines) and lines[i].strip() == "":
                i += 1

            # Add exactly two blank lines before the next content (NAME field)
            if i < len(lines):
                result_lines.append("")
                result_lines.append("")
        else:
            result_lines.append(line)
            i += 1

    return "\n".join(result_lines)


def clean_orphaned_blank_lines(content: str) -> str:
    """Clean up orphaned consecutive blank lines in the file.

    This is used after removing the RUNNING field entirely to clean up
    any extra blank lines that were left behind.

    Args:
        content: The file content as a string.

    Returns:
        The content with consecutive blank lines reduced to at most two.
        Two blank lines are preserved because they serve as boundaries
        between ChangeSpecs.
    """
    lines = content.split("\n")
    result_lines: list[str] = []
    consecutive_blank_count = 0

    for line in lines:
        is_blank = line.strip() == ""

        if is_blank:
            consecutive_blank_count += 1
            # Allow at most 2 consecutive blank lines (ChangeSpec boundary)
            if consecutive_blank_count > 2:
                continue
        else:
            consecutive_blank_count = 0

        result_lines.append(line)

    return "\n".join(result_lines)
