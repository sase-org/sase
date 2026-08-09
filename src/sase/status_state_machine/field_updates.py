"""
Field update functions for Patch files.

This module provides atomic update operations for STATUS, PR, PARENT, and
DESCRIPTION fields.
"""

import logging

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.ace.patch.section_order import PROJECT_SPEC_SECTION_HEADERS
from sase.ace.patch.review_field import (
    REVIEW_URL_PREFIXES,
    format_review_url_line,
    is_review_url_line,
)

logger = logging.getLogger(__name__)


def apply_status_update(lines: list[str], changespec_name: str, new_status: str) -> str:
    """Apply STATUS field update to file lines.

    Public entry point — calls
    :func:`sase.core.status_facade.apply_status_update`, which delegates
    directly to the Rust binding. :func:`_apply_status_update_python`
    below is the host-logic golden reference used by parity tests.
    """
    from sase.core.status_facade import apply_status_update as _facade

    return _facade(lines, changespec_name, new_status)


def _apply_status_update_python(
    lines: list[str], changespec_name: str, new_status: str
) -> str:
    """Host-logic golden reference for :func:`apply_status_update`.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        new_status: New STATUS value.

    Returns:
        Updated file content as a string.
    """
    updated_lines = []
    in_target_patch = False

    for line in lines:
        # Check if this is a NAME field
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_patch = current_name == changespec_name

        # Update STATUS if we're in the target Patch
        if in_target_patch and line.startswith("STATUS:"):
            # Replace the STATUS line
            updated_lines.append(f"STATUS: {new_status}\n")
            in_target_patch = False  # Done updating this Patch
        else:
            updated_lines.append(line)

    return "".join(updated_lines)


def _apply_pr_url_update(
    lines: list[str], changespec_name: str, new_pr_url: str | None, project_file: str
) -> str:
    """Apply PR review URL field update to file lines.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        new_pr_url: New PR URL value (None to reset/remove).
        project_file: Path to the project file.

    Returns:
        Updated file content as a string.
    """
    updated_lines = []
    in_target_patch = False
    found_pr_url_line = False
    del project_file

    for line in lines:
        # Check if this is a NAME field
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_patch = current_name == changespec_name
            found_pr_url_line = False  # Reset for new Patch

        # Update PR URL if we're in the target Patch.
        if in_target_patch and is_review_url_line(line):
            found_pr_url_line = True
            # Replace the review URL line, or skip it entirely if resetting.
            if new_pr_url is not None:
                updated_lines.append(format_review_url_line(new_pr_url))
            # When new_pr_url is None, we simply skip this line (don't append it)
        elif in_target_patch and line.startswith("STATUS:") and not found_pr_url_line:
            # PR URL field doesn't exist - add it before STATUS if we have a new value.
            if new_pr_url is not None:
                updated_lines.append(format_review_url_line(new_pr_url))
                found_pr_url_line = True
            updated_lines.append(line)
        else:
            updated_lines.append(line)

    return "".join(updated_lines)


def update_patch_pr_url_atomic(
    project_file: str, changespec_name: str, new_pr_url: str | None
) -> None:
    """Update the PR URL field of a specific Patch in the project file.

    Acquires a lock for the entire read-modify-write cycle.
    If the PR field doesn't exist and new_pr_url is not None, it will be
    added before the STATUS field.

    Args:
        project_file: Path to the ProjectSpec file
        changespec_name: NAME of the ChangeSpec to update
        new_pr_url: New PR URL value (None to reset/remove)
    """
    commit_msg = (
        f"Update PR to {new_pr_url} for {changespec_name}"
        if new_pr_url
        else f"Remove PR for {changespec_name}"
    )

    with patch_lock(project_file):
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_content = _apply_pr_url_update(
            lines, changespec_name, new_pr_url, project_file
        )

        write_patch_atomic(project_file, updated_content, commit_msg)


def update_patch_cl_atomic(
    project_file: str, changespec_name: str, new_cl: str | None
) -> None:
    """Legacy alias for :func:`update_patch_pr_url_atomic`."""
    update_patch_pr_url_atomic(project_file, changespec_name, new_cl)


update_changespec_pr_url_atomic = update_patch_pr_url_atomic  # legacy API alias


