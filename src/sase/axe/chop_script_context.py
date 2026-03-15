"""Context serialization for chop scripts.

Provides dataclasses and helpers for passing context to external chop
scripts via JSON files.  The lumberjack writes a context file before
launching a script and the script reads it to discover its environment.
"""

import json
from dataclasses import asdict, dataclass

from sase.ace.changespec import (
    ChangeSpec,
    CommentEntry,
    CommitEntry,
    HookEntry,
    HookStatusLine,
    MentorEntry,
    MentorStatusLine,
)


@dataclass
class ChopScriptContext:
    """JSON-serializable context passed to an external chop script."""

    max_hook_runners: int
    max_agent_runners: int
    zombie_timeout_seconds: int
    query: str
    lumberjack_name: str
    state_dir: str
    all_changespecs_file: str
    filtered_changespecs_file: str


def write_chop_context(ctx: ChopScriptContext, path: str) -> None:
    """Write a ChopScriptContext to a JSON file.

    Creates parent directories if they don't exist.

    Args:
        ctx: The context to serialize.
        path: Destination file path.
    """
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(asdict(ctx), f, indent=2)


def read_chop_context(path: str) -> ChopScriptContext:
    """Read a ChopScriptContext from a JSON file.

    Args:
        path: Source file path.

    Returns:
        Deserialized ChopScriptContext.
    """
    with open(path) as f:
        return ChopScriptContext(**json.load(f))


def serialize_changespecs(changespecs: list[ChangeSpec], path: str) -> None:
    """Serialize a list of ChangeSpecs to a JSON file.

    Creates parent directories if they don't exist.

    Args:
        changespecs: The changespecs to serialize.
        path: Destination file path.
    """
    from pathlib import Path

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump([asdict(cs) for cs in changespecs], f, indent=2)


def load_changespecs_from_file(path: str) -> list[ChangeSpec]:
    """Load a list of ChangeSpecs from a JSON file.

    Handles reconstruction of nested dataclasses (CommitEntry,
    HookEntry with HookStatusLine, CommentEntry, MentorEntry with
    MentorStatusLine).

    Args:
        path: Source file path.

    Returns:
        List of deserialized ChangeSpecs.
    """
    with open(path) as f:
        content = f.read()
    if not content.strip():
        return []
    raw_list = json.loads(content)
    return [_reconstruct_changespec(d) for d in raw_list]


def _reconstruct_changespec(d: dict) -> ChangeSpec:
    """Reconstruct a ChangeSpec from a plain dict."""
    commits = d.pop("commits", None)
    hooks = d.pop("hooks", None)
    comments = d.pop("comments", None)
    mentors = d.pop("mentors", None)

    return ChangeSpec(
        **d,
        commits=[_reconstruct_commit_entry(c) for c in commits]
        if commits is not None
        else None,
        hooks=[_reconstruct_hook_entry(h) for h in hooks]
        if hooks is not None
        else None,
        comments=[CommentEntry(**c) for c in comments]
        if comments is not None
        else None,
        mentors=[_reconstruct_mentor_entry(m) for m in mentors]
        if mentors is not None
        else None,
    )


def _reconstruct_commit_entry(d: dict) -> CommitEntry:
    """Reconstruct a CommitEntry from a plain dict."""
    return CommitEntry(**d)


def _reconstruct_hook_entry(d: dict) -> HookEntry:
    """Reconstruct a HookEntry, including nested HookStatusLine list."""
    status_lines = d.pop("status_lines", None)
    return HookEntry(
        **d,
        status_lines=[HookStatusLine(**sl) for sl in status_lines]
        if status_lines is not None
        else None,
    )


def _reconstruct_mentor_entry(d: dict) -> MentorEntry:
    """Reconstruct a MentorEntry, including nested MentorStatusLine list."""
    status_lines = d.pop("status_lines", None)
    return MentorEntry(
        **d,
        status_lines=[MentorStatusLine(**sl) for sl in status_lines]
        if status_lines is not None
        else None,
    )
