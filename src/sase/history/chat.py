"""Chat history management for sase agents.

This module provides functions to save and load conversation histories
from sase agent runs. Histories are stored in ~/.sase/chats/ with filenames
that encode the branch/workspace, workflow, optional agent name, and timestamp.
"""

import os
import re
from datetime import datetime
from pathlib import Path

from sase.core.changespec import strip_reverted_suffix
from sase.core.paths import (
    find_sharded_file,
    iter_sharded_files,
    sharded_path,
)
from sase.core.time import generate_timestamp, get_timezone
from sase.core.shell import run_shell_command


# Matches #resume:name, #resume(`name`), #resume(name),
# #resume_by_chat:path, #resume_by_chat(`path`), #resume_by_chat(path)
_RESUME_REF_RE = re.compile(
    r"#(resume|resume_by_chat)"  # xprompt name
    r"(?:"
    r":(`[^`]+`|[^\s,)]+)"  # colon syntax (backtick-quoted or bare)
    r"|"
    r"\((`[^`]+`|[^)]+)\)"  # paren syntax
    r")"
)


def _find_resume_refs(text: str) -> list[tuple[str, str, str]]:
    """Find all #resume references in text.

    Returns:
        List of (full_match, xprompt_name, argument) tuples.
    """
    results = []
    for m in _RESUME_REF_RE.finditer(text):
        full_match = m.group(0)
        xprompt_name = m.group(1)
        # Argument is in group 2 (colon syntax) or group 3 (paren syntax)
        raw_arg = m.group(2) or m.group(3)
        # Strip backtick quoting
        arg = raw_arg.strip("`")
        results.append((full_match, xprompt_name, arg))
    return results


def _resolve_resume_to_chat_path(xprompt_name: str, argument: str) -> str | None:
    """Resolve a #resume ref to a chat file path.

    For ``resume``: looks up the named agent and reads its done.json.
    For ``resume_by_chat``: returns the argument directly.

    Returns:
        Absolute chat file path, or None on any failure.
    """
    if xprompt_name == "resume_by_chat":
        path = os.path.expanduser(argument)
        if not path.endswith(".md"):
            resolved = resolve_chat_file_path(path)
            return resolved
        return path if os.path.exists(path) else None

    # resume — resolve via agent name
    try:
        from sase.agent.names import find_named_agent

        agent = find_named_agent(argument, only_done=True)
        if agent is None:
            return None
        import json

        done_path = os.path.join(agent.artifacts_dir, "done.json")
        with open(done_path, encoding="utf-8") as f:
            done_data = json.load(f)
        response_path = done_data.get("response_path")
        if not response_path:
            return None
        expanded = os.path.expanduser(response_path)
        return expanded if os.path.exists(expanded) else None
    except Exception:
        return None


def _parse_flat_turns(text: str) -> list[tuple[str, str]]:
    """Parse **User:**/**Assistant:** formatted text into (prompt, response) tuples."""
    # Split on **User:** markers
    chunks = re.split(r"\*\*User:\*\*\s*", text)
    turns = []
    for chunk in chunks:
        chunk = chunk.strip()
        if not chunk:
            continue
        # Split on **Assistant:** marker
        parts = re.split(r"\*\*Assistant:\*\*\s*", chunk, maxsplit=1)
        if len(parts) == 2:
            prompt = parts[0].strip()
            response = re.sub(r"\n---\s*$", "", parts[1]).strip()
            turns.append((prompt, response))
    return turns


