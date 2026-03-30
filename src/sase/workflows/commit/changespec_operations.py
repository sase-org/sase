"""Functions for manipulating ChangeSpec files."""

import os

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.output import print_status
from sase.workflows.utils import get_project_file_path


def _find_changespec_end_line(lines: list[str], changespec_name: str) -> int | None:
    """Find the line number where a ChangeSpec ends.

    A ChangeSpec ends at the last non-empty line before either:
    - The next NAME: field
    - The end of the file

    Args:
        lines: List of lines from the project file.
        changespec_name: NAME of the ChangeSpec to find.

    Returns:
        The line index (0-based) of the last line of the ChangeSpec,
        or None if the ChangeSpec is not found.
    """
    in_target_changespec = False
    changespec_end = None

    for i, line in enumerate(lines):
        if line.startswith("NAME: "):
            if in_target_changespec:
                # We hit the next ChangeSpec, so the previous one ended
                # Find the last non-empty line before this
                for j in range(i - 1, -1, -1):
                    if lines[j].strip():
                        return j
                return i - 1

            # Check if this is the target ChangeSpec
            current_name = line[6:].strip()
            if current_name == changespec_name:
                in_target_changespec = True
                changespec_end = i

        elif in_target_changespec and line.strip():
            # Track the last non-empty line in the target ChangeSpec
            changespec_end = i

    # If we're still in the target ChangeSpec at the end of file
    if in_target_changespec:
        return changespec_end

    return None


def _remove_reservation_lines(lines: list[str], reserved_name: str) -> list[str]:
    """Remove a ``Reserved`` ChangeSpec stub from a list of file lines.

    Returns a new list with the reservation block (NAME + STATUS lines and
    surrounding blank lines) stripped out.
    """
    name_line = f"NAME: {reserved_name}\n"
    status_line = "STATUS: Reserved\n"
    result: list[str] = []
    i = 0
    while i < len(lines):
        if lines[i] == name_line:
            # Check if the next non-blank line is STATUS: Reserved
            j = i + 1
            while j < len(lines) and lines[j].strip() == "":
                j += 1
            if j < len(lines) and lines[j] == status_line:
                # Skip trailing blank lines after STATUS line
                j += 1
                while j < len(lines) and lines[j].strip() == "":
                    j += 1
                # Also remove leading blank lines before NAME
                while result and result[-1].strip() == "":
                    result.pop()
                i = j
                continue
        result.append(lines[i])
        i += 1
    return result


def remove_reservation(project: str, reserved_name: str) -> None:
    """Remove a ``Reserved`` ChangeSpec entry from the project file.

    Called when the VCS push fails so stale reservations don't accumulate.

    Args:
        project: Project name.
        reserved_name: The suffixed name that was reserved.
    """
    project_file = get_project_file_path(project)
    if not os.path.isfile(project_file):
        return

    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = _remove_reservation_lines(lines, reserved_name)
            if len(new_lines) != len(lines):
                write_changespec_atomic(
                    project_file,
                    "".join(new_lines),
                    f"Remove reservation {reserved_name}",
                )
    except Exception as e:
        print_status(f"Failed to remove reservation {reserved_name}: {e}", "warning")


def compute_suffixed_cl_name(project: str, cl_name: str) -> str | None:
    """Compute the suffixed CL name and write a reservation to the project file.

    Reads existing ChangeSpec names from the project file and archive to find
    the next available ``_<N>`` suffix, then writes a minimal ``Reserved``
    ChangeSpec entry **within the same lock** to prevent concurrent agents from
    picking the same suffix (TOCTOU race).

    Args:
        project: Project name.
        cl_name: Base CL name to suffix.

    Returns:
        The suffixed name, or None if the project file doesn't exist and can't
        be created.
    """
    project_file = get_project_file_path(project)

    if not os.path.isfile(project_file):
        from sase.workflows.commit.project_file_utils import create_project_file

        if not create_project_file(project):
            return None

    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            existing_names = set()
            for line in lines:
                if line.startswith("NAME: "):
                    existing_names.add(line[6:].strip())

            from sase.ace.changespec.archive import get_archive_file_path

            archive_file = get_archive_file_path(project_file)
            if os.path.isfile(archive_file):
                with open(archive_file, encoding="utf-8") as f:
                    for line in f.readlines():
                        if line.startswith("NAME: "):
                            existing_names.add(line[6:].strip())

            from sase.core.changespec import get_next_suffix_number

            suffix_num = get_next_suffix_number(cl_name, existing_names)
            suffixed_name = f"{cl_name}_{suffix_num}"

            # Write a minimal reservation entry so concurrent agents see this
            # name as taken before the lock is released.
            reservation_block = f"\n\nNAME: {suffixed_name}\nSTATUS: Reserved\n"
            lines.append(reservation_block)
            write_changespec_atomic(
                project_file,
                "".join(lines),
                f"Reserve {suffixed_name}",
            )

            return suffixed_name
    except Exception as e:
        print_status(f"Failed to compute suffixed CL name: {e}", "warning")
        return None


