"""Data models and builder for the Mentor Review modal."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from sase.ace.mentor_output import (
    MentorAcceptanceState,
    MentorOutput,
    MentorReadState,
    load_acceptance_state,
    load_file_snapshots,
    load_mentor_outputs_for_commit,
    load_read_state,
)

if TYPE_CHECKING:
    from sase.ace.changespec.models import MentorEntry
    from sase.vcs_provider._base import VCSProvider

_EXTENSION_TO_LEXER: dict[str, str] = {
    ".bash": "bash",
    ".c": "c",
    ".cpp": "cpp",
    ".css": "css",
    ".dart": "dart",
    ".diff": "diff",
    ".go": "go",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".kt": "kotlin",
    ".md": "markdown",
    ".patch": "diff",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".sh": "bash",
    ".sql": "sql",
    ".swift": "swift",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".xml": "xml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


def lexer_for_path(file_path: str) -> str:
    """Return the syntax lexer name for a file path based on its extension."""
    _, ext = os.path.splitext(file_path)
    return _EXTENSION_TO_LEXER.get(ext.lower(), "text")


@dataclass
class MentorInfo:
    """Aggregated info for a single mentor in the side panel."""

    mentor_name: str
    profile_name: str
    status: str  # COMMENTED, PASSED, FAILED, RUNNING, KILLED, DEAD
    comments: list[dict[str, str | int]]  # list of comment dicts
    is_running: bool = False


@dataclass
class MentorReviewData:
    """Data passed to the MentorReviewModal."""

    mentors: list[MentorInfo]
    acceptance: MentorAcceptanceState
    read_state: MentorReadState
    cl_name: str
    entry_id: str
    vcs_provider: VCSProvider | None = None
    revision: str = ""
    vcs_cwd: str = ""
    file_snapshots: dict[str, str] = field(default_factory=dict)
    total_comments: int = field(init=False, default=0)

    def __post_init__(self) -> None:
        self.total_comments = sum(len(m.comments) for m in self.mentors)


@dataclass
class MentorApplyResult:
    """Result returned when user applies accepted comments.

    ``mode`` is ``"commit"`` (A key) or ``"propose"`` (a key).
    """

    accepted_comments: list[dict[str, str | int]]
    cl_name: str
    mode: str = "commit"


@dataclass
class MentorKillResult:
    """Result returned when user presses K to kill a running mentor."""

    entry_id: str
    mentor_name: str
    profile_name: str
    cl_name: str


@dataclass
class MentorRunResult:
    """Result returned when user selects a profile to run via ``r``."""

    profile_name: str
    cl_name: str
    entry_id: str


def build_mentor_review_data(
    mentor_entry: MentorEntry,
    cl_name: str,
    *,
    vcs_provider: VCSProvider | None = None,
    revision: str = "",
    vcs_cwd: str = "",
) -> MentorReviewData | None:
    """Build MentorReviewData from a MentorEntry.

    Returns None if there are no mentors with comments or actionable status.
    """
    entry_id = mentor_entry.entry_id

    # Load mentor outputs from disk, matching by status line timestamps
    timestamps = (
        {sl.timestamp for sl in mentor_entry.status_lines}
        if mentor_entry.status_lines
        else set()
    )
    outputs = load_mentor_outputs_for_commit(cl_name, timestamps)
    # Map timestamp → MentorOutput (filenames use config-level names, but the
    # JSON content may have LLM-provided names that don't match status lines).
    ts_output_map: dict[str, MentorOutput] = {}
    for path, mo in outputs:
        for ts in timestamps:
            if path.stem.endswith(f"-{ts}"):
                ts_output_map[ts] = mo
                break

    # Build mentor info list from status lines
    mentors: list[MentorInfo] = []
    seen: set[tuple[str, str]] = set()

    if mentor_entry.status_lines:
        for sl in mentor_entry.status_lines:
            key = (sl.profile_name, sl.mentor_name)
            if key in seen:
                continue
            seen.add(key)

            comments: list[dict[str, str | int]] = []
            output: MentorOutput | None = ts_output_map.get(sl.timestamp)
            if output is not None:
                for c in output.comments:
                    comments.append(
                        {
                            "focus_name": c.focus_name,
                            "file_path": c.file_path,
                            "line_number": c.line_number,
                            "description": c.description,
                            "severity": c.severity,
                        }
                    )

            mentors.append(
                MentorInfo(
                    mentor_name=sl.mentor_name,
                    profile_name=sl.profile_name,
                    status=sl.status,
                    comments=comments,
                    is_running=sl.suffix_type == "running_agent",
                )
            )

    if not mentors:
        return None

    # Load and merge file snapshots from all mentor outputs
    all_snapshots: dict[str, str] = {}
    if mentor_entry.status_lines:
        for sl in mentor_entry.status_lines:
            snapshots = load_file_snapshots(
                cl_name, sl.profile_name, sl.mentor_name, sl.timestamp
            )
            all_snapshots.update(snapshots)

    acceptance = load_acceptance_state(cl_name, entry_id)
    read_state = load_read_state(cl_name, entry_id)
    return MentorReviewData(
        mentors=mentors,
        acceptance=acceptance,
        read_state=read_state,
        cl_name=cl_name,
        entry_id=entry_id,
        vcs_provider=vcs_provider,
        revision=revision,
        vcs_cwd=vcs_cwd,
        file_snapshots=all_snapshots,
    )
