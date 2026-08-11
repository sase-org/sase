"""Patch data models and constants.

The exports in this package preserve the historical
``sase.ace.patch.models`` import surface while keeping each model domain in a
focused module.
"""

from .entries import CommentEntry, DeltaEntry, DeltaLineStats, TimestampEntry
from .hooks import HookEntry, HookStatusLine
from .mentors import MentorEntry, MentorStatusLine
from .patch import (  # legacy compatibility alias
    PR_ORIGIN_EXTERNAL,
    PR_ORIGIN_SASE,
    PR_ORIGIN_UNKNOWN,
    PR_ORIGIN_VALUES,
    ChangeSpec,  # legacy compatibility alias
    Patch,
    normalize_pr_origin,
)
from .stitches import (
    CommitEntry,
    Stitch,
    StitchDict,
    parse_commit_entry_id,
    parse_stitch_id,
)
from .suffixes import (
    ERROR_SUFFIX_MESSAGES,
    extract_pid_from_agent_suffix,
    get_base_status,
    is_error_suffix,
    is_plain_suffix,
    is_running_agent_suffix,
    is_running_process_suffix,
)

__all__ = [
    "ERROR_SUFFIX_MESSAGES",
    "ChangeSpec",  # legacy compatibility alias
    "CommentEntry",
    "CommitEntry",
    "DeltaEntry",
    "DeltaLineStats",
    "HookEntry",
    "HookStatusLine",
    "MentorEntry",
    "MentorStatusLine",
    "PR_ORIGIN_EXTERNAL",
    "PR_ORIGIN_SASE",
    "PR_ORIGIN_UNKNOWN",
    "PR_ORIGIN_VALUES",
    "Patch",
    "Stitch",
    "StitchDict",
    "TimestampEntry",
    "extract_pid_from_agent_suffix",
    "get_base_status",
    "is_error_suffix",
    "is_plain_suffix",
    "is_running_agent_suffix",
    "is_running_process_suffix",
    "normalize_pr_origin",
    "parse_commit_entry_id",
    "parse_stitch_id",
]
