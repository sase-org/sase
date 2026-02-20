"""Resolve an Agent to its Claude Code JSONL session transcript."""

import json
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

    # Check workspace_num first, then meta_workspace from step_output
    workspace_num = agent.workspace_num
    if (
        workspace_num is None
        and agent.step_output
        and isinstance(agent.step_output, dict)
    ):
        meta_ws = agent.step_output.get("meta_workspace")
        if meta_ws is not None:
            try:
                workspace_num = int(meta_ws)
            except (ValueError, TypeError):
                pass
    if workspace_num is None:
        workspace_num = 1

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
    """Find JSONL files modified since a given time, filtering to the best session match.

    When multiple candidates exist (e.g. multiple Claude Code sessions sharing
    the same project directory), selects the file whose first event timestamp
    is closest to ``since`` — the agent's start time.
    """
    since_ts = since.timestamp()
    matching = [p for p in directory.glob("*.jsonl") if p.stat().st_mtime >= since_ts]
    matching.sort(key=lambda p: p.stat().st_mtime)

    if len(matching) <= 1:
        return _expand_linked_sessions(directory, matching)

    best = _find_best_session_match(matching, since_ts)
    if best is not None:
        return _expand_linked_sessions(directory, [best])

    # Fallback: timestamp reading failed for all files
    return matching


def _expand_linked_sessions(directory: Path, sessions: list[Path]) -> list[Path]:
    """Follow .impl_session sidecar links to include implementation sessions."""
    result = list(sessions)
    for session_path in sessions:
        link_file = session_path.with_suffix(".impl_session")
        if link_file.exists():
            impl_uuid = link_file.read_text().strip()
            impl_path = directory / f"{impl_uuid}.jsonl"
            if impl_path.exists() and impl_path not in result:
                result.append(impl_path)
    result.sort(key=lambda p: p.stat().st_mtime)
    return result


def _find_best_session_match(candidates: list[Path], target_ts: float) -> Path | None:
    """Find the JSONL file whose first event timestamp is closest to target_ts."""
    best_path: Path | None = None
    best_diff = float("inf")

    for path in candidates:
        ts = _first_event_timestamp(path)
        if ts is None:
            continue
        diff = abs(ts - target_ts)
        if diff < best_diff:
            best_diff = diff
            best_path = path

    return best_path


def _first_event_timestamp(path: Path) -> float | None:
    """Read the first event timestamp from a JSONL file.

    Reads only the first few lines (cheap I/O) to extract the earliest
    timestamp from the session transcript.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for _ in range(10):
                line = f.readline()
                if not line:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                ts_str = event.get("timestamp")
                if not isinstance(ts_str, str) or not ts_str:
                    continue
                return _parse_iso_timestamp(ts_str)
    except OSError:
        pass
    return None


def _parse_iso_timestamp(ts_str: str) -> float | None:
    """Parse an ISO 8601 timestamp string to a Unix timestamp."""
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.timestamp()
    except ValueError:
        return None
