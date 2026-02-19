"""Resolve an Agent to its Claude Code JSONL session transcript."""

import re
from datetime import datetime
from pathlib import Path

from sase.ace.tui.models.agent import Agent


def resolve_agent_session(agent: Agent) -> Path | None:
    """Resolve an Agent to the most recent JSONL transcript path.

    Resolution chain: Agent → project_name → workspace CWD →
    hash CWD → ~/.claude/projects/{hash}/ → most recent .jsonl
    """
    paths = resolve_agent_sessions(agent)
    return paths[-1] if paths else None


def resolve_agent_sessions(agent: Agent, since: datetime | None = None) -> list[Path]:
    """Resolve an Agent to all JSONL transcript paths modified since a time.

    When ``since`` is provided, returns all JSONL files modified after that
    time (sorted oldest-first).  When ``since`` is None, falls back to
    returning only the single most-recent file (wrapped in a list).

    Resolution chain: Agent → project_name → workspace CWD →
    hash CWD → ~/.claude/projects/{hash}/ → matching .jsonl files
    """
    cwd = _get_workspace_cwd(agent)
    if cwd is None:
        return []
    claude_dir = _cwd_to_claude_project_dir(cwd)
    if not claude_dir.is_dir():
        return []

    if since is not None:
        return _find_jsonl_files_since(claude_dir, since)

    # Fallback: single most-recent file
    newest = _find_most_recent_jsonl(claude_dir)
    return [newest] if newest is not None else []


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


def _find_jsonl_files_since(directory: Path, since: datetime) -> list[Path]:
    """Find all JSONL files modified since a given time, sorted oldest-first."""
    since_ts = since.timestamp()
    matching = [p for p in directory.glob("*.jsonl") if p.stat().st_mtime >= since_ts]
    matching.sort(key=lambda p: p.stat().st_mtime)
    return matching
