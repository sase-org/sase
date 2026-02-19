"""Resolve an Agent to its Claude Code JSONL session transcript."""

import re
from pathlib import Path

from sase.ace.tui.models.agent import Agent


def resolve_agent_session(agent: Agent) -> Path | None:
    """Resolve an Agent to the most recent JSONL transcript path.

    Resolution chain: Agent → project_name → workspace CWD →
    hash CWD → ~/.claude/projects/{hash}/ → most recent .jsonl
    """
    cwd = _get_workspace_cwd(agent)
    if cwd is None:
        return None
    claude_dir = _cwd_to_claude_project_dir(cwd)
    if not claude_dir.is_dir():
        return None
    return _find_most_recent_jsonl(claude_dir)


def _get_workspace_cwd(agent: Agent) -> str | None:
    """Extract the workspace working directory for an agent.

    Uses lazy import of get_workspace_directory to match the existing
    pattern in running_field.py.
    """
    from sase.running_field import get_workspace_directory

    project_name = Path(agent.project_file).parent.name
    workspace_num = agent.workspace_num if agent.workspace_num is not None else 1

    try:
        cwd = get_workspace_directory(project_name, workspace_num)
    except RuntimeError:
        return None

    # ensure_git_clone returns paths with trailing "/" for workspace > 1
    return cwd.rstrip("/")


def _cwd_to_claude_project_dir(cwd: str) -> Path:
    """Convert a working directory path to the Claude projects hash directory.

    Claude Code hashes the CWD by replacing non-alphanumeric chars with '-'.
    """
    hashed = re.sub(r"[^a-zA-Z0-9]", "-", cwd)
    return Path.home() / ".claude" / "projects" / hashed


def _find_most_recent_jsonl(directory: Path) -> Path | None:
    """Find the most recently modified .jsonl file in a directory."""
    jsonl_files = list(directory.glob("*.jsonl"))
    if not jsonl_files:
        return None
    return max(jsonl_files, key=lambda p: p.stat().st_mtime)
