"""Commit handlers for spec write operations."""

import re

from sase.ace.changespec import changespec_lock, write_changespec_atomic
from sase.commit_utils.entries import (
    get_next_proposal_letter,
    format_chat_line_with_duration,
    get_next_commit_number,
)
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse


def handle_add_commit_entry(request: SpecWriteRequest) -> SpecWriteResponse:
    """Add a new COMMITS entry to a ChangeSpec."""
    cl_name = request.params["cl_name"]
    note = request.params["note"]
    diff_path = request.params.get("diff_path")
    chat_path = request.params.get("chat_path")
    end_timestamp = request.params.get("end_timestamp")

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        in_target_changespec = False
        commits_field_line = -1
        last_commit_entry_line = -1
        changespec_end_line = -1

        in_commits_section = False
        for i, line in enumerate(lines):
            if line.startswith("NAME: "):
                current_name = line[6:].strip()
                if in_target_changespec:
                    changespec_end_line = i
                    break
                in_target_changespec = current_name == cl_name
            elif in_target_changespec:
                if line.startswith("COMMITS:"):
                    commits_field_line = i
                    in_commits_section = True
                elif in_commits_section:
                    stripped = line.strip()
                    if re.match(r"^\(\d+[a-z]?\)", stripped) or stripped.startswith(
                        "| "
                    ):
                        last_commit_entry_line = i
                    elif stripped and not stripped.startswith("#"):
                        in_commits_section = False
                        if changespec_end_line < 0:
                            changespec_end_line = i

        if in_target_changespec and changespec_end_line < 0:
            changespec_end_line = len(lines)

        if not in_target_changespec and changespec_end_line < 0:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="ChangeSpec not found",
            )

        next_num = get_next_commit_number(lines, cl_name)

        entry_lines = [f"  ({next_num}) {note}\n"]
        if chat_path:
            entry_lines.append(format_chat_line_with_duration(chat_path, end_timestamp))
        if diff_path:
            entry_lines.append(f"      | DIFF: {diff_path}\n")

        if commits_field_line >= 0:
            if last_commit_entry_line >= 0:
                insert_idx = last_commit_entry_line + 1
            else:
                insert_idx = commits_field_line + 1
        else:
            insert_idx = changespec_end_line
            in_target_changespec = False
            for i, line in enumerate(lines):
                if in_target_changespec and line.startswith("STATUS:"):
                    insert_idx = i
                    break
                if line.startswith("NAME: "):
                    current_name = line[6:].strip()
                    in_target_changespec = current_name == cl_name

            entry_lines.insert(0, "COMMITS:\n")

        for j, entry_line in enumerate(entry_lines):
            lines.insert(insert_idx + j, entry_line)

        write_changespec_atomic(
            request.project_file,
            "".join(lines),
            f"Add commit entry {next_num} for {cl_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_add_proposed_commit_entry(request: SpecWriteRequest) -> SpecWriteResponse:
    """Add a proposed COMMITS entry to a ChangeSpec."""
    cl_name = request.params["cl_name"]
    note = request.params["note"]
    diff_path = request.params.get("diff_path")
    chat_path = request.params.get("chat_path")
    end_timestamp = request.params.get("end_timestamp")

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        base_number = get_next_commit_number(lines, cl_name) - 1
        if base_number == 0:
            base_number = 0
        proposal_letter = get_next_proposal_letter(lines, cl_name, base_number)
        entry_id = f"{base_number}{proposal_letter}"

        in_target_changespec = False
        commits_field_line = -1
        last_commit_entry_line = -1
        changespec_end_line = -1

        in_commits_section = False
        for i, line in enumerate(lines):
            if line.startswith("NAME: "):
                current_name = line[6:].strip()
                if in_target_changespec:
                    changespec_end_line = i
                    break
                in_target_changespec = current_name == cl_name
            elif in_target_changespec:
                if line.startswith("COMMITS:"):
                    commits_field_line = i
                    in_commits_section = True
                elif in_commits_section:
                    stripped = line.strip()
                    if re.match(r"^\(\d+[a-z]?\)", stripped) or stripped.startswith(
                        "| "
                    ):
                        last_commit_entry_line = i
                    elif stripped and not stripped.startswith("#"):
                        in_commits_section = False
                        if changespec_end_line < 0:
                            changespec_end_line = i

        if in_target_changespec and changespec_end_line < 0:
            changespec_end_line = len(lines)

        if not in_target_changespec and changespec_end_line < 0:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="ChangeSpec not found",
            )

        entry_lines = [f"  ({entry_id}) {note} - (!: NEW PROPOSAL)\n"]
        if chat_path:
            entry_lines.append(format_chat_line_with_duration(chat_path, end_timestamp))
        if diff_path:
            entry_lines.append(f"      | DIFF: {diff_path}\n")

        if commits_field_line >= 0:
            if last_commit_entry_line >= 0:
                insert_idx = last_commit_entry_line + 1
            else:
                insert_idx = commits_field_line + 1
        else:
            insert_idx = changespec_end_line
            in_target_changespec = False
            for i, line in enumerate(lines):
                if in_target_changespec and line.startswith("STATUS:"):
                    insert_idx = i
                    break
                if line.startswith("NAME: "):
                    current_name = line[6:].strip()
                    in_target_changespec = current_name == cl_name

            entry_lines.insert(0, "COMMITS:\n")

        for j, entry_line in enumerate(entry_lines):
            lines.insert(insert_idx + j, entry_line)

        write_changespec_atomic(
            request.project_file,
            "".join(lines),
            f"Add proposed commit entry {entry_id} for {cl_name}",
        )

    return SpecWriteResponse(
        request_id=request.request_id,
        success=True,
        result={"entry_id": entry_id},
    )


