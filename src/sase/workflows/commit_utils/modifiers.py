"""Functions for modifying existing COMMITS entries in Patches."""

import re

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.ace.patch.section_order import PROJECT_SPEC_SECTION_HEADERS
from sase.ace.patch.storage import is_stitch_section_header


def reject_proposals_and_set_status_atomic(
    project_file: str,
    cl_name: str,
    final_status: str,
) -> bool:
    """Reject all new proposals and optionally set STATUS in a single atomic write.

    Args:
        project_file: Path to the project file.
        cl_name: The Patch name to update.
        final_status: The final status to set. Should be either:
            - "Mailed" to set status directly to Mailed
            - Empty string to keep current status unchanged

    Returns:
        True if successful, False otherwise.
    """
    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            # Track state while parsing
            in_target_patch = False
            in_commits = False
            rejected_count = 0
            status_line_idx: int | None = None
            current_status: str | None = None

            for i, line in enumerate(lines):
                if line.startswith("NAME: "):
                    current_name = line[6:].strip()
                    in_target_patch = current_name == cl_name
                    in_commits = False
                elif in_target_patch:
                    if line.startswith("STATUS:"):
                        # Capture the status line index and current value
                        status_line_idx = i
                        current_status = line[7:].strip()
                        in_commits = False
                    elif is_stitch_section_header(line):
                        in_commits = True
                    elif line.startswith(PROJECT_SPEC_SECTION_HEADERS):
                        in_commits = False
                        if line.startswith("NAME:"):
                            in_target_patch = False
                    elif in_commits:
                        stripped = line.strip()
                        # Match: (Na) Note text - (!: NEW PROPOSAL)
                        entry_match = re.match(
                            r"^\((\d+[a-z])\)\s+(.+?)\s+-\s+\(!:\s*NEW PROPOSAL\)$",
                            stripped,
                        )
                        if entry_match:
                            matched_id = entry_match.group(1)
                            note_text = entry_match.group(2)
                            # Preserve leading whitespace
                            leading_ws = line[: len(line) - len(line.lstrip())]
                            # Change (!: NEW PROPOSAL) to (~!: NEW PROPOSAL)
                            new_line = (
                                f"{leading_ws}({matched_id}) {note_text} - "
                                f"(~!: NEW PROPOSAL)\n"
                            )
                            lines[i] = new_line
                            rejected_count += 1

            # Must have found the status line
            if status_line_idx is None or current_status is None:
                return False

            # Update the status line based on final_status
            if final_status:
                new_status = final_status
                lines[status_line_idx] = f"STATUS: {new_status}\n"
            else:
                new_status = current_status

            # Write atomically
            write_patch_atomic(
                project_file,
                "".join(lines),
                f"Reject {rejected_count} proposal(s) and set status to "
                f"'{new_status}' for {cl_name}",
            )
            return True
    except Exception:
        return False


def reject_all_new_proposals(
    project_file: str,
    cl_name: str,
) -> int:
    """Reject all new proposals by changing (!: NEW PROPOSAL) to (~!: NEW PROPOSAL).

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the project file.
        cl_name: The Patch name to update.

    Returns:
        Number of proposals rejected, or -1 on error.
    """
    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            # Find and update all new proposals
            in_target_patch = False
            in_commits = False
            rejected_count = 0

            for i, line in enumerate(lines):
                if line.startswith("NAME: "):
                    current_name = line[6:].strip()
                    in_target_patch = current_name == cl_name
                    in_commits = False
                elif in_target_patch:
                    if is_stitch_section_header(line):
                        in_commits = True
                    elif line.startswith(PROJECT_SPEC_SECTION_HEADERS):
                        in_commits = False
                        if line.startswith("NAME:"):
                            in_target_patch = False
                    elif in_commits:
                        stripped = line.strip()
                        # Match: (Na) Note text - (!: NEW PROPOSAL)
                        entry_match = re.match(
                            r"^\((\d+[a-z])\)\s+(.+?)\s+-\s+\(!:\s*NEW PROPOSAL\)$",
                            stripped,
                        )
                        if entry_match:
                            matched_id = entry_match.group(1)
                            note_text = entry_match.group(2)
                            # Preserve leading whitespace
                            leading_ws = line[: len(line) - len(line.lstrip())]
                            # Change (!: NEW PROPOSAL) to (~!: NEW PROPOSAL)
                            new_line = (
                                f"{leading_ws}({matched_id}) {note_text} - "
                                f"(~!: NEW PROPOSAL)\n"
                            )
                            lines[i] = new_line
                            rejected_count += 1

            if rejected_count == 0:
                return 0

            # Write atomically
            write_patch_atomic(
                project_file,
                "".join(lines),
                f"Reject {rejected_count} new proposal(s) for {cl_name}",
            )
            return rejected_count
    except Exception:
        return -1


