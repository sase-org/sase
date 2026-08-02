"""Storage and serialization helpers for chat history files."""

import os
from collections.abc import Iterable, Iterator
from datetime import datetime
from pathlib import Path

from sase.core.paths import (
    find_sharded_file,
    is_shard_dir_name,
    make_safe_filename,
    sase_subdir,
    sharded_path,
)
from sase.core.time import get_timezone
from sase.history.multi_agent_prompt import MULTI_AGENT_PROMPT_METADATA_LABEL
from sase.history.chat_prompt_sections import render_prompt_sections


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
    top-level, all shards, and finally imported non-shard chat directories.
    Returns ``None`` if no matching file exists.
    """
    if not basename.endswith(".md"):
        basename = f"{basename}.md"
    resolved = find_sharded_file("chats", basename)
    if resolved is not None:
        return resolved
    for path in _iter_non_shard_chat_files():
        if path.name == basename:
            return str(path)
    return None


def _safe_sorted_paths(paths: Iterable[Path]) -> list[Path]:
    """Return paths sorted by name, ignoring entries that vanish mid-scan."""
    try:
        return sorted(paths, key=lambda path: path.name)
    except OSError:
        return []


def _iter_files_in_dir(directory: Path, pattern: str) -> Iterator[Path]:
    """Yield matching files in one directory, tolerating per-entry failures."""
    for path in _safe_sorted_paths(directory.glob(pattern)):
        try:
            if path.is_file():
                yield path
        except OSError:
            continue


def _iter_chat_base_entries() -> Iterator[Path]:
    base = sase_subdir("chats")
    try:
        if not base.is_dir():
            return
        entries = sorted(base.iterdir(), key=lambda path: path.name)
    except OSError:
        return
    yield from entries


def _iter_non_shard_chat_files() -> Iterator[Path]:
    """Yield one-level-deep chat markdown files from non-YYYYMM directories."""
    for entry in _iter_chat_base_entries():
        try:
            if not entry.is_dir() or is_shard_dir_name(entry.name):
                continue
        except OSError:
            continue
        yield from _iter_files_in_dir(entry, "*.md")


def _yield_unique_basenames(
    paths: Iterable[Path],
    seen_basenames: set[str],
) -> Iterator[Path]:
    for path in paths:
        basename = path.name
        if basename in seen_basenames:
            continue
        seen_basenames.add(basename)
        yield path


def iter_chat_files() -> Iterator[Path]:
    """Yield known chat markdown files across local and imported layouts.

    The canonical chat layout uses ``YYYYMM/`` shards, with legacy
    top-level ``*.md`` files still accepted. Imported remote transcripts
    are stored one level deeper in non-shard directories such as
    ``v2-.../``. Results are stable-sorted within each layout tier and
    deduplicated by basename, with the established sharded/legacy paths
    winning over imported duplicates.
    """
    seen_basenames: set[str] = set()
    entries = list(_iter_chat_base_entries())

    for entry in entries:
        try:
            if entry.is_dir() and is_shard_dir_name(entry.name):
                shard_files = _iter_files_in_dir(entry, "*.md")
                yield from _yield_unique_basenames(shard_files, seen_basenames)
        except OSError:
            continue

    legacy_files = (
        entry
        for entry in entries
        if entry.name.endswith(".md") and _safe_is_file(entry)
    )
    yield from _yield_unique_basenames(legacy_files, seen_basenames)

    yield from _yield_unique_basenames(
        _iter_non_shard_chat_files(),
        seen_basenames,
    )


def _safe_is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


def read_xprompt_prompt(artifacts_dir: str | Path | None) -> str | None:
    """Read one run's unrendered XPrompt prompt when it is available."""

    if artifacts_dir is None:
        return None
    try:
        return (Path(artifacts_dir) / "raw_xprompt.md").read_text(encoding="utf-8")
    except OSError:
        return None


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
    xprompt_prompt: str | None = None,
    rendered_prompt: str | None = None,
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

    prompt_sections = render_prompt_sections(xprompt_prompt, rendered_prompt)
    if prompt_sections:
        content_parts.append(f"\n{prompt_sections}")

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
    for path in iter_chat_files():
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
    for path in iter_chat_files():
        if path.name.endswith(suffix):
            return str(path).replace(str(Path.home()), "~")
    return None