def _extract_previous_conversation_turns(
    content: str,
) -> list[tuple[str, str]]:
    """Extract turns from ## Previous Conversation sections in raw chat content."""
    # Match "## Previous Conversation" or deeper heading variants
    pattern = re.compile(r"^#{2,6}\s+Previous Conversation\s*$", re.MULTILINE)
    matches = list(pattern.finditer(content))
    if not matches:
        return []

    all_turns: list[tuple[str, str]] = []
    for m in matches:
        # Extract body until next same-or-higher-level heading or end
        start = m.end()
        heading_level = m.group(0).lstrip().split()[0]  # e.g. "##"
        next_heading = re.search(
            rf"^#{{{1},{len(heading_level)}}}\s",
            content[start:],
            re.MULTILINE,
        )
        end = start + next_heading.start() if next_heading else len(content)
        body = content[start:end].strip()
        # Strip trailing --- separator
        body = re.sub(r"\n---\s*$", "", body).strip()
        all_turns.extend(_parse_flat_turns(body))
    return all_turns


def _get_branch_or_workspace_name() -> str:
    """Get the current branch name or workspace name."""
    result = run_shell_command("branch_or_workspace_name", capture_output=True)
    if result.returncode != 0:
        raise RuntimeError(f"Failed to get branch_or_workspace_name: {result.stderr}")
    return strip_reverted_suffix(result.stdout.strip())


def generate_chat_filename(
    workflow: str,
    agent: str | None = None,
    branch_or_workspace: str | None = None,
    timestamp: str | None = None,
) -> str:
    """Generate a chat history filename.

    Args:
        workflow: The workflow name (e.g., 'run', 'rerun', 'crs')
        agent: Optional agent name within a multi-agent workflow
        branch_or_workspace: Optional branch/workspace name (defaults to current)
        timestamp: Optional timestamp (defaults to current time)

    Returns:
        The full path to the chat history file (without extension for basename usage)
    """
    if branch_or_workspace is None:
        branch_or_workspace = _get_branch_or_workspace_name()
    if timestamp is None:
        timestamp = generate_timestamp()

    # Normalize workflow name: replace dashes and slashes with underscores for consistent filenames
    normalized_workflow = workflow.replace("-", "_").replace("/", "_")

    # Build filename parts
    parts = [branch_or_workspace, normalized_workflow]
    if agent is not None:
        parts.append(agent)
    parts.append(timestamp)

    # Join with dashes
    basename = "-".join(parts)

    return basename


def get_chat_file_path(basename: str) -> str:
    """Return the sharded write path for a chat history file.

    For reads, prefer :func:`resolve_chat_file_path` which also handles
    legacy (unsharded) paths and cross-shard lookup.
    """
    if not basename.endswith(".md"):
        basename = f"{basename}.md"
    return sharded_path("chats", basename, ensure=False)


def resolve_chat_file_path(basename: str) -> str | None:
    """Find an existing chat history file by basename.

    Checks the expected shard (from the filename timestamp), legacy
    top-level, and finally scans all shards.  Returns ``None`` if no
    matching file exists.
    """
    if not basename.endswith(".md"):
        basename = f"{basename}.md"
    return find_sharded_file("chats", basename)


def save_chat_history(
    prompt: str,
    response: str,
    workflow: str,
    agent: str | None = None,
    previous_history: str | None = None,
    timestamp: str | None = None,
    extra_sections: str | None = None,
    branch_or_workspace: str | None = None,
) -> str:
    """Save a chat history to a file.

    Args:
        prompt: The prompt sent to the agent
        response: The response from the agent
        workflow: The workflow name
        agent: Optional agent name for multi-agent workflows
        previous_history: Optional previous conversation history to prepend
        timestamp: Optional timestamp for filename (YYmmdd_HHMMSS format)
        extra_sections: Optional markdown content (plan feedback, Q&A) to
            insert after the timestamp and before the prompt.

    Returns:
        The full path to the saved chat history file
    """
    basename = generate_chat_filename(
        workflow, agent, branch_or_workspace=branch_or_workspace, timestamp=timestamp
    )
    # get_chat_file_path returns the sharded write location (not ensured).
    file_path = sharded_path(
        "chats",
        basename if basename.endswith(".md") else f"{basename}.md",
    )

    display_timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")

    # Build content
    content_parts = []

    # Add header
    content_parts.append(f"# Chat History - {workflow}")
    if agent:
        content_parts.append(f" ({agent})")
    content_parts.append(f"\n\n**Timestamp:** {display_timestamp}\n")

    # Add extra sections (plan feedback, Q&A) before prompt
    if extra_sections:
        content_parts.append(f"\n{extra_sections}\n")

    # Add previous history if present
    if previous_history:
        content_parts.append("\n## Previous Conversation\n\n")
        content_parts.append(previous_history)
        content_parts.append("\n\n---\n")

    # Add current prompt and response
    content_parts.append("\n## Prompt\n\n")
    content_parts.append(prompt)
    content_parts.append("\n\n## Response\n\n")
    content_parts.append(response)
    content_parts.append("\n")

    content = "".join(content_parts)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    # Return path with ~ for home directory
    return file_path.replace(str(Path.home()), "~")