def reset_patch_pr_url(project_file: str, changespec_name: str) -> bool:
    """
    Remove the PR URL field from a Patch.

    Args:
        project_file: Path to the ProjectSpec file
        changespec_name: NAME of the ChangeSpec to update

    Returns:
        True if reset succeeded, False otherwise
    """
    try:
        update_patch_pr_url_atomic(project_file, changespec_name, None)
        logger.info(f"Removed PR field for {changespec_name}")
        return True
    except Exception as e:
        logger.error(f"Error resetting PR for {changespec_name}: {e}")
        return False


def reset_patch_cl(project_file: str, changespec_name: str) -> bool:
    """Legacy CL alias for :func:`reset_patch_pr_url`."""
    return reset_patch_pr_url(project_file, changespec_name)


reset_changespec_pr_url = reset_patch_pr_url  # legacy API alias
reset_changespec_cl = reset_patch_cl  # legacy API alias


def read_status_from_lines(lines: list[str], changespec_name: str) -> str | None:
    """Read STATUS from file lines (unlocked helper).

    Public entry point — calls
    :func:`sase.core.status_facade.read_status_from_lines`, which
    delegates directly to the Rust binding.
    :func:`_read_status_from_lines_python` below is the host-logic golden
    reference used by parity tests.
    """
    from sase.core.status_facade import read_status_from_lines as _facade

    return _facade(lines, changespec_name)


def _read_status_from_lines_python(
    lines: list[str], changespec_name: str
) -> str | None:
    """Host-logic golden reference for :func:`read_status_from_lines`.

    Args:
        lines: File lines to search.
        changespec_name: NAME of the ChangeSpec to find.

    Returns:
        Current STATUS value, or None if not found.
    """
    in_target_patch = False
    for line in lines:
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_patch = current_name == changespec_name
        if in_target_patch and line.startswith("STATUS:"):
            return line.split(":", 1)[1].strip()
    return None