def handle_reject_proposals_and_set_status(
    request: SpecWriteRequest,
) -> SpecWriteResponse:
    """Reject all new proposals and optionally set STATUS."""
    cl_name = request.params["cl_name"]
    final_status = request.params["final_status"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        in_target_changespec = False
        in_commits = False
        rejected_count = 0
        status_line_idx: int | None = None
        current_status: str | None = None

        for i, line in enumerate(lines):
            if line.startswith("NAME: "):
                current_name = line[6:].strip()
                in_target_changespec = current_name == cl_name
                in_commits = False
            elif in_target_changespec:
                if line.startswith("STATUS:"):
                    status_line_idx = i
                    current_status = line[7:].strip()
                    in_commits = False
                elif line.startswith("COMMITS:"):
                    in_commits = True
                elif line.startswith(
                    (
                        "NAME:",
                        "DESCRIPTION:",
                        "PARENT:",
                        "CL:",
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
                        r"^\((\d+[a-z])\)\s+(.+?)\s+-\s+\(!:\s*NEW PROPOSAL\)$",
                        stripped,
                    )
                    if entry_match:
                        matched_id = entry_match.group(1)
                        note_text = entry_match.group(2)
                        leading_ws = line[: len(line) - len(line.lstrip())]
                        new_line = (
                            f"{leading_ws}({matched_id}) {note_text} - "
                            f"(~!: NEW PROPOSAL)\n"
                        )
                        lines[i] = new_line
                        rejected_count += 1

        if status_line_idx is None or current_status is None:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="STATUS line not found",
            )

        if final_status:
            new_status = final_status
            lines[status_line_idx] = f"STATUS: {new_status}\n"
        else:
            new_status = current_status

        write_changespec_atomic(
            request.project_file,
            "".join(lines),
            f"Reject {rejected_count} proposal(s) and set status to "
            f"'{new_status}' for {cl_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_reject_all_new_proposals(request: SpecWriteRequest) -> SpecWriteResponse:
    """Reject all new proposals by changing (!: NEW PROPOSAL) to (~!: NEW PROPOSAL)."""
    cl_name = request.params["cl_name"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        in_target_changespec = False
        in_commits = False
        rejected_count = 0

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
                    )
                ):
                    in_commits = False
                    if line.startswith("NAME:"):
                        in_target_changespec = False
                elif in_commits:
                    stripped = line.strip()
                    entry_match = re.match(
                        r"^\((\d+[a-z])\)\s+(.+?)\s+-\s+\(!:\s*NEW PROPOSAL\)$",
                        stripped,
                    )
                    if entry_match:
                        matched_id = entry_match.group(1)
                        note_text = entry_match.group(2)
                        leading_ws = line[: len(line) - len(line.lstrip())]
                        new_line = (
                            f"{leading_ws}({matched_id}) {note_text} - "
                            f"(~!: NEW PROPOSAL)\n"
                        )
                        lines[i] = new_line
                        rejected_count += 1

        if rejected_count == 0:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=True,
                result={"rejected_count": 0},
            )

        write_changespec_atomic(
            request.project_file,
            "".join(lines),
            f"Reject {rejected_count} new proposal(s) for {cl_name}",
        )

    return SpecWriteResponse(
        request_id=request.request_id,
        success=True,
        result={"rejected_count": rejected_count},
    )


def handle_update_commit_entry_suffix(
    request: SpecWriteRequest,
) -> SpecWriteResponse:
    """Update or remove the suffix of a COMMITS entry."""
    cl_name = request.params["cl_name"]
    entry_id = request.params["entry_id"]
    new_suffix_type = request.params["new_suffix_type"]

    if new_suffix_type not in ("remove", "reject"):
        return SpecWriteResponse(
            request_id=request.request_id,
            success=False,
            error=f"Invalid suffix type: {new_suffix_type}",
        )

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
                    )
                ):
                    in_commits = False
                    if line.startswith("NAME:"):
                        in_target_changespec = False
                elif in_commits:
                    stripped = line.strip()
                    entry_match = re.match(
                        rf"^\(({re.escape(entry_id)})\)\s+(.+?)\s+-\s+\((!:|~:)\s*([^)]+)\)$",
                        stripped,
                    )
                    if entry_match:
                        matched_id = entry_match.group(1)
                        note_text = entry_match.group(2)
                        suffix_prefix = entry_match.group(3)
                        suffix_msg = entry_match.group(4)
                        leading_ws = line[: len(line) - len(line.lstrip())]
                        if new_suffix_type == "remove":
                            new_line = f"{leading_ws}({matched_id}) {note_text}\n"
                        else:  # reject
                            if suffix_prefix == "!:":
                                new_line = (
                                    f"{leading_ws}({matched_id}) {note_text} - "
                                    f"(~!: {suffix_msg})\n"
                                )
                            else:
                                continue
                        lines[i] = new_line
                        updated = True
                        break

        if not updated:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Entry not found or no suffix to update",
            )

        action = "Remove" if new_suffix_type == "remove" else "Reject"
        write_changespec_atomic(
            request.project_file,
            "".join(lines),
            f"{action} suffix from commit entry {entry_id} for {cl_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)