def _increment_markdown_headings(content: str) -> str:
    """Increment all markdown heading levels by one.

    Args:
        content: The markdown content to process

    Returns:
        Content with all heading levels incremented (# -> ##, ## -> ###, etc.)
    """
    lines = content.split("\n")
    result_lines = []

    for line in lines:
        # Check if line starts with markdown heading
        if line.startswith("#"):
            # Add one more # to increment the heading level
            result_lines.append("#" + line)
        else:
            result_lines.append(line)

    return "\n".join(result_lines)


def _parse_chat_turns(content: str) -> list[tuple[str, str]]:
    """Parse chat history content into chronological (prompt, response) turns.

    Finds all Prompt/Response heading pairs at any markdown heading level,
    extracts their content, and sorts by heading depth (deepest = oldest)
    to produce chronological order.

    Args:
        content: Raw markdown content from a chat history file.

    Returns:
        List of (prompt_text, response_text) tuples in chronological order.
    """
    heading_pattern = re.compile(r"^(#{1,6})\s+(Prompt|Response)\s*$", re.MULTILINE)
    matches = list(heading_pattern.finditer(content))

    turns: list[tuple[int, str, str]] = []  # (level, prompt_text, response_text)

    i = 0
    while i < len(matches) - 1:
        m_prompt = matches[i]
        m_response = matches[i + 1]

        # Expect Prompt followed by Response at the same heading level
        if m_prompt.group(2) != "Prompt" or m_response.group(2) != "Response":
            i += 1
            continue

        prompt_level = len(m_prompt.group(1))
        response_level = len(m_response.group(1))
        if prompt_level != response_level:
            i += 1
            continue

        # Extract prompt text
        prompt_text = content[m_prompt.end() : m_response.start()].strip()

        # Extract response text (until next match or end of content)
        response_start = m_response.end()
        response_end = matches[i + 2].start() if i + 2 < len(matches) else len(content)
        response_text = content[response_start:response_end].strip()

        # Strip trailing --- separator
        response_text = re.sub(r"\n---\s*$", "", response_text).strip()

        turns.append((prompt_level, prompt_text, response_text))
        i += 2

    # Sort by depth (deepest = oldest → first in chronological order)
    turns.sort(key=lambda t: t[0], reverse=True)

    return [(prompt, response) for _, prompt, response in turns]


def extract_response_from_chat_file(file_ref: str) -> str | None:
    """Extract the most recent response text from a chat file.

    Args:
        file_ref: Either a basename or full path to the chat history file.

    Returns:
        The most recent response text, or None if the file can't be read or parsed.
    """
    try:
        content = _load_chat_history(file_ref)
    except (FileNotFoundError, OSError):
        return None
    turns = _parse_chat_turns(content)
    if not turns:
        return None
    return turns[-1][1]  # last turn = most recent response


