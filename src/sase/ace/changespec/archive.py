"""Archive file operations for ChangeSpecs.

When a ChangeSpec transitions to a terminal status (Submitted, Archived, Reverted),
its text block is moved from the main project file to an archive file. This keeps the
main file lean while preserving history.
"""

import logging
import os

from .locking import changespec_lock, write_changespec_atomic

logger = logging.getLogger(__name__)


def get_archive_file_path(project_file: str) -> str:
    """Get the archive file path for a given project file.

    Args:
        project_file: Path like ``~/.sase/projects/sase/sase.gp``

    Returns:
        Path like ``~/.sase/projects/sase/sase-archive.gp``
    """
    if project_file.endswith(".gp"):
        return project_file[:-3] + "-archive.gp"
    return project_file + "-archive"


def get_main_file_path(archive_file: str) -> str:
    """Get the main project file path from an archive file path.

    Args:
        archive_file: Path like ``~/.sase/projects/sase/sase-archive.gp``

    Returns:
        Path like ``~/.sase/projects/sase/sase.gp``
    """
    if archive_file.endswith("-archive.gp"):
        return archive_file[:-11] + ".gp"
    return archive_file


def is_archive_file(file_path: str) -> bool:
    """Check whether a file path is an archive file."""
    return file_path.endswith("-archive.gp")


def _extract_changespec_block(
    lines: list[str], changespec_name: str
) -> tuple[list[str] | None, list[str]]:
    """Extract a ChangeSpec block from file lines.

    Finds the ChangeSpec named ``changespec_name`` and returns its raw lines
    (including any preceding ``## ChangeSpec`` header and trailing blank
    separator) along with the remaining file lines.

    Args:
        lines: All lines of the file.
        changespec_name: The NAME value to find.

    Returns:
        ``(extracted_lines, remaining_lines)`` where *extracted_lines* is
        ``None`` if the ChangeSpec was not found.
    """
    # Find the NAME line for this ChangeSpec
    name_line_idx: int | None = None
    for i, line in enumerate(lines):
        if line.startswith("NAME: ") and line[6:].strip() == changespec_name:
            name_line_idx = i
            break

    if name_line_idx is None:
        return None, list(lines)

    # Walk backwards to include a preceding ## ChangeSpec header and blank lines
    block_start = name_line_idx
    idx = name_line_idx - 1
    while idx >= 0:
        stripped = lines[idx].strip()
        if stripped == "":
            # blank separator — include it
            idx -= 1
            continue
        if stripped.startswith("## ChangeSpec"):
            block_start = idx
            break
        # Some other content — stop
        break
    else:
        # Reached beginning of file
        pass

    # Include any blank lines between the header (or previous content) and NAME
    # We already walked backwards; block_start is the earliest line to include.
    # But only include blank lines that are directly above the block:
    if block_start < name_line_idx:
        block_start = block_start  # already correct
    # Also include blank lines that sit between previous content and our header
    while block_start > 0 and lines[block_start - 1].strip() == "":
        block_start -= 1

    # Walk forward to find the end of this ChangeSpec block
    block_end = name_line_idx + 1
    while block_end < len(lines):
        line = lines[block_end]
        stripped = line.strip()

        # Next ChangeSpec header or NAME line → stop (don't include it)
        if stripped.startswith("## ChangeSpec") or line.startswith("NAME: "):
            break

        block_end += 1

    # Trim trailing blank lines from the block end (we'll re-add a separator)
    while block_end > name_line_idx + 1 and lines[block_end - 1].strip() == "":
        block_end -= 1

    extracted = lines[block_start:block_end]
    remaining = lines[:block_start] + lines[block_end:]

    # Clean up multiple consecutive blank lines left in remaining
    cleaned: list[str] = []
    prev_blank = False
    for line in remaining:
        is_blank = line.strip() == ""
        if is_blank and prev_blank:
            continue
        cleaned.append(line)
        prev_blank = is_blank

    return extracted, cleaned


def move_changespec_to_file(
    source_file: str, dest_file: str, changespec_name: str
) -> bool:
    """Move a ChangeSpec block from one file to another.

    The move uses an add-then-remove strategy so the ChangeSpec temporarily
    exists in both files (safe) rather than neither (unsafe).

    Args:
        source_file: Path to the file containing the ChangeSpec.
        dest_file: Path to the file to move the ChangeSpec to.
        changespec_name: The NAME of the ChangeSpec to move.

    Returns:
        ``True`` on success, ``False`` if the ChangeSpec was not found.
    """
    # Step 1: Read source and extract the block
    with changespec_lock(source_file):
        if not os.path.isfile(source_file):
            return False
        with open(source_file, encoding="utf-8") as f:
            source_lines = f.readlines()

        extracted, _ = _extract_changespec_block(source_lines, changespec_name)

    if extracted is None:
        logger.debug(
            "ChangeSpec '%s' not found in %s, skipping move",
            changespec_name,
            source_file,
        )
        return False

    # Step 2: Append to destination file
    with changespec_lock(dest_file):
        if os.path.isfile(dest_file):
            with open(dest_file, encoding="utf-8") as f:
                dest_content = f.read()
        else:
            dest_content = ""

        # Ensure separation from existing content
        if dest_content and not dest_content.endswith("\n\n"):
            if not dest_content.endswith("\n"):
                dest_content += "\n"
            dest_content += "\n"

        dest_content += "".join(extracted)
        if not dest_content.endswith("\n"):
            dest_content += "\n"

        # Ensure dest directory exists
        dest_dir = os.path.dirname(dest_file)
        if dest_dir:
            os.makedirs(dest_dir, exist_ok=True)

        write_changespec_atomic(dest_file, dest_content, f"Add {changespec_name}")

    # Step 3: Re-read source and remove the block
    with changespec_lock(source_file):
        with open(source_file, encoding="utf-8") as f:
            source_lines = f.readlines()

        _, remaining = _extract_changespec_block(source_lines, changespec_name)
        new_content = "".join(remaining)

        write_changespec_atomic(source_file, new_content, f"Remove {changespec_name}")

    logger.info(
        "Moved ChangeSpec '%s' from %s to %s",
        changespec_name,
        source_file,
        dest_file,
    )
    return True