def update_commit_entry_suffix(
    project_file: str,
    cl_name: str,
    entry_id: str,
    new_suffix_type: str,
) -> bool:
    """Update or remove the suffix of a COMMITS entry.

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project_file: Path to the project file.
        cl_name: The Patch name to update.
        entry_id: The entry ID to update (e.g., "2a").
        new_suffix_type: The action - "remove" to remove suffix, "reject" to change
            (!: MSG) to (~!: MSG).

    Returns:
        True if successful, False otherwise.
    """
    if new_suffix_type not in ("remove", "reject"):
        return False

    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            # Find the target entry and update its suffix
            in_target_patch = False
            in_commits = False
            updated = False

            for i, line in enumerate(lines):
                if line.startswith("NAME: "):
                    current_name = line[6:].strip()
                    in_target_patch = current_name == cl_name
                    in_commits = False
                elif in_target_patch:
                    if is_stitch_section_header(line):
                        in_commits = True
                    elif line.startswith(PROJECT_SPEC_SECTION_HEADERS):
                        in_commits = False
                        if line.startswith("NAME:"):
                            in_target_patch = False
                    elif in_commits:
                        stripped = line.strip()
                        # Match entry with this ID: (Na) Note text - (!: MSG) or - (~: MSG)
                        entry_match = re.match(
                            rf"^\(({re.escape(entry_id)})\)\s+(.+?)\s+-\s+\((!:|~:)\s*([^)]+)\)$",
                            stripped,
                        )
                        if entry_match:
                            matched_id = entry_match.group(1)
                            note_text = entry_match.group(2)
                            suffix_prefix = entry_match.group(3)
                            suffix_msg = entry_match.group(4)
                            # Preserve leading whitespace
                            leading_ws = line[: len(line) - len(line.lstrip())]
                            if new_suffix_type == "remove":
                                # Remove the suffix entirely
                                new_line = f"{leading_ws}({matched_id}) {note_text}\n"
                            else:  # reject
                                # Change (!: MSG) to (~!: MSG)
                                if suffix_prefix == "!:":
                                    new_line = (
                                        f"{leading_ws}({matched_id}) {note_text} - "
                                        f"(~!: {suffix_msg})\n"
                                    )
                                else:
                                    # Not an error suffix, don't change
                                    continue
                            lines[i] = new_line
                            updated = True
                            break

            if not updated:
                return False

            # Write atomically
            action = "Remove" if new_suffix_type == "remove" else "Reject"
            write_patch_atomic(
                project_file,
                "".join(lines),
                f"{action} suffix from commit entry {entry_id} for {cl_name}",
            )
            return True
    except Exception:
        return False


def mark_proposal_broken(
    project_file: str,
    cl_name: str,
    entry_id: str,
) -> bool:
    """Mark a proposal as broken by setting its suffix to (~!: BROKEN PROPOSAL).

    This is called when a proposal's diff fails to apply to a workspace.
    Broken proposals are skipped in future hook runs.
    Works regardless of the current suffix (NEW PROPOSAL, no suffix, etc.).

    Args:
        project_file: Path to the project file.
        cl_name: The Patch name to update.
        entry_id: The proposal entry ID (e.g., "2a").

    Returns:
        True if successful, False otherwise.
    """
    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            in_target_patch = False
            in_commits = False
            updated = False

            for i, line in enumerate(lines):
                if line.startswith("NAME: "):
                    current_name = line[6:].strip()
                    in_target_patch = current_name == cl_name
                    in_commits = False
                elif in_target_patch:
                    if is_stitch_section_header(line):
                        in_commits = True
                    elif line.startswith(PROJECT_SPEC_SECTION_HEADERS):
                        in_commits = False
                        if line.startswith("NAME:"):
                            in_target_patch = False
                    elif in_commits:
                        stripped = line.strip()
                        # Match proposal entry with any suffix or no suffix:
                        #   (Na) Note text - (!: NEW PROPOSAL)
                        #   (Na) Note text - (~!: BROKEN PROPOSAL)
                        #   (Na) Note text
                        entry_match = re.match(
                            rf"^\(({re.escape(entry_id)})\)\s+(.+?)(?:\s+-\s+\([^)]+\))?$",
                            stripped,
                        )
                        if entry_match:
                            matched_id = entry_match.group(1)
                            note_text = entry_match.group(2)
                            leading_ws = line[: len(line) - len(line.lstrip())]
                            # Set to (~!: BROKEN PROPOSAL)
                            new_line = (
                                f"{leading_ws}({matched_id}) {note_text} - "
                                f"(~!: BROKEN PROPOSAL)\n"
                            )
                            lines[i] = new_line
                            updated = True
                            break

            if not updated:
                return False

            write_patch_atomic(
                project_file,
                "".join(lines),
                f"Mark proposal {entry_id} as broken for {cl_name}",
            )
            return True
    except Exception:
        return False