def load_chat_for_resume(
    file_ref: str,
    _visited: set[str] | None = None,
) -> str:
    """Load a chat history file and format it as flat turns for resume.

    Loads the file without heading increment, parses all (prompt, response)
    turns in chronological order, and formats them with bold markers instead
    of heading levels to prevent heading inflation on repeated resumes.

    Recursively expands any ``#resume`` or ``#resume_by_chat`` references
    found in prompt text, inlining the referenced conversation history.

    Args:
        file_ref: Either a basename or full path to the chat history file.
        _visited: Internal cycle-detection set of resolved file paths.

    Returns:
        Formatted string with flat **User:**/**Assistant:** turns.
    """
    if _visited is None:
        _visited = set()

    content = _load_chat_history(file_ref)

    # Resolve file_ref to an absolute path for cycle detection
    if file_ref.startswith("/") or file_ref.startswith("~"):
        abs_path = os.path.expanduser(file_ref)
    else:
        abs_path = resolve_chat_file_path(file_ref) or get_chat_file_path(file_ref)
    _visited.add(abs_path)

    turns = _parse_chat_turns(content)

    if not turns:
        return content  # Fallback to raw content if parsing fails

    expanded_turns: list[tuple[str, str]] = []
    for prompt, response in turns:
        refs = _find_resume_refs(prompt)
        for full_match, xprompt_name, argument in refs:
            resolved_path = _resolve_resume_to_chat_path(xprompt_name, argument)
            if resolved_path and resolved_path not in _visited:
                # Recursively load and parse the referenced history
                nested_text = load_chat_for_resume(resolved_path, _visited)
                nested_turns = _parse_flat_turns(nested_text)
                expanded_turns.extend(nested_turns)
            elif resolved_path is None:
                # Fallback: extract from ## Previous Conversation in this file
                fallback_turns = _extract_previous_conversation_turns(content)
                expanded_turns.extend(fallback_turns)
            # Strip the #resume ref from the prompt text
            prompt = prompt.replace(full_match, "").strip()

        if prompt or response:
            expanded_turns.append((prompt, response))

    parts = []
    for prompt, response in expanded_turns:
        parts.append(f"**User:**\n\n{prompt}\n\n**Assistant:**\n\n{response}")

    return "\n\n---\n\n".join(parts)


def _load_chat_history(file_ref: str, increment_headings: bool = False) -> str:
    """Load a chat history from a file.

    Args:
        file_ref: Either a basename (e.g., 'foobar_run_251128104155')
                  or a full path (e.g., '~/.sase/chats/foobar_run_251128104155.md')
        increment_headings: If True, increment all markdown heading levels by one

    Returns:
        The content of the chat history file
    """
    # Handle full paths
    if file_ref.startswith("/") or file_ref.startswith("~"):
        file_path = os.path.expanduser(file_ref)
    else:
        # Treat as basename — search shards + legacy top-level.
        resolved = resolve_chat_file_path(file_ref)
        if resolved is None:
            raise FileNotFoundError(f"Chat history file not found: {file_ref}")
        file_path = resolved

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Chat history file not found: {file_path}")

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    if increment_headings:
        content = _increment_markdown_headings(content)

    return content


def list_chat_histories() -> list[str]:
    """List all available chat history basenames.

    Returns:
        A list of chat history basenames (without .md extension),
        sorted by modification time (most recent first).
    """
    entries: list[tuple[str, float]] = []
    for p in iter_sharded_files("chats", pattern="*.md"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        entries.append((p.name[:-3], mtime))
    entries.sort(key=lambda e: e[1], reverse=True)
    return [name for name, _ in entries]


def find_chat_by_timestamp(timestamp: str) -> str | None:
    """Find a chat history file by its timestamp suffix.

    Returns the path (with ~ for home) or None if not found.
    """
    suffix = f"-{timestamp}.md"
    for p in iter_sharded_files("chats", pattern="*.md"):
        if p.name.endswith(suffix):
            return str(p).replace(str(Path.home()), "~")
    return None
