"""Commit entry renumbering for rewind workflow."""

import re

from sase.spec_writer.client import make_request, submit_spec_write_and_wait
from sase.spec_writer.models import OperationType


def get_lowest_available_letter(
    base_num: int,
    existing_letters: set[str],
) -> str:
    """Get the lowest available proposal letter for a base number.

    Args:
        base_num: The base number for proposals.
        existing_letters: Set of already-used letters.

    Returns:
        The lowest available letter (a-z).
    """
    for letter in "abcdefghijklmnopqrstuvwxyz":
        if letter not in existing_letters:
            return letter
    raise ValueError("No available proposal letters (a-z all used)")


def update_hooks_with_id_mapping(
    lines: list[str],
    cl_name: str,
    id_mapping: dict[str, str | None],
) -> list[str]:
    """Update hook status lines with new entry IDs based on the mapping.

    Entries mapped to None are deleted.

    Args:
        lines: All lines from the project file.
        cl_name: The CL name.
        id_mapping: Mapping from old entry IDs to new entry IDs (or None for deletion).

    Returns:
        Updated lines with hook status lines renumbered.
    """
    updated_lines: list[str] = []
    in_target_changespec = False
    in_hooks = False

    for line in lines:
        if line.startswith("NAME: "):
            current_name = line[6:].strip()
            in_target_changespec = current_name == cl_name
            in_hooks = False
            updated_lines.append(line)
        elif in_target_changespec and line.startswith("HOOKS:"):
            in_hooks = True
            updated_lines.append(line)
        elif in_target_changespec and in_hooks and line.startswith("      | "):
            # This is a status line (6-space + "| " prefixed)
            stripped = line.strip()[2:]  # Skip "| " prefix
            # Match status line format: (N) or (Na) or (Na-M) followed by rest
            status_match = re.match(r"^\((\d+[a-z]?)(?:-\d+)?\)(.*)$", stripped)
            if status_match:
                old_id = status_match.group(1)
                rest = status_match.group(2)

                # Check if this entry should be deleted
                if old_id in id_mapping and id_mapping[old_id] is None:
                    # Skip this line (delete it)
                    continue

                # Update any proposal ID suffix (e.g., "- (1a)" -> "- (2)")
                suffix_match = re.search(r" - \((\d+[a-z])(\s*\|[^)]+)?\)$", rest)
                if suffix_match:
                    old_suffix_id = suffix_match.group(1)
                    summary_part = suffix_match.group(2) or ""
                    new_suffix_id = id_mapping.get(old_suffix_id)
                    if new_suffix_id is None:
                        # Suffix entry is being deleted, remove the suffix
                        rest = re.sub(r" - \(\d+[a-z](?:\s*\|[^)]+)?\)$", "", rest)
                    elif new_suffix_id != old_suffix_id:
                        rest = re.sub(
                            r" - \(\d+[a-z](?:\s*\|[^)]+)?\)$",
                            f" - ({new_suffix_id}{summary_part})",
                            rest,
                        )

                # Map the entry ID
                new_id = id_mapping.get(old_id, old_id)
                if new_id is not None:
                    updated_lines.append(f"      | ({new_id}){rest}\n")
            else:
                updated_lines.append(line)
        elif in_target_changespec and in_hooks:
            # Check if still in hooks section
            if line.startswith("  ") and not line.startswith("    "):
                # Command line (2-space indented, not 4-space) - still in hooks
                updated_lines.append(line)
            elif line.strip() == "":
                # Blank line - might end hooks section
                in_hooks = False
                updated_lines.append(line)
            else:
                # End of hooks section
                in_hooks = False
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    return updated_lines


