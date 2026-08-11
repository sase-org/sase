"""Functions for manipulating Patch files."""

import os

from sase.ace.patch import patch_lock, write_patch_atomic
from sase.ace.patch.storage import DEFAULT_STITCH_SECTION_HEADER, format_patch_block
from sase.output import print_status
from sase.workflows.utils import get_project_file_path


def _find_patch_end_line(lines: list[str], changespec_name: str) -> int | None:
    """Find the line number where a Patch ends.

    A Patch ends at the last non-empty line before either:
    - The next NAME: field
    - The end of the file

    Args:
        lines: List of lines from the project file.
        changespec_name: NAME of the ChangeSpec to find.

    Returns:
        The line index (0-based) of the last line of the Patch,
        or None if the Patch is not found.
    """
    in_target_patch = False
    patch_end = None

    for i, line in enumerate(lines):
        if line.startswith("NAME: "):
            if in_target_patch:
                # We hit the next Patch, so the previous one ended
                # Find the last non-empty line before this
                for j in range(i - 1, -1, -1):
                    if lines[j].strip():
                        return j
                return i - 1

            # Check if this is the target Patch
            current_name = line[6:].strip()
            if current_name == changespec_name:
                in_target_patch = True
                patch_end = i

        elif in_target_patch and line.strip():
            # Track the last non-empty line in the target Patch
            patch_end = i

    # If we're still in the target Patch at the end of file
    if in_target_patch:
        return patch_end

    return None


def _patch_in_archive(project_file: str, changespec_name: str) -> bool:
    """Return True when ``changespec_name`` appears in the archive file."""
    from sase.ace.patch.archive import get_archive_file_path

    archive_file = get_archive_file_path(project_file)
    if not os.path.isfile(archive_file):
        return False
    try:
        with open(archive_file, encoding="utf-8") as f:
            for line in f:
                if line.startswith("NAME: ") and line[6:].strip() == changespec_name:
                    return True
    except OSError:
        return False
    return False


def _remove_reservation_lines(lines: list[str], reserved_name: str) -> list[str]:
    """Remove a ``Reserved`` Patch stub from a list of file lines.

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
    """Remove a ``Reserved`` Patch entry from the project file.

    Called when the VCS push fails so stale reservations don't accumulate.

    Args:
        project: Project name.
        reserved_name: The suffixed name that was reserved.
    """
    project_file = get_project_file_path(project)
    if not os.path.isfile(project_file):
        return

    try:
        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            new_lines = _remove_reservation_lines(lines, reserved_name)
            if len(new_lines) != len(lines):
                write_patch_atomic(
                    project_file,
                    "".join(new_lines),
                    f"Remove reservation {reserved_name}",
                )
    except Exception as e:
        print_status(f"Failed to remove reservation {reserved_name}: {e}", "warning")


def _remote_taken_suffix_names(base_name: str, cwd: str) -> set[str]:
    """Return ``<base_name>_<N>`` names whose branch already exists on the remote.

    Consulted so the reserved Patch name stays consistent with the remote
    branch namespace.  Best-effort: any failure (no provider, no remote,
    network error) yields an empty set so suffix allocation degrades to the
    Patch-only behaviour.
    """
    try:
        from sase.vcs_provider import get_vcs_provider

        provider = get_vcs_provider(cwd)
        suffixes = provider.existing_branch_suffixes(base_name, cwd)
        return {f"{base_name}_{n}" for n in suffixes}
    except Exception:
        return set()


def compute_suffixed_cl_name(
    project: str, cl_name: str, cwd: str | None = None
) -> str | None:
    """Compute the suffixed Patch name and write a reservation.

    Reads existing Patch names from the project file and archive to find
    the next available ``_<N>`` suffix, then writes a minimal ``Reserved``
    Patch entry **within the same lock** to prevent concurrent agents from
    picking the same suffix (TOCTOU race).

    When *cwd* is provided, the remote branch namespace is also consulted (via
    the VCS provider) and any ``_<N>`` whose branch already exists on the remote
    is excluded.  This keeps the reserved Patch name consistent with the
    branch that will be pushed, preventing the orphaned-PR bug where a low
    suffix is reserved in the (nearly empty) Patch namespace but collides
    with a long-lived remote branch at push time.

    Args:
        project: Project name.
        cl_name: Base Patch/branch name to suffix.
        cwd: Working directory of the repo. When given, remote branch suffixes
            are unioned into the taken-name set. When None, only the Patch
            namespace is consulted.

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
        from sase.core.patch import ensure_project_prefix
        from sase.project_display_names import (
            humanize_cl_name,
            project_display_name_for,
        )

        display_project = project_display_name_for(project)
        cl_name = ensure_project_prefix(display_project, humanize_cl_name(cl_name))

        with patch_lock(project_file):
            with open(project_file, encoding="utf-8") as f:
                lines = f.readlines()

            existing_names = set()
            for line in lines:
                if line.startswith("NAME: "):
                    existing_names.add(line[6:].strip())

            from sase.ace.patch.archive import get_archive_file_path

            archive_file = get_archive_file_path(project_file)
            if os.path.isfile(archive_file):
                with open(archive_file, encoding="utf-8") as f:
                    for line in f.readlines():
                        if line.startswith("NAME: "):
                            existing_names.add(line[6:].strip())

            # Union in remote branch suffixes so the reserved name never
            # collides with an already-pushed branch (orphaned-PR root cause).
            if cwd is not None:
                existing_names |= _remote_taken_suffix_names(cl_name, cwd)

            from sase.core.patch import get_next_suffix_number

            suffix_num = get_next_suffix_number(cl_name, existing_names)
            suffixed_name = f"{cl_name}_{suffix_num}"

            # Write a minimal reservation entry so concurrent agents see this
            # name as taken before the lock is released.
            reservation_block = f"\n\nNAME: {suffixed_name}\nSTATUS: Reserved\n"
            lines.append(reservation_block)
            write_patch_atomic(
                project_file,
                "".join(lines),
                f"Reserve {suffixed_name}",
            )

            return suffixed_name
    except Exception as e:
        print_status(f"Failed to compute suffixed Patch name: {e}", "warning")
        return None


