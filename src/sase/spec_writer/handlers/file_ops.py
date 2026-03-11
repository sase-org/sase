"""File-level handlers for spec write operations."""

import os
import re

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse


def handle_add_changespec(request: SpecWriteRequest) -> SpecWriteResponse:
    """Add a new ChangeSpec to the project file."""
    from sase.ace.changespec import parse_project_file
    from sase.commit_utils.entries import format_chat_line_with_duration
    from sase.commit_workflow.changespec_operations import find_changespec_end_line
    from sase.rich_utils import print_status
    from sase.sase_utils import get_next_suffix_number

    cl_name = request.params["cl_name"]
    description = request.params["description"]
    parent = request.params.get("parent")
    cl_url = request.params.get("cl_url")
    initial_hooks = request.params.get("initial_hooks")
    initial_commits = request.params.get("initial_commits")
    bug = request.params.get("bug")
    cl_label = request.params.get("cl_label", "CL")
    status = request.params.get("status", "Draft")

    project_file = request.project_file

    # Ensure project file exists
    if not os.path.isfile(project_file):
        project = request.params["project"]
        from sase.commit_workflow.project_file_utils import create_project_file

        if not create_project_file(project):
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Failed to create project file",
            )

    # Format description
    description_lines = description.strip().split("\n")
    formatted_description = "\n".join(f"  {line}" for line in description_lines)

    parent_line = f"PARENT: {parent}\n" if parent else ""

    # Build COMMITS field
    commits_block = ""
    if initial_commits:
        commits_lines = ["COMMITS:\n"]
        for num, note, chat_path, diff_path in initial_commits:
            commits_lines.append(f"  ({num}) {note}\n")
            if chat_path:
                commits_lines.append(format_chat_line_with_duration(chat_path))
            if diff_path:
                commits_lines.append(f"      | DIFF: {diff_path}\n")
        commits_block = "".join(commits_lines)

    with changespec_lock(project_file):
        with open(project_file, encoding="utf-8") as f:
            lines = f.readlines()

        # Extract existing names to compute unique suffix
        existing_names = set()
        for line in lines:
            if line.startswith("NAME: "):
                existing_names.add(line[6:].strip())

        suffix_num = get_next_suffix_number(cl_name, existing_names)
        cl_name = f"{cl_name}_{suffix_num}"

        # Determine insertion point and collect parent hooks
        parent_hooks_to_add: list[str] = []
        if parent:
            parent_end = find_changespec_end_line(lines, parent)
            if parent_end is not None:
                insert_index = parent_end + 1

                changespecs = parse_project_file(project_file)
                for cs in changespecs:
                    if cs.name == parent:
                        if cs.hooks:
                            existing_hooks = (
                                set(initial_hooks) if initial_hooks else set()
                            )
                            for hook_entry in cs.hooks:
                                if hook_entry.command not in existing_hooks:
                                    parent_hooks_to_add.append(hook_entry.command)
                        if not bug and cs.bug:
                            bug = cs.bug
                        break
            else:
                print_status(
                    f"Parent ChangeSpec '{parent}' not found. "
                    "Appending to end of file.",
                    "warning",
                )
                insert_index = len(lines)
        else:
            insert_index = len(lines)

        bug_line = f"BUG: {bug}\n" if bug else ""

        all_hooks = list(initial_hooks or []) + parent_hooks_to_add
        hooks_block = ""
        if all_hooks:
            hooks_lines = ["HOOKS:\n"]
            for hook_cmd in all_hooks:
                hooks_lines.append(f"  {hook_cmd}\n")
            hooks_block = "".join(hooks_lines)

        cl_line = f"{cl_label}: {cl_url}\n" if cl_url else ""
        changespec_block = f"""

NAME: {cl_name}
DESCRIPTION:
{formatted_description}
{parent_line}{bug_line}{cl_line}STATUS: {status}
{commits_block}{hooks_block}"""

        lines.insert(insert_index, changespec_block)

        write_changespec_atomic(
            project_file,
            "".join(lines),
            f"Add ChangeSpec {cl_name}",
        )

    return SpecWriteResponse(
        request_id=request.request_id,
        success=True,
        result={"cl_name": cl_name},
    )


