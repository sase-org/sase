"""Mentor handlers for spec write operations."""

from sase.ace.changespec import (
    MentorEntry,
    MentorStatusLine,
    changespec_lock,
    parse_project_file,
    write_changespec_atomic,
)
from sase.ace.mentors import (
    apply_mentors_update,
    merge_mentor_status_lines,
)
from sase.sase_utils import generate_timestamp as gen_timestamp
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse
from sase.status_state_machine import remove_workspace_suffix


def _dict_to_mentor_status_line(d: dict) -> MentorStatusLine:
    """Reconstruct a MentorStatusLine from a dict."""
    return MentorStatusLine(**d)


def _dict_to_mentor_entry(d: dict) -> MentorEntry:
    """Reconstruct a MentorEntry from a dict."""
    d = dict(d)
    if d.get("status_lines") is not None:
        d["status_lines"] = [
            _dict_to_mentor_status_line(sl) for sl in d["status_lines"]
        ]
    return MentorEntry(**d)


def handle_set_mentors(request: SpecWriteRequest) -> SpecWriteResponse:
    """Set the MENTORS field, merging status_lines from disk."""
    changespec_name = request.params["changespec_name"]
    mentors = [_dict_to_mentor_entry(m) for m in request.params["mentors"]]

    with changespec_lock(request.project_file):
        # Re-read current state inside the lock
        current_changespecs = parse_project_file(request.project_file)
        current_mentors: list[MentorEntry] = []
        for cs in current_changespecs:
            if cs.name == changespec_name:
                current_mentors = list(cs.mentors) if cs.mentors else []
                break

        # Merge status_lines from disk that caller doesn't have
        merged = merge_mentor_status_lines(current_mentors, mentors)

        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = apply_mentors_update(lines, changespec_name, merged)
        content = "".join(updated_lines)

        write_changespec_atomic(
            request.project_file,
            content,
            f"Update MENTORS field for {changespec_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_add_mentor_entry(request: SpecWriteRequest) -> SpecWriteResponse:
    """Add a new MENTORS entry for a ChangeSpec."""
    changespec_name = request.params["changespec_name"]
    entry_id = request.params["entry_id"]
    profile_names = request.params["profile_names"]

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_mentors: list[MentorEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_mentors = list(cs.mentors) if cs.mentors else []
                break

        # Check if entry already exists
        existing_entry: MentorEntry | None = None
        for entry in current_mentors:
            if entry.entry_id == entry_id:
                existing_entry = entry
                break

        if existing_entry:
            # Merge profiles
            for pname in profile_names:
                if pname not in existing_entry.profiles:
                    existing_entry.profiles.append(pname)
        else:
            # Create new entry
            new_entry = MentorEntry(
                entry_id=entry_id,
                profiles=profile_names,
                status_lines=[],
            )
            current_mentors.append(new_entry)

        # Write updated mentors
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = apply_mentors_update(lines, changespec_name, current_mentors)
        content = "".join(updated_lines)

        write_changespec_atomic(
            request.project_file,
            content,
            f"Add MENTORS entry ({entry_id}) for {changespec_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_set_mentor_status(request: SpecWriteRequest) -> SpecWriteResponse:
    """Set or update the status for a specific mentor in a profile."""
    changespec_name = request.params["changespec_name"]
    entry_id = request.params["entry_id"]
    profile_name = request.params["profile_name"]
    mentor_name = request.params["mentor_name"]
    status = request.params["status"]
    timestamp = request.params.get("timestamp")
    suffix = request.params.get("suffix")
    suffix_type = request.params.get("suffix_type")
    duration = request.params.get("duration")

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_mentors: list[MentorEntry] = []
        changespec_status: str | None = None
        for cs in changespecs:
            if cs.name == changespec_name:
                current_mentors = list(cs.mentors) if cs.mentors else []
                changespec_status = cs.status
                break

        # Determine if changespec is in Draft status
        is_draft_status = (
            changespec_status is not None
            and remove_workspace_suffix(changespec_status) == "Draft"
        )

        # Find the entry
        target_entry: MentorEntry | None = None
        for entry in current_mentors:
            if entry.entry_id == entry_id:
                target_entry = entry
                break

        if target_entry is None:
            # Entry doesn't exist - create it
            target_entry = MentorEntry(
                entry_id=entry_id,
                profiles=[profile_name],
                status_lines=[],
                is_draft=is_draft_status,
            )
            current_mentors.append(target_entry)

        # Find or create the status line
        if target_entry.status_lines is None:
            target_entry.status_lines = []

        existing_status_line: MentorStatusLine | None = None
        for sl in target_entry.status_lines:
            if sl.profile_name == profile_name and sl.mentor_name == mentor_name:
                existing_status_line = sl
                break

        if existing_status_line:
            # Don't overwrite killed_agent status
            if existing_status_line.suffix_type == "killed_agent":
                return SpecWriteResponse(request_id=request.request_id, success=True)

            # Update existing status line
            existing_status_line.status = status
            if timestamp is not None:
                existing_status_line.timestamp = timestamp
            existing_status_line.suffix = suffix
            existing_status_line.suffix_type = suffix_type
            existing_status_line.duration = duration
        else:
            # Create new status line
            new_status_line = MentorStatusLine(
                profile_name=profile_name,
                mentor_name=mentor_name,
                status=status,
                timestamp=timestamp if timestamp else gen_timestamp(),
                duration=duration,
                suffix=suffix,
                suffix_type=suffix_type,
            )
            target_entry.status_lines.append(new_status_line)

        # Write updated mentors
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = apply_mentors_update(lines, changespec_name, current_mentors)
        content = "".join(updated_lines)

        write_changespec_atomic(
            request.project_file,
            content,
            f"Set mentor status {profile_name}:{mentor_name} -> {status}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_clear_mentor_status_lines(
    request: SpecWriteRequest,
) -> SpecWriteResponse:
    """Remove status lines for specific mentors (to allow rerun)."""
    changespec_name = request.params["changespec_name"]
    # Convert from JSON-serializable format back to dict[str, set[tuple]]
    raw_mentors_to_clear = request.params["mentors_to_clear"]
    mentors_to_clear: dict[str, set[tuple[str, str]]] = {}
    for entry_id, tuples in raw_mentors_to_clear.items():
        mentors_to_clear[entry_id] = {(t[0], t[1]) for t in tuples}

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_mentors: list[MentorEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_mentors = list(cs.mentors) if cs.mentors else []
                break

        if not current_mentors:
            return SpecWriteResponse(request_id=request.request_id, success=True)

        # Remove specified status lines
        for entry in current_mentors:
            if entry.entry_id not in mentors_to_clear:
                continue
            if not entry.status_lines:
                continue

            mentors_to_remove = mentors_to_clear[entry.entry_id]
            entry.status_lines = [
                sl
                for sl in entry.status_lines
                if (sl.mentor_name, sl.profile_name) not in mentors_to_remove
            ]

        # Write updated mentors
        with open(request.project_file, encoding="utf-8") as f:
            lines = f.readlines()

        updated_lines = apply_mentors_update(lines, changespec_name, current_mentors)
        content = "".join(updated_lines)

        write_changespec_atomic(
            request.project_file,
            content,
            f"Clear mentor status lines for {changespec_name}",
        )

    return SpecWriteResponse(request_id=request.request_id, success=True)
