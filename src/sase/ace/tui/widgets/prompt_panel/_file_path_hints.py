"""File path detection and hint rendering for agent displays."""

import os
import re

from rich.text import Text


# Regex to match file paths in text.
# Group 1: optional @ prefix (sase file reference convention)
# Group 2: the actual file path
_FILE_PATH_RE = re.compile(
    r"(?<![/\w@.])"  # Not preceded by word char, /, @, or .
    r"(@?)"  # Group 1: optional @ prefix
    r"("  # Group 2: the file path
    # Absolute paths: /foo/bar or ~/foo/bar
    r"(?:~?/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Relative paths with explicit prefix: ./foo or ../foo
    r"(?:\.{1,2}/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Dot-directory paths: .sase/foo.ext
    r"(?:\.[\w\-]+/[\w.+\-][\w.+\-/]*)"
    r"|"
    # Bare relative paths with extension: dir/file.ext
    r"(?:[\w\-]+/[\w.+\-/]*\.[\w]+)"
    r")"
)


def resolve_agent_workspace_dir(
    workspace_num: int | None,
    project_file: str,
    workspace_dir: str | None = None,
) -> str | None:
    """Get workspace directory for an agent.

    Delegates to workspace provider plugins to correctly resolve the
    workspace path for any VCS type (Git, Mercurial, etc.).

    Args:
        workspace_num: Agent's workspace number (None or 0 = no workspace).
        project_file: Path to the .gp project file.

    Returns:
        Workspace directory path, or None if unavailable.
    """
    if workspace_dir:
        expanded = os.path.expanduser(workspace_dir)
        if os.path.isdir(expanded):
            return expanded.rstrip("/")

    if workspace_num is None or workspace_num <= 0:
        return None

    from pathlib import Path

    from sase.workspace_provider import (
        detect_workflow_type,
        get_workspace_directory,
    )
    from sase.workspace_provider.utils import parse_workspace_dir

    try:
        workflow_type = detect_workflow_type(project_file)
        primary_dir = parse_workspace_dir(project_file) or ""
        project_name = Path(project_file).parent.name
        ws_dir = get_workspace_directory(
            workflow_type, workspace_num, project_name, primary_dir
        )
        ws_dir = ws_dir.rstrip("/")
        if os.path.isdir(ws_dir):
            return ws_dir
    except Exception:
        pass

    return None


def _resolve_file_path(path: str, workspace_dir: str | None) -> str:
    """Resolve a file path to absolute.

    For relative paths, prepends the workspace directory.
    For absolute/home paths, expands and returns directly.
    """
    expanded = os.path.expanduser(path)
    if os.path.isabs(expanded):
        return expanded
    if workspace_dir:
        return os.path.join(workspace_dir, expanded)
    return os.path.abspath(expanded)


def append_text_with_file_hints(
    text: Text,
    content: str,
    hint_counter: int,
    hint_mappings: dict[int, str],
    workspace_dir: str | None,
    style: str = "",
) -> int:
    """Append text content with ``[N]`` hint markers before file paths.

    Scans *content* for file path patterns, inserts numbered hint markers,
    and populates *hint_mappings* with resolved absolute paths.

    Args:
        text: Rich Text object to append to.
        content: Raw text to scan for file paths.
        hint_counter: Current hint counter (1-based).
        hint_mappings: Dict to populate (hint number -> absolute path).
        workspace_dir: Workspace directory for resolving relative paths.
        style: Default style for non-hint text segments.

    Returns:
        Updated hint counter.
    """
    last_end = 0
    for match in _FILE_PATH_RE.finditer(content):
        at_prefix = match.group(1)
        path = match.group(2)
        # Include @ prefix in display range
        full_match_start = match.start(1) if at_prefix else match.start(2)
        full_match_end = match.end(2)

        # Append text before this match
        if full_match_start > last_end:
            text.append(content[last_end:full_match_start], style=style)

        # Resolve the path (using group 2, without @ prefix)
        resolved_path = _resolve_file_path(path, workspace_dir)

        # Add hint marker and styled file path
        text.append(f"[{hint_counter}] ", style="bold #FFFF00")
        text.append(content[full_match_start:full_match_end], style="#87AFFF")

        hint_mappings[hint_counter] = resolved_path
        hint_counter += 1
        last_end = full_match_end

    # Append remaining text after last match (or entire content if no matches)
    if last_end < len(content):
        text.append(content[last_end:], style=style)

    return hint_counter