def handle_create_project_file(request: SpecWriteRequest) -> SpecWriteResponse:
    """Create a new project file if it doesn't exist."""
    project = request.params["project"]

    from sase.workflow_utils import get_project_file_path

    project_file = get_project_file_path(project)
    project_dir = os.path.dirname(project_file)

    try:
        os.makedirs(project_dir, exist_ok=True)
    except Exception as e:
        return SpecWriteResponse(
            request_id=request.request_id,
            success=False,
            error=f"Failed to create project directory: {e}",
        )

    if not os.path.isfile(project_file):
        write_changespec_atomic(
            project_file,
            "",
            f"Create project file for {project}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_set_workspace_dir(request: SpecWriteRequest) -> SpecWriteResponse:
    """Set or update the WORKSPACE_DIR field."""
    workspace_dir = request.params["workspace_dir"]

    parent_dir = os.path.dirname(request.project_file)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    if not os.path.exists(request.project_file):
        with open(request.project_file, "w", encoding="utf-8") as f:
            f.write(f"WORKSPACE_DIR: {workspace_dir}\n")
        return SpecWriteResponse(request_id=request.request_id, success=True)

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines(keepends=True)
        new_line = f"WORKSPACE_DIR: {workspace_dir}\n"

        for i, line in enumerate(lines):
            if line.startswith("WORKSPACE_DIR:"):
                lines[i] = new_line
                write_changespec_atomic(
                    request.project_file,
                    "".join(lines),
                    f"Update WORKSPACE_DIR to {workspace_dir}",
                )
                return SpecWriteResponse(request_id=request.request_id, success=True)

        # Insert before first RUNNING: or NAME: line
        insert_idx = len(lines)
        for i, line in enumerate(lines):
            if line.startswith("RUNNING:") or line.startswith("NAME:"):
                insert_idx = i
                break

        lines.insert(insert_idx, new_line)
        write_changespec_atomic(
            request.project_file,
            "".join(lines),
            f"Set WORKSPACE_DIR to {workspace_dir}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_set_bare_repo_dir(request: SpecWriteRequest) -> SpecWriteResponse:
    """Set or update the BARE_REPO_DIR field."""
    bare_repo_dir = request.params["bare_repo_dir"]

    parent_dir = os.path.dirname(request.project_file)
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)

    if not os.path.exists(request.project_file):
        with open(request.project_file, "w", encoding="utf-8") as f:
            f.write(f"BARE_REPO_DIR: {bare_repo_dir}\n")
        return SpecWriteResponse(request_id=request.request_id, success=True)

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            content = f.read()

        lines = content.splitlines(keepends=True)
        new_line = f"BARE_REPO_DIR: {bare_repo_dir}\n"

        for i, line in enumerate(lines):
            if line.startswith("BARE_REPO_DIR:"):
                lines[i] = new_line
                write_changespec_atomic(
                    request.project_file,
                    "".join(lines),
                    f"Update BARE_REPO_DIR to {bare_repo_dir}",
                )
                return SpecWriteResponse(request_id=request.request_id, success=True)

        insert_idx = len(lines)
        for i, line in enumerate(lines):
            if line.startswith("RUNNING:") or line.startswith("NAME:"):
                insert_idx = i
                break

        lines.insert(insert_idx, new_line)
        write_changespec_atomic(
            request.project_file,
            "".join(lines),
            f"Set BARE_REPO_DIR to {bare_repo_dir}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_rename_changespec(request: SpecWriteRequest) -> SpecWriteResponse:
    """Rename a ChangeSpec's NAME field."""
    old_name = request.params["old_name"]
    new_name = request.params["new_name"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = []
        for line in lines:
            if line.startswith("NAME:"):
                current_name = line.split(":", 1)[1].strip()
                if current_name == old_name:
                    updated_lines.append(f"NAME: {new_name}\n")
                    continue
            updated_lines.append(line)

        write_changespec_atomic(
            request.project_file,
            "".join(updated_lines),
            f"Rename ChangeSpec {old_name} to {new_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_mark_proposal_broken(request: SpecWriteRequest) -> SpecWriteResponse:
    """Mark a proposal as broken by setting its suffix to (~!: BROKEN PROPOSAL)."""
    cl_name = request.params["cl_name"]
    entry_id = request.params["entry_id"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        in_target_changespec = False
        in_commits = False
        updated = False

        for i, line in enumerate(lines):
            if line.startswith("NAME: "):
                current_name = line[6:].strip()
                in_target_changespec = current_name == cl_name
                in_commits = False
            elif in_target_changespec:
                if line.startswith("COMMITS:"):
                    in_commits = True
                elif line.startswith(
                    (
                        "NAME:",
                        "DESCRIPTION:",
                        "PARENT:",
                        "CL:",
                        "STATUS:",
                        "TEST TARGETS:",
                        "KICKSTART:",
                        "HOOKS:",
                        "COMMENTS:",
                        "MENTORS:",
                    )
                ):
                    in_commits = False
                    if line.startswith("NAME:"):
                        in_target_changespec = False
                elif in_commits:
                    stripped = line.strip()
                    entry_match = re.match(
                        rf"^\(({re.escape(entry_id)})\)\s+(.+?)(?:\s+-\s+\([^)]+\))?$",
                        stripped,
                    )
                    if entry_match:
                        matched_id = entry_match.group(1)
                        note_text = entry_match.group(2)
                        leading_ws = line[: len(line) - len(line.lstrip())]
                        new_line = (
                            f"{leading_ws}({matched_id}) {note_text} - "
                            f"(~!: BROKEN PROPOSAL)\n"
                        )
                        lines[i] = new_line
                        updated = True
                        break

        if not updated:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Entry not found",
            )

        write_changespec_atomic(
            request.project_file,
            "".join(lines),
            f"Mark proposal {entry_id} as broken for {cl_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)
