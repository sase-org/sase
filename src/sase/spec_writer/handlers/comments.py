"""Comment handlers for spec write operations."""

from sase.ace.changespec import (
    CommentEntry,
    changespec_lock,
    parse_project_file,
)
from sase.ace.comments.operations import write_comments_unlocked
from sase.spec_writer.models import SpecWriteRequest, SpecWriteResponse


def _dict_to_comment_entry(d: dict) -> CommentEntry:
    """Reconstruct a CommentEntry from a dict."""
    return CommentEntry(**d)


def handle_set_comments(request: SpecWriteRequest) -> SpecWriteResponse:
    """Set the COMMENTS field to the provided comments list."""
    changespec_name = request.params["changespec_name"]
    raw_comments = request.params["comments"]
    comments: list[CommentEntry] | None = (
        [_dict_to_comment_entry(c) for c in raw_comments]
        if raw_comments is not None
        else None
    )

    with changespec_lock(request.project_file):
        write_comments_unlocked(request.project_file, changespec_name, comments)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_add_comment(request: SpecWriteRequest) -> SpecWriteResponse:
    """Add or update a single comment entry by reviewer."""
    changespec_name = request.params["changespec_name"]
    comment = _dict_to_comment_entry(request.params["comment"])

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_comments: list[CommentEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_comments = list(cs.comments) if cs.comments else []
                break

        # Check if entry with same reviewer already exists
        for i, c in enumerate(current_comments):
            if c.reviewer == comment.reviewer:
                current_comments[i] = comment
                write_comments_unlocked(
                    request.project_file, changespec_name, current_comments
                )
                return SpecWriteResponse(request_id=request.request_id, success=True)

        current_comments.append(comment)
        write_comments_unlocked(request.project_file, changespec_name, current_comments)

    return SpecWriteResponse(request_id=request.request_id, success=True)


def handle_remove_comment(request: SpecWriteRequest) -> SpecWriteResponse:
    """Remove a comment entry by reviewer."""
    changespec_name = request.params["changespec_name"]
    reviewer = request.params["reviewer"]

    with changespec_lock(request.project_file):
        changespecs = parse_project_file(request.project_file)
        current_comments: list[CommentEntry] = []
        for cs in changespecs:
            if cs.name == changespec_name:
                current_comments = list(cs.comments) if cs.comments else []
                break

        if not current_comments:
            return SpecWriteResponse(request_id=request.request_id, success=True)

        comments = [c for c in current_comments if c.reviewer != reviewer]
        if not comments:
            write_comments_unlocked(request.project_file, changespec_name, None)
        else:
            write_comments_unlocked(request.project_file, changespec_name, comments)

    return SpecWriteResponse(request_id=request.request_id, success=True)