def update_mentors_with_id_mapping(
    lines: list[str],
    cl_name: str,
    id_mapping: dict[str, str | None],
    selected_entry_num: int,
) -> list[str]:
    """Update MENTORS entry IDs and suffixes based on the mapping.

    Entries mapped to None are deleted. Additionally, orphaned MENTORS entries
    (numeric entries > selected_entry_num that aren't in the id_mapping) are
    also deleted.

    Args:
        lines: All lines from the project file.
        cl_name: The CL name.
        id_mapping: Mapping from old entry IDs to new entry IDs (or None for deletion).
        selected_entry_num: The entry number being rewound to.

    Returns:
        Updated lines with mentor entries renumbered.
    """
    updated_lines: list[str] = []
    in_target_changespec = False
    in_mentors = False
    skip_status_lines = (
        False  # Track if we're skipping status lines for a deleted entry
    )

    for line in lines:
        if line.startswith("NAME: "):
            current_name = line[6:].strip()
            in_target_changespec = current_name == cl_name
            in_mentors = False
            skip_status_lines = False
            updated_lines.append(line)
        elif in_target_changespec and line.startswith("MENTORS:"):
            in_mentors = True
            skip_status_lines = False
            updated_lines.append(line)
        elif in_target_changespec and in_mentors:
            # Check if this is an entry header line: (N) profile1 [profile2 ...]
            entry_match = re.match(r"^  \((\d+[a-z]?)\)\s+(.*)$", line)
            if entry_match:
                old_id = entry_match.group(1)
                rest = entry_match.group(2)
                new_id = id_mapping.get(old_id, old_id)

                # Check for orphaned numeric entries > selected_entry_num
                # These are MENTORS entries for commits that don't exist in COMMITS
                if new_id is not None and old_id not in id_mapping:
                    id_match = re.match(r"^(\d+)([a-z])?$", old_id)
                    if id_match:
                        num = int(id_match.group(1))
                        letter = id_match.group(2)
                        if letter is None and num > selected_entry_num:
                            new_id = None  # Mark for deletion

                if new_id is None:
                    # Delete this entry and its status lines
                    skip_status_lines = True
                    continue
                else:
                    skip_status_lines = False
                    if new_id != old_id:
                        updated_lines.append(f"  ({new_id}) {rest}\n")
                    else:
                        updated_lines.append(line)
            elif skip_status_lines and line.startswith("      | "):
                # Skip status lines for deleted entries
                continue
            elif line.startswith("      | "):
                # Status line - check for entry_ref suffix
                suffix_match = re.search(r" - \((\d+[a-z])\)$", line)
                if suffix_match:
                    old_suffix_id = suffix_match.group(1)
                    new_suffix_id = id_mapping.get(old_suffix_id)
                    if new_suffix_id is None:
                        # Suffix entry is being deleted, remove the suffix
                        updated_line = re.sub(r" - \(\d+[a-z]\)$", "", line)
                        updated_lines.append(updated_line)
                    elif new_suffix_id != old_suffix_id:
                        updated_line = re.sub(
                            r" - \(\d+[a-z]\)$",
                            f" - ({new_suffix_id})",
                            line,
                        )
                        updated_lines.append(updated_line)
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)
            elif line.strip() == "":
                # Blank line - might end mentors section
                in_mentors = False
                skip_status_lines = False
                updated_lines.append(line)
            else:
                # End of mentors section
                in_mentors = False
                skip_status_lines = False
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    return updated_lines


def update_comments_with_id_mapping(
    lines: list[str],
    cl_name: str,
    id_mapping: dict[str, str | None],
) -> list[str]:
    """Update COMMENTS entry_ref suffixes based on the mapping.

    Args:
        lines: All lines from the project file.
        cl_name: The CL name.
        id_mapping: Mapping from old entry IDs to new entry IDs (or None for deletion).

    Returns:
        Updated lines with comment entry_ref suffixes renumbered.
    """
    updated_lines: list[str] = []
    in_target_changespec = False
    in_comments = False

    for line in lines:
        if line.startswith("NAME: "):
            current_name = line[6:].strip()
            in_target_changespec = current_name == cl_name
            in_comments = False
            updated_lines.append(line)
        elif in_target_changespec and line.startswith("COMMENTS:"):
            in_comments = True
            updated_lines.append(line)
        elif in_target_changespec and in_comments:
            if line.startswith("  ["):
                # Comment entry line - check for entry_ref suffix
                suffix_match = re.search(r" - \((\d+[a-z])\)$", line)
                if suffix_match:
                    old_suffix_id = suffix_match.group(1)
                    new_suffix_id = id_mapping.get(old_suffix_id)
                    if new_suffix_id is None:
                        # Suffix entry is being deleted, remove the suffix
                        updated_line = re.sub(r" - \(\d+[a-z]\)$", "", line)
                        updated_lines.append(updated_line)
                    elif new_suffix_id != old_suffix_id:
                        updated_line = re.sub(
                            r" - \(\d+[a-z]\)$",
                            f" - ({new_suffix_id})",
                            line,
                        )
                        updated_lines.append(updated_line)
                    else:
                        updated_lines.append(line)
                else:
                    updated_lines.append(line)
            else:
                # End of comments section
                in_comments = False
                updated_lines.append(line)
        else:
            updated_lines.append(line)

    return updated_lines


def rewind_commit_entries(
    project_file: str,
    cl_name: str,
    selected_entry_num: int,
) -> bool:
    """Update ChangeSpec after rewinding to a previous entry.

    The renumbering logic:
    1. Keep entries 1...(selected-1) as accepted entries (unchanged)
    2. Keep selected entry (N) as (N) but add "(!: NEW PROPOSAL)" suffix
    3. Convert entry (N+1) to proposal (Na) with "(!: NEW PROPOSAL)" suffix
    4. Keep existing proposals for base N (Nb, Nc, etc.) unchanged
    5. Delete ALL entries after (N+1) (entries N+2, N+3, ...)
    6. Update all references in HOOKS/MENTORS/COMMENTS

    Example: Entries (1), (2), (3), (3a), (3b), (4), (5), (6), rewind to (3):
    - Keep (1), (2) as accepted
    - Keep (3) as (3) with NEW PROPOSAL suffix
    - Keep (3a), (3b) unchanged
    - Convert (4) to (3c) with NEW PROPOSAL suffix (lowest available letter)
    - Delete (5), (6)

    Result: (1), (2), (3)[NEW PROPOSAL], (3a), (3b), (3c)[was 4, NEW PROPOSAL]

    Args:
        project_file: Path to the project file.
        cl_name: The CL name.
        selected_entry_num: The entry number being rewound to.

    Returns:
        True if successful, False otherwise.
    """
    try:
        request = make_request(
            project_file,
            OperationType.REWIND_COMMIT_ENTRIES,
            {
                "cl_name": cl_name,
                "selected_entry_num": selected_entry_num,
            },
        )
        response = submit_spec_write_and_wait(request, timeout=10.0)
        return response.success
    except Exception:
        return False