def add_patch_to_project_file(
    project: str,
    cl_name: str,
    description: str,
    parent: str | None,
    pr_url: str | None = None,
    initial_hooks: list[str] | None = None,
    initial_commits: list[tuple] | None = None,
    bug: str | None = None,
    pr_origin: str | None = None,
    status: str = "Draft",
    reserved_name: str | None = None,
    **legacy_kwargs: object,
) -> str | None:
    """Add a new Patch to the project file.

    The Patch is placed:
    - Directly after the parent Patch if parent is specified
    - At the top of the file (after BUG: header) if no parent

    Acquires a lock for the entire read-modify-write cycle.

    Args:
        project: Project name.
        cl_name: NAME field value (will be suffixed with _<N> for uniqueness).
        description: DESCRIPTION field value (raw, will be indented).
        parent: PARENT field value (or None for "None").
        pr_url: PR/review URL. If None, the PR line is omitted from the
            Patch.
        initial_hooks: List of hook commands to include in the HOOKS field.
            If None or empty, no HOOKS field is added.
        initial_commits: List of tuples for the COMMITS field. Tuple shape is
            ``(number, note, chat_path, diff_path[, commit_body[, plan_path]])``.
            chat_path, diff_path, and plan_path are optional drawer paths.
            If None or empty, no COMMITS field is added.
        bug: BUG field value (e.g., "http://b/12345"). If None, no BUG field
            is added.
        pr_origin: PR origin marker (``sase``, ``external``, or ``unknown``).
            If None, no PR_ORIGIN field is added.
        status: STATUS field value (e.g., "Draft", "WIP"). Defaults to "Draft".
        reserved_name: Pre-computed suffixed name from a prior reservation.
            When provided, the existing ``Reserved`` entry for this name is
            replaced in-place with the full Patch, skipping suffix
            recomputation.

    Returns:
        The suffixed cl_name (e.g., "foo_bar_1") on success, None on failure.
    """
    legacy_cl_url = legacy_kwargs.pop("cl_url", None)
    legacy_kwargs.pop("cl_label", None)
    legacy_kwargs.pop("pr_label", None)
    if legacy_kwargs:
        unexpected = next(iter(legacy_kwargs))
        raise TypeError(f"unexpected keyword argument: {unexpected}")
    if pr_url is None and legacy_cl_url is not None:
        pr_url = str(legacy_cl_url)

    project_file = get_project_file_path(project)

    # Ensure project file exists before trying to add a Patch
    if not os.path.isfile(project_file):
        from sase.workflows.commit.project_file_utils import create_project_file

        if not create_project_file(project):
            return None

    # PARENT line and BUG line are built later, after parent resolution and
    # potential parent inheritance.

    # Build COMMITS field if initial_commits provided
    commits_block = ""
    timestamps_block = ""
    if initial_commits:
        from sase.ace.timestamps.recording import format_timestamp_entry_line
        from sase.workflows.commit_utils.entries import format_chat_line_with_duration

        commits_lines = [f"{DEFAULT_STITCH_SECTION_HEADER}\n"]
        timestamps_lines = ["TIMESTAMPS:\n"]
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
            timestamps_lines.append(format_timestamp_entry_line("COMMIT", f"({num})"))
        commits_block = "".join(commits_lines)
        timestamps_block = "".join(timestamps_lines)

    try:
        with patch_lock(project_file):
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
                from sase.ace.patch.archive import get_archive_file_path

                archive_file = get_archive_file_path(project_file)
                if os.path.isfile(archive_file):
                    with open(archive_file, encoding="utf-8") as f:
                        for line in f.readlines():
                            if line.startswith("NAME: "):
                                existing_names.add(line[6:].strip())

                # Add _<N> suffix to make name unique (for WIP Patches)
                from sase.core.patch import get_next_suffix_number

                suffix_num = get_next_suffix_number(cl_name, existing_names)
                cl_name = f"{cl_name}_{suffix_num}"

            # Determine insertion point and collect parent hooks
            parent_hooks_to_add: list[str] = []
            if parent:
                # Find the end of the parent Patch
                parent_end = _find_patch_end_line(lines, parent)
                if parent_end is not None:
                    # Insert after parent Patch
                    insert_index = parent_end + 1

                    # Get parent hooks and BUG to inherit
                    from sase.ace.patch import parse_project_file

                    patches = parse_project_file(project_file)
                    for cs in patches:
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
                elif _patch_in_archive(project_file, parent):
                    # Parent is a terminal CS (submitted / reverted / archived);
                    # keep the PARENT reference but append to end of file.
                    insert_index = len(lines)
                else:
                    # Parent does not exist in this project at all. Guard
                    # against bogus values (e.g., a VCS ref like ``p4head`` or
                    # ``origin/main``) leaking into the PARENT field by
                    # dropping it and warning loudly.
                    print_status(
                        f"Parent Patch '{parent}' does not exist — "
                        "omitting PARENT field.",
                        "warning",
                    )
                    parent = None
                    insert_index = len(lines)
            else:
                # No parent - append to end of file
                insert_index = len(lines)

            # Build HOOKS field with initial hooks + inherited parent hooks
            all_hooks = list(initial_hooks or []) + parent_hooks_to_add
            hooks_block = ""
            if all_hooks:
                hooks_lines = ["HOOKS:\n"]
                for hook_cmd in all_hooks:
                    hooks_lines.append(f"  {hook_cmd}\n")
                hooks_block = "".join(hooks_lines)

            # Build the Patch block with the suffixed name
            patch_block = format_patch_block(
                name=cl_name,
                description=description,
                parent=parent,
                pr_url=pr_url,
                pr_origin=pr_origin,
                bug=bug,
                status=status,
                commits_block=commits_block,
                hooks_block=hooks_block,
                timestamps_block=timestamps_block,
            )

            # Insert the new Patch
            lines.insert(insert_index, patch_block)

            # Write atomically
            write_patch_atomic(
                project_file,
                "".join(lines),
                f"Add Patch {cl_name}",
            )

        return cl_name
    except Exception as e:
        print_status(f"Failed to add Patch to project file: {e}", "warning")
        return None


compute_suffixed_patch_name = compute_suffixed_cl_name
add_patch_to_project_file = add_patch_to_project_file


__all__ = [
    "add_patch_to_project_file",
    "add_patch_to_project_file",
    "compute_suffixed_cl_name",
    "compute_suffixed_patch_name",
    "remove_reservation",
]
