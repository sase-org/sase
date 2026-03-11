"""Renumber handlers for spec write operations."""

import re
from typing import Any

from sase.ace.changespec import changespec_lock, get_entry_id, write_changespec_atomic
from sase.renumber_utils import (
    build_commits_section,
    find_commits_section,
    parse_commit_entries,
    sort_entries_by_id,
    sort_hook_status_lines,
)
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse


def handle_renumber_commit_entries(
    request: SpecWriteRequest,
) -> SpecWriteResponse:
    """Renumber commit entries after accepting proposals."""
    from sase.accept_workflow.renumber import (
        build_entry_id_mapping,
        reject_remaining_proposals_unlocked,
        update_comments_with_id_mapping,
        update_hooks_with_id_mapping,
        update_mentors_with_id_mapping,
    )

    cl_name = request.params["cl_name"]
    accepted_proposals = [
        (int(base), letter) for base, letter in request.params["accepted_proposals"]
    ]
    extra_msgs = request.params.get("extra_msgs")
    mark_ready_to_mail = request.params.get("mark_ready_to_mail", False)

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        # Find the ChangeSpec and its commits section
        commits_start, commits_end = find_commits_section(lines, cl_name)

        if commits_start < 0:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="No COMMITS section found",
            )

        # Parse current commit entries
        commit_lines = lines[commits_start + 1 : commits_end]
        entries = parse_commit_entries(commit_lines, include_raw_lines=True)

        # Find max regular (non-proposal) number
        max_regular = 0
        for entry in entries:
            if entry["letter"] is None:
                max_regular = max(max_regular, int(entry["number"]))  # type: ignore[arg-type]

        # Determine new numbers for accepted proposals
        next_regular = max_regular + 1
        accepted_set = set(accepted_proposals)

        # Group remaining proposals by base number
        remaining_proposals: list[dict[str, Any]] = []
        for entry in entries:
            if entry["letter"] is not None:
                key = (int(entry["number"]), str(entry["letter"]))
                if key not in accepted_set:
                    remaining_proposals.append(entry)

        # Build new entries list
        new_entries: list[dict[str, Any]] = []

        # First, add all regular (non-proposal) entries unchanged
        for entry in entries:
            if entry["letter"] is None:
                new_entries.append(entry)

        # Add accepted proposals as new regular entries in acceptance order
        for idx, (base_num, letter) in enumerate(accepted_proposals):
            for entry in entries:
                if entry["number"] == base_num and entry["letter"] == letter:
                    new_entry = entry.copy()
                    new_entry["number"] = next_regular
                    new_entry["letter"] = None
                    # Strip any proposal suffix
                    new_entry["note"] = re.sub(
                        r" - \([!~]: [^)]+\)$", "", entry["note"]
                    )
                    if extra_msgs and idx < len(extra_msgs) and extra_msgs[idx]:
                        new_entry["note"] = f"{new_entry['note']} - {extra_msgs[idx]}"
                    new_entries.append(new_entry)
                    next_regular += 1
                    break

        # Add remaining proposals unchanged
        for entry in remaining_proposals:
            new_entries.append(entry.copy())

        # Build ID mappings
        promote_mapping, archive_mapping = build_entry_id_mapping(
            entries,
            new_entries,
            accepted_proposals,
            next_regular,
            remaining_proposals,
        )

        # Sort entries
        new_entries = sort_entries_by_id(new_entries)

        # Rebuild commits section
        new_commit_lines = build_commits_section(new_entries)

        # Replace old commits section with new one
        new_lines = lines[:commits_start] + new_commit_lines + lines[commits_end:]

        # Update hooks, mentors, comments with ID mapping
        new_lines = update_hooks_with_id_mapping(
            new_lines, cl_name, promote_mapping, archive_mapping
        )
        new_lines = update_mentors_with_id_mapping(new_lines, cl_name, promote_mapping)
        new_lines = update_comments_with_id_mapping(new_lines, cl_name, promote_mapping)

        # Sort hook status lines
        new_lines = sort_hook_status_lines(new_lines, cl_name)

        # If mark_ready_to_mail is True, also reject remaining proposals
        if mark_ready_to_mail:
            new_lines = reject_remaining_proposals_unlocked(new_lines, cl_name)

        # Write atomically
        commit_msg = f"Renumber commit entries for {cl_name}"
        if mark_ready_to_mail:
            commit_msg += " and mark ready to mail"
        write_changespec_atomic(
            request.project_file,
            "".join(new_lines),
            commit_msg,
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_rewind_commit_entries(
    request: SpecWriteRequest,
) -> SpecWriteResponse:
    """Update ChangeSpec after rewinding to a previous entry."""
    from sase.rewind_workflow.renumber import (
        get_lowest_available_letter,
        update_comments_with_id_mapping,
        update_hooks_with_id_mapping,
        update_mentors_with_id_mapping,
    )

    cl_name = request.params["cl_name"]
    selected_entry_num = request.params["selected_entry_num"]

    with changespec_lock(request.project_file):
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        # Find the ChangeSpec and its commits section
        commits_start, commits_end = find_commits_section(lines, cl_name)

        if commits_start < 0:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="No COMMITS section found",
            )

        # Parse current commit entries
        commit_lines = lines[commits_start + 1 : commits_end]
        entries = parse_commit_entries(commit_lines)

        # Calculate base number for new proposals
        base_num = selected_entry_num

        # Separate entries into categories
        numeric_entries = [e for e in entries if e["letter"] is None]
        proposal_entries = [e for e in entries if e["letter"] is not None]

        entries_to_keep = [
            e for e in numeric_entries if e["number"] < selected_entry_num
        ]
        entry_after = next(
            (e for e in numeric_entries if e["number"] == selected_entry_num + 1),
            None,
        )
        selected_entry = next(
            (e for e in numeric_entries if e["number"] == selected_entry_num),
            None,
        )
        entries_to_delete = [
            e for e in numeric_entries if e["number"] > selected_entry_num + 1
        ]
        existing_proposals = [
            e for e in proposal_entries if e["number"] == selected_entry_num
        ]

        if not entry_after or not selected_entry:
            return SpecWriteResponse(
                request_id=request.request_id,
                success=False,
                error="Selected entry or next entry not found",
            )

        # Build ID mapping
        id_mapping: dict[str, str | None] = {}

        for e in entries_to_keep:
            old_id = get_entry_id(e)
            id_mapping[old_id] = old_id

        for e in entries_to_delete:
            old_id = get_entry_id(e)
            id_mapping[old_id] = None

        old_id = get_entry_id(selected_entry)
        id_mapping[old_id] = old_id

        used_letters: set[str] = set()
        for e in existing_proposals:
            if e["letter"]:
                used_letters.add(e["letter"])

        entry_after_new_letter = get_lowest_available_letter(base_num, used_letters)
        old_id = get_entry_id(entry_after)
        new_id = f"{base_num}{entry_after_new_letter}"
        id_mapping[old_id] = new_id

        for e in existing_proposals:
            old_id = get_entry_id(e)
            id_mapping[old_id] = old_id

        # Build new entries list
        new_entries: list[dict[str, Any]] = []

        for e in entries_to_keep:
            new_entries.append(e.copy())

        # Selected entry with NEW PROPOSAL suffix
        new_entry = selected_entry.copy()
        new_entry["note"] = re.sub(r" - \([!~@$%?]: [^)]+\)$", "", new_entry["note"])
        new_entry["note"] = f"{new_entry['note']} - (!: NEW PROPOSAL)"
        new_entries.append(new_entry)

        # Entry after -> proposal
        new_entry = entry_after.copy()
        new_entry["number"] = base_num
        new_entry["letter"] = entry_after_new_letter
        new_entry["note"] = re.sub(r" - \([!~@$%?]: [^)]+\)$", "", new_entry["note"])
        new_entry["note"] = f"{new_entry['note']} - (!: NEW PROPOSAL)"
        new_entries.append(new_entry)

        for e in sorted(existing_proposals, key=lambda x: x["letter"] or ""):
            new_entries.append(e.copy())

        # Sort entries
        new_entries = sort_entries_by_id(new_entries)

        # Rebuild commits section
        new_commit_lines = build_commits_section(new_entries)

        # Replace old commits section
        new_lines = lines[:commits_start] + new_commit_lines + lines[commits_end:]

        # Update hooks, mentors, comments
        new_lines = update_hooks_with_id_mapping(new_lines, cl_name, id_mapping)
        new_lines = update_mentors_with_id_mapping(
            new_lines, cl_name, id_mapping, selected_entry_num
        )
        new_lines = update_comments_with_id_mapping(new_lines, cl_name, id_mapping)

        # Sort hook status lines
        new_lines = sort_hook_status_lines(new_lines, cl_name)

        # Write atomically
        commit_msg = f"Rewind {cl_name} to entry ({selected_entry_num})"
        write_changespec_atomic(
            request.project_file,
            "".join(new_lines),
            commit_msg,
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)
