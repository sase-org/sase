"""Rust-backed helpers for deterministic agent-cleanup side effects.

The TUI still owns event-loop scheduling, user notifications, process
signalling, and project-file locks. These wrappers move the repeatable
file/text/list mutations behind the Rust cleanup boundary while preserving
Python fallbacks for stale editable installs.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sase.core.rust import require_rust_binding
from sase.core.wire import to_json_dict
from sase.core.wire_conversion import (
    comment_entry_to_wire,
    hook_entry_to_wire,
    mentor_entry_to_wire,
)


def try_save_dismissed_agents_index(
    path: Path,
    identities: list[dict[str, Any]],
) -> bool:
    try:
        binding = require_rust_binding("save_dismissed_agents_index")
    except (ImportError, AttributeError):
        return False
    binding(str(path), identities)
    return True


def try_save_dismissed_bundle(root: Path, bundle: dict[str, Any]) -> bool:
    try:
        binding = require_rust_binding("save_dismissed_bundle")
    except (ImportError, AttributeError):
        return False
    binding(str(root), bundle)
    return True


def try_delete_agent_artifacts(artifacts_dir: str | None) -> bool:
    if not artifacts_dir:
        return True
    try:
        binding = require_rust_binding("delete_agent_artifacts")
    except (ImportError, AttributeError):
        return False
    binding(str(artifacts_dir))
    return True


def try_release_workspace_from_content(
    content: str,
    workspace_num: int,
    workflow: str | None,
    cl_name: str | None,
) -> dict[str, Any] | None:
    try:
        binding = require_rust_binding("release_workspace_from_content")
    except (ImportError, AttributeError):
        return None
    return dict(binding(content, workspace_num, workflow, cl_name))


def mark_hook_agents_as_killed_rust(
    hooks: list[Any],
    suffixes: list[str],
) -> list[Any] | None:
    try:
        binding = require_rust_binding("mark_hook_agents_as_killed")
    except (ImportError, AttributeError):
        return None
    from sase.ace.changespec.models import HookEntry, HookStatusLine

    payload = to_json_dict([hook_entry_to_wire(hook) for hook in hooks])
    updated = binding(payload, suffixes)
    return [
        HookEntry(
            command=str(hook["command"]),
            status_lines=[
                HookStatusLine(
                    commit_entry_num=str(line["commit_entry_num"]),
                    timestamp=str(line["timestamp"]),
                    status=str(line["status"]),
                    duration=line.get("duration"),
                    suffix=line.get("suffix"),
                    suffix_type=line.get("suffix_type"),
                    summary=line.get("summary"),
                )
                for line in hook.get("status_lines") or []
            ],
        )
        for hook in updated
    ]


def mark_mentor_agents_as_killed_rust(
    mentors: list[Any],
    suffixes: list[str],
) -> list[Any] | None:
    try:
        binding = require_rust_binding("mark_mentor_agents_as_killed")
    except (ImportError, AttributeError):
        return None
    from sase.ace.changespec.models import MentorEntry, MentorStatusLine

    payload = to_json_dict([mentor_entry_to_wire(entry) for entry in mentors])
    updated = binding(payload, suffixes)
    return [
        MentorEntry(
            entry_id=str(entry["entry_id"]),
            profiles=list(entry.get("profiles") or []),
            status_lines=[
                MentorStatusLine(
                    profile_name=str(line["profile_name"]),
                    mentor_name=str(line["mentor_name"]),
                    status=str(line["status"]),
                    timestamp=line.get("timestamp"),
                    duration=line.get("duration"),
                    suffix=line.get("suffix"),
                    suffix_type=line.get("suffix_type"),
                )
                for line in entry.get("status_lines") or []
            ],
            is_draft=bool(entry.get("is_draft", False)),
        )
        for entry in updated
    ]


def mark_comment_agents_as_killed_rust(
    comments: list[Any],
    suffixes: list[str],
) -> list[Any] | None:
    try:
        binding = require_rust_binding("mark_comment_agents_as_killed")
    except (ImportError, AttributeError):
        return None
    from sase.ace.changespec.models import CommentEntry

    payload = to_json_dict([comment_entry_to_wire(comment) for comment in comments])
    updated = binding(payload, suffixes)
    return [
        CommentEntry(
            reviewer=str(comment["reviewer"]),
            file_path=str(comment["file_path"]),
            suffix=comment.get("suffix"),
            suffix_type=comment.get("suffix_type"),
        )
        for comment in updated
    ]