def _apply_parent_update(
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
    in_target_patch = False
    found_parent_line = False
    in_description = False

    for line in lines:
        # Check if this is a NAME field
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_patch = current_name == changespec_name
            found_parent_line = False
            in_description = False

        # Track when we're in the DESCRIPTION field
        if in_target_patch and line.startswith("DESCRIPTION:"):
            in_description = True

        # Update PARENT if we're in the target Patch
        if in_target_patch and line.startswith("PARENT:"):
            found_parent_line = True
            # Replace the PARENT line, or skip it entirely if resetting to None
            if new_parent is not None:
                updated_lines.append(f"PARENT: {new_parent}\n")
            # When new_parent is None, we simply skip this line (don't append it)
        elif (
            in_target_patch
            and in_description
            and (is_review_url_line(line) or line.startswith("STATUS:"))
            and not found_parent_line
        ):
            # PARENT field doesn't exist - add it before PR or STATUS if we have value
            if new_parent is not None:
                updated_lines.append(f"PARENT: {new_parent}\n")
                found_parent_line = True
            in_description = False
            updated_lines.append(line)
        else:
            # End description section when we hit another field
            if (
                in_target_patch
                and in_description
                and line.startswith(("PARENT:", *REVIEW_URL_PREFIXES, "STATUS:"))
            ):
                in_description = False
            updated_lines.append(line)

    return "".join(updated_lines)


def update_patch_parent_atomic(
    project_file: str, changespec_name: str, new_parent: str | None
) -> None:
    """Update the PARENT field of a specific Patch in the project file.

    Acquires a lock for the entire read-modify-write cycle.
    If the PARENT field doesn't exist and new_parent is not None, it will be
    added before the PR or STATUS field.

    Args:
        project_file: Path to the ProjectSpec file
        changespec_name: NAME of the ChangeSpec to update
        new_parent: New PARENT value (None to remove)
    """
    commit_msg = (
        f"Update PARENT to {new_parent} for {changespec_name}"
        if new_parent
        else f"Remove PARENT for {changespec_name}"
    )

    with patch_lock(project_file):
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_content = _apply_parent_update(lines, changespec_name, new_parent)

        write_patch_atomic(project_file, updated_content, commit_msg)


def update_parent_references_atomic(
    project_file: str, old_name: str, new_name: str
) -> None:
    """Update all PARENT field references from old_name to new_name.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file
        old_name: The old name to replace in PARENT fields
        new_name: The new name to use in PARENT fields
    """
    with patch_lock(project_file):
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = []
        for line in lines:
            if line.startswith("PARENT: "):
                current_parent = line[8:].strip()
                if current_parent == old_name:
                    updated_lines.append(f"PARENT: {new_name}\n")
                    continue
            updated_lines.append(line)

        write_patch_atomic(
            project_file,
            "".join(updated_lines),
            f"Update PARENT references from {old_name} to {new_name}",
        )


_FIELD_HEADERS = PROJECT_SPEC_SECTION_HEADERS


def _is_field_or_section_header(line: str) -> bool:
    """Check if a line starts with a known Patch field/section header."""
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


def _apply_description_update(
    lines: list[str], changespec_name: str, new_description: str
) -> str:
    """Apply DESCRIPTION field update to file lines.

    Finds the target Patch by NAME, then replaces the DESCRIPTION header
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
    in_target_patch = False
    skipping_old_description = False

    for line in lines:
        # Track which Patch we're in
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_patch = current_name == changespec_name

        # When skipping old description lines, check for end of description
        if skipping_old_description:
            if _is_field_or_section_header(line):
                # Hit the next field — stop skipping, emit this line normally
                skipping_old_description = False
                updated_lines.append(line)
            # Otherwise it's a continuation line (2-space-indented or blank) — skip it
            continue

        # Replace DESCRIPTION header in the target Patch
        if in_target_patch and line.startswith("DESCRIPTION:"):
            updated_lines.extend(_format_description_field(new_description))
            skipping_old_description = True
            continue

        updated_lines.append(line)

    return "".join(updated_lines)


def _apply_bug_update(
    lines: list[str], changespec_name: str, new_bug: str | None
) -> str:
    """Apply BUG field update to file lines.

    Args:
        lines: Current file lines.
        changespec_name: NAME of the ChangeSpec to update.
        new_bug: New BUG value (None to remove).

    Returns:
        Updated file content as a string.
    """
    updated_lines = []
    in_target_patch = False
    found_bug_line = False

    for line in lines:
        if line.startswith("NAME:"):
            current_name = line.split(":", 1)[1].strip()
            in_target_patch = current_name == changespec_name
            found_bug_line = False

        if in_target_patch and line.startswith("BUG:"):
            found_bug_line = True
            if new_bug is not None:
                updated_lines.append(f"BUG: {new_bug}\n")
            # When new_bug is None, skip this line (remove it)
        elif in_target_patch and line.startswith("STATUS:") and not found_bug_line:
            # BUG field doesn't exist — insert before STATUS if we have a value
            if new_bug is not None:
                updated_lines.append(f"BUG: {new_bug}\n")
                found_bug_line = True
            updated_lines.append(line)
        else:
            updated_lines.append(line)

    return "".join(updated_lines)


def update_patch_bug_atomic(
    project_file: str, changespec_name: str, new_bug: str | None
) -> None:
    """Update the BUG field of a specific Patch in the project file.

    Acquires a lock for the entire read-modify-write cycle.
    If the BUG field doesn't exist and new_bug is not None, it will be
    added before the STATUS field.

    Args:
        project_file: Path to the ProjectSpec file
        changespec_name: NAME of the ChangeSpec to update
        new_bug: New BUG value (None to remove)
    """
    commit_msg = (
        f"Update BUG to {new_bug} for {changespec_name}"
        if new_bug
        else f"Remove BUG for {changespec_name}"
    )

    with patch_lock(project_file):
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_content = _apply_bug_update(lines, changespec_name, new_bug)

        write_patch_atomic(project_file, updated_content, commit_msg)


update_changespec_bug_atomic = update_patch_bug_atomic  # legacy API alias


def update_patch_description_atomic(
    project_file: str, changespec_name: str, new_description: str
) -> bool:
    """Update the DESCRIPTION field of a specific Patch atomically.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the ProjectSpec file.
        changespec_name: NAME of the ChangeSpec to update.
        new_description: New plain-text description.

    Returns:
        True if update succeeded, False otherwise.
    """
    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            updated_content = _apply_description_update(
                lines, changespec_name, new_description
            )

            write_patch_atomic(
                project_file,
                updated_content,
                f"Update DESCRIPTION for {changespec_name}",
            )
            return True
    except Exception:
        logger.exception("Error updating DESCRIPTION for %s", changespec_name)
        return False


update_changespec_description_atomic = (
    update_patch_description_atomic  # legacy API alias
)
