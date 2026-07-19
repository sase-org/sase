"""Storage and serialization helpers for chat history files."""

import os
from datetime import datetime
from pathlib import Path

from sase.core.paths import (
    find_sharded_file,
    iter_sharded_files,
    make_safe_filename,
    sharded_path,
)
from sase.core.time import get_timezone
from sase.history.multi_agent_prompt import MULTI_AGENT_PROMPT_METADATA_LABEL


def format_chat_filename(
    workflow: str,
    agent: str | None,
    branch_or_workspace: str,
    timestamp: str,
) -> str:
    """Build a sanitized chat filename from already-resolved components."""
    # Sanitize user/project/workflow-derived parts before joining so path-like
    # labels such as "~/org" remain a single filename component.
    parts = [
        make_safe_filename(branch_or_workspace),
        make_safe_filename(workflow),
    ]
    if agent is not None:
        parts.append(make_safe_filename(agent))
    parts.append(timestamp)
    return "-".join(parts)


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
    top-level, and finally scans all shards. Returns ``None`` if no
    matching file exists.
    """
    if not basename.endswith(".md"):
        basename = f"{basename}.md"
    return find_sharded_file("chats", basename)


def _clean_metadata_field(value: str | None) -> str | None:
    """Normalize a transcript metadata field for compact markdown output."""
    if value is None:
        return None
    cleaned = " ".join(str(value).split())
    return cleaned or None


def format_metadata_model(
    metadata_llm_provider: str | None,
    metadata_model: str | None,
) -> str | None:
    """Format transcript provider/model metadata without inventing unknowns."""
    provider = _clean_metadata_field(metadata_llm_provider)
    model = _clean_metadata_field(metadata_model)
    if provider and model:
        if model.startswith(f"{provider}/"):
            return model
        return f"{provider}/{model}"
    return model or provider


def format_transcript_metadata_blocks(
    *,
    display_timestamp: str,
    metadata_model: str | None,
    metadata_llm_provider: str | None,
    metadata_agent: str | None,
    metadata_multi_agent_prompt: str | None,
) -> str:
    rows = [f"- **TIMESTAMP:** {display_timestamp}"]
    model = format_metadata_model(metadata_llm_provider, metadata_model)
    agent = _clean_metadata_field(metadata_agent)
    multi_agent_prompt = _clean_metadata_field(metadata_multi_agent_prompt)
    if model:
        rows.append(f"- **MODEL:** {model}")
    if agent:
        rows.append(f"- **AGENT:** {agent}")
    if multi_agent_prompt:
        rows.append(
            f"- **{MULTI_AGENT_PROMPT_METADATA_LABEL}:** `{multi_agent_prompt}`"
        )
    return "\n".join(rows)


def write_chat_history(
    prompt: str,
    response: str,
    workflow: str,
    basename: str,
    agent: str | None = None,
    previous_history: str | None = None,
    extra_sections: str | None = None,
    *,
    metadata_model: str | None = None,
    metadata_llm_provider: str | None = None,
    metadata_agent: str | None = None,
    metadata_multi_agent_prompt: str | None = None,
) -> str:
    """Serialize a chat history using a precomputed basename."""
    file_path = sharded_path(
        "chats",
        basename if basename.endswith(".md") else f"{basename}.md",
    )
    display_timestamp = datetime.now(get_timezone()).strftime("%Y-%m-%d %H:%M:%S %Z")

    content_parts = [f"# Chat History - {workflow}"]
    if agent:
        content_parts.append(f" ({agent})")
    metadata_blocks = format_transcript_metadata_blocks(
        display_timestamp=display_timestamp,
        metadata_model=metadata_model,
        metadata_llm_provider=metadata_llm_provider,
        metadata_agent=metadata_agent,
        metadata_multi_agent_prompt=metadata_multi_agent_prompt,
    )
    content_parts.append(f"\n\n{metadata_blocks}\n")

    if extra_sections:
        content_parts.append(f"\n{extra_sections}\n")
    if previous_history:
        content_parts.append("\n## Previous Conversation\n\n")
        content_parts.append(previous_history)
        content_parts.append("\n\n---\n")

    content_parts.append("\n## Prompt\n\n")
    content_parts.append(prompt)
    content_parts.append("\n\n## Response\n\n")
    content_parts.append(response)
    content_parts.append("\n")

    with open(file_path, "w", encoding="utf-8") as f:
        f.write("".join(content_parts))

    return file_path.replace(str(Path.home()), "~")


def increment_markdown_headings(content: str) -> str:
    """Increment all markdown heading levels by one."""
    return "\n".join(
        "#" + line if line.startswith("#") else line for line in content.split("\n")
    )


def load_chat_history(file_ref: str, increment_headings: bool = False) -> str:
    """Load a chat history from a basename or full path."""
    if file_ref.startswith("/") or file_ref.startswith("~"):
        file_path = os.path.expanduser(file_ref)
    else:
        resolved = resolve_chat_file_path(file_ref)
        if resolved is None:
            raise FileNotFoundError(f"Chat history file not found: {file_ref}")
        file_path = resolved

    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Chat history file not found: {file_path}")

    with open(file_path, encoding="utf-8") as f:
        content = f.read()

    if increment_headings:
        content = increment_markdown_headings(content)
    return content


def list_chat_histories() -> list[str]:
    """List chat basenames by modification time, most recent first."""
    entries: list[tuple[str, float]] = []
    for path in iter_sharded_files("chats", pattern="*.md"):
        try:
            mtime = path.stat().st_mtime
        except OSError:
            continue
        entries.append((path.name[:-3], mtime))
    entries.sort(key=lambda entry: entry[1], reverse=True)
    return [name for name, _ in entries]


def find_chat_by_timestamp(timestamp: str) -> str | None:
    """Find a chat by timestamp suffix and return its home-relative path."""
    suffix = f"-{timestamp}.md"
    for path in iter_sharded_files("chats", pattern="*.md"):
        if path.name.endswith(suffix):
            return str(path).replace(str(Path.home()), "~")
    return None