def add_changespec_to_project_file(
    project: str,
    cl_name: str,
    description: str,
    parent: str | None,
    cl_url: str | None = None,
    initial_hooks: list[str] | None = None,
    initial_commits: list[tuple] | None = None,
    bug: str | None = None,
    cl_label: str = "CL",
    status: str = "Draft",
    reserved_name: str | None = None,
) -> str | None:
    """Add a new ChangeSpec to the project file.

    The ChangeSpec is placed:
    - Directly after the parent ChangeSpec if parent is specified
    - At the top of the file (after BUG: header) if no parent

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project: Project name.
        cl_name: NAME field value (will be suffixed with _<N> for uniqueness).
        description: DESCRIPTION field value (raw, will be indented).
        parent: PARENT field value (or None for "None").
        cl_url: CL/PR URL (e.g., ``"http://cl/12345"`` or a GitHub PR URL).
            If None, the CL line is omitted from the ChangeSpec.
        initial_hooks: List of hook commands to include in the HOOKS field.
            If None or empty, no HOOKS field is added.
        initial_commits: List of tuples for the COMMITS field. Tuple shape is
            ``(number, note, chat_path, diff_path[, commit_body[, plan_path]])``.
            chat_path, diff_path, and plan_path are optional drawer paths.
            If None or empty, no COMMITS field is added.
        bug: BUG field value (e.g., "http://b/12345"). If None, no BUG field
            is added.
        status: STATUS field value (e.g., "Draft", "WIP"). Defaults to "Draft".
        reserved_name: Pre-computed suffixed name from a prior reservation.
            When provided, the existing ``Reserved`` entry for this name is
            replaced in-place with the full ChangeSpec, skipping suffix
            recomputation.

    Returns:
        The suffixed cl_name (e.g., "foo_bar_1") on success, None on failure.
    """
    project_file = get_project_file_path(project)

    # Ensure project file exists before trying to add a ChangeSpec
    if not os.path.isfile(project_file):
        from sase.workflows.commit.project_file_utils import create_project_file

        if not create_project_file(project):
            return None

    # Format the description with 2-space indent
    description_lines = description.strip().split("\n")
    formatted_description = "\n".join(f"  {line}" for line in description_lines)

    # Build partial ChangeSpec components (name added after suffix computation)
    # Only include PARENT line if parent is specified
    parent_line = f"PARENT: {parent}\n" if parent else ""
    # BUG line is built later after potential parent inheritance

    # Build COMMITS field if initial_commits provided
    commits_block = ""
    if initial_commits:
        from sase.workflows.commit_utils.entries import format_chat_line_with_duration

        commits_lines = ["COMMITS:\n"]
        for commit_tuple in initial_commits:
            num, note, chat_path, diff_path = commit_tuple[:4]
            commit_body: list[str] | None = (
                commit_tuple[4] if len(commit_tuple) > 4 else None
            )
            plan_path: str | None = commit_tuple[5] if len(commit_tuple) > 5 else None
            commits_lines.append(f"  ({num}) {note}\n")
            if commit_body:
                for body_line in commit_body:
                    if body_line == "":
                        commits_lines.append("      .\n")
                    else:
                        commits_lines.append(f"      {body_line}\n")
            if chat_path:
                commits_lines.append(format_chat_line_with_duration(chat_path))
            if diff_path:
                commits_lines.append(f"      | DIFF: {diff_path}\n")
            if plan_path:
                commits_lines.append(f"      | PLAN: {plan_path}\n")
        commits_block = "".join(commits_lines)

    try:
        with changespec_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            if reserved_name:
                # Use the pre-computed reserved name and remove the
                # reservation stub so we can replace it with the full block.
                cl_name = reserved_name
                lines = _remove_reservation_lines(lines, reserved_name)
            else:
                # Extract existing names to compute unique suffix
                existing_names = set()
                for line in lines:
                    if line.startswith("NAME: "):
                        existing_names.add(line[6:].strip())

                # Also check archive file for existing names
                from sase.ace.changespec.archive import get_archive_file_path

                archive_file = get_archive_file_path(project_file)
                if os.path.isfile(archive_file):
                    with open(archive_file, encoding="utf-8") as f:
                        for line in f.readlines():
                            if line.startswith("NAME: "):
                                existing_names.add(line[6:].strip())

                # Add _<N> suffix to make name unique (for WIP ChangeSpecs)
                from sase.core.changespec import get_next_suffix_number

                suffix_num = get_next_suffix_number(cl_name, existing_names)
                cl_name = f"{cl_name}_{suffix_num}"

            # Determine insertion point and collect parent hooks
            parent_hooks_to_add: list[str] = []
            if parent:
                # Find the end of the parent ChangeSpec
                parent_end = _find_changespec_end_line(lines, parent)
                if parent_end is not None:
                    # Insert after parent ChangeSpec
                    insert_index = parent_end + 1

                    # Get parent hooks and BUG to inherit
                    from sase.ace.changespec import parse_project_file

                    changespecs = parse_project_file(project_file)
                    for cs in changespecs:
                        if cs.name == parent:
                            # Inherit hooks from parent
                            if cs.hooks:
                                # Collect existing hook commands to avoid duplicates
                                existing_hooks = (
                                    set(initial_hooks) if initial_hooks else set()
                                )
                                for hook_entry in cs.hooks:
                                    if hook_entry.command not in existing_hooks:
                                        parent_hooks_to_add.append(hook_entry.command)
                            # Inherit BUG from parent if not explicitly provided
                            if not bug and cs.bug:
                                bug = cs.bug
                            break
                else:
                    # Parent not found, append to end
                    print_status(
                        f"Parent ChangeSpec '{parent}' not found. "
                        "Appending to end of file.",
                        "warning",
                    )
                    insert_index = len(lines)
            else:
                # No parent - append to end of file
                insert_index = len(lines)

            # Build BUG line (may be inherited from parent)
            bug_line = f"BUG: {bug}\n" if bug else ""

            # Build HOOKS field with initial hooks + inherited parent hooks
            all_hooks = list(initial_hooks or []) + parent_hooks_to_add
            hooks_block = ""
            if all_hooks:
                hooks_lines = ["HOOKS:\n"]
                for hook_cmd in all_hooks:
                    hooks_lines.append(f"  {hook_cmd}\n")
                hooks_block = "".join(hooks_lines)

            # Build the ChangeSpec block with the suffixed name
            cl_line = f"{cl_label}: {cl_url}\n" if cl_url else ""
            changespec_block = f"""

NAME: {cl_name}
DESCRIPTION:
{formatted_description}
{parent_line}{bug_line}{cl_line}STATUS: {status}
{commits_block}{hooks_block}"""

            # Insert the new ChangeSpec
            lines.insert(insert_index, changespec_block)

            # Write atomically
            write_changespec_atomic(
                project_file,
                "".join(lines),
                f"Add ChangeSpec {cl_name}",
            )

        # Record COMMIT timestamps for initial commits (outside lock —
        # uses its own lock, matching the pattern in entries.py)
        if initial_commits:
            from sase.ace.timestamps.recording import add_timestamp_entry_atomic

            for commit_tuple in initial_commits:
                num = commit_tuple[0]
                add_timestamp_entry_atomic(project_file, cl_name, "COMMIT", f"({num})")

        return cl_name
    except Exception as e:
        print_status(f"Failed to add ChangeSpec to project file: {e}", "warning")
        return None
