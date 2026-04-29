"""Reusable transcript discovery and resolution helpers.

This module is the foundation layer for the ``sase chats`` CLI and the
``/sase_chats`` agent-facing skill.  It does not import any CLI or
parser code — it speaks only to the on-disk chat history layout under
``~/.sase/chats/`` and to named-agent resolution under
``~/.sase/projects/``.

The dataclass :class:`ChatTranscriptInfo` is the primary catalog row and
:func:`chat_info_to_json` produces a stable-key-ordered serialization
suitable for ``sase chats list -j``.
"""

import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sase.core.paths import iter_sharded_files
from sase.core.time import get_timezone
from sase.history.chat import resolve_chat_file_path

# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------

# Matches a trailing ``-YYmmdd_HHMMSS`` filename suffix (no extension).
_FILENAME_TS_RE = re.compile(r"-(\d{6}_\d{6})$")

# Matches the chat history H1 banner: ``# Chat History - <workflow>`` with
# an optional `` (<agent>)`` segment.  ``save_chat_history`` writes both on
# the same line when an agent is present.
_HEADER_RE = re.compile(
    r"^#\s+Chat History\s*-\s*(\S+?)(?:\s+\(([^)]+)\))?\s*$",
    re.MULTILINE,
)

_PROMPT_HEADER_RE = re.compile(r"^#{1,6}\s+Prompt\s*$", re.MULTILINE)
_RESPONSE_HEADER_RE = re.compile(r"^#{1,6}\s+Response\s*$", re.MULTILINE)
_ANY_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)

# Bound how much of each transcript is read for snippet/query purposes so a
# single huge transcript cannot make ``list_chat_transcripts`` slow.
_READ_LIMIT_BYTES = 64 * 1024
_SNIPPET_MAX_CHARS = 140


# pyvision: tests/history/test_chat_catalog.py
@dataclass(frozen=True)
class ChatTranscriptInfo:
    """A single chat transcript entry suitable for skill summarization."""

    path: str
    absolute_path: str
    basename: str
    mtime: str
    size_bytes: int
    workflow: str | None
    agent: str | None
    timestamp: str | None
    prompt_snippet: str | None
    response_snippet: str | None


# pyvision: tests/history/test_chat_catalog.py
class ChatRefError(ValueError):
    """Raised when a chat reference cannot be resolved."""


def _shorten_home(path: str) -> str:
    home = str(Path.home())
    if path == home:
        return "~"
    if path.startswith(home + os.sep):
        return "~" + path[len(home) :]
    return path


def _read_head(p: Path) -> str:
    """Return up to ``_READ_LIMIT_BYTES`` of *p*, decoded leniently."""
    try:
        with open(p, "rb") as f:
            raw = f.read(_READ_LIMIT_BYTES)
    except OSError:
        return ""
    return raw.decode("utf-8", errors="replace")


def _parse_header(content: str) -> tuple[str | None, str | None]:
    m = _HEADER_RE.search(content)
    if not m:
        return (None, None)
    workflow = (m.group(1) or "").strip() or None
    agent = (m.group(2) or "").strip() or None
    return (workflow, agent)


def _filename_timestamp(basename_no_ext: str) -> str | None:
    m = _FILENAME_TS_RE.search(basename_no_ext)
    return m.group(1) if m else None


def _extract_section_snippet(content: str, header_re: re.Pattern[str]) -> str | None:
    """Return a short snippet of the body following ``header_re`` in *content*.

    Looks for the first matching heading, then captures text until the next
    heading (any level) or end-of-content.  Collapses whitespace and clamps
    to ``_SNIPPET_MAX_CHARS`` characters.
    """
    m = header_re.search(content)
    if not m:
        return None
    rest = content[m.end() :]
    next_heading = _ANY_HEADING_RE.search(rest)
    body = rest[: next_heading.start()] if next_heading else rest
    body = body.strip()
    if not body:
        return None
    body = re.sub(r"\s+", " ", body)
    if len(body) > _SNIPPET_MAX_CHARS:
        body = body[: _SNIPPET_MAX_CHARS - 1].rstrip() + "…"
    return body


def _build_info(p: Path, mtime: float, head: str) -> ChatTranscriptInfo | None:
    try:
        size = p.stat().st_size
    except OSError:
        return None
    basename_no_ext = p.name[:-3] if p.name.endswith(".md") else p.name
    workflow, agent = _parse_header(head)
    timestamp = _filename_timestamp(basename_no_ext)
    prompt_snippet = _extract_section_snippet(head, _PROMPT_HEADER_RE)
    response_snippet = _extract_section_snippet(head, _RESPONSE_HEADER_RE)
    mtime_iso = datetime.fromtimestamp(mtime, get_timezone()).isoformat()
    return ChatTranscriptInfo(
        path=_shorten_home(str(p)),
        absolute_path=str(p),
        basename=basename_no_ext,
        mtime=mtime_iso,
        size_bytes=size,
        workflow=workflow,
        agent=agent,
        timestamp=timestamp,
        prompt_snippet=prompt_snippet,
        response_snippet=response_snippet,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


# pyvision: tests/history/test_chat_catalog.py
def list_chat_transcripts(
    limit: int | None = None,
    query: str | None = None,
) -> list[ChatTranscriptInfo]:
    """List chat transcripts, newest first.

    Iterates ``~/.sase/chats`` (sharded ``YYYYMM/`` plus legacy top-level)
    and returns one :class:`ChatTranscriptInfo` per readable ``*.md`` file.

    Args:
        limit: If set, return at most this many entries after sorting.
        query: Case-insensitive substring filter applied to path/basename
            first, then to a bounded head of the transcript content.

    Returns:
        Newest-first list of :class:`ChatTranscriptInfo`.
    """
    entries: list[tuple[Path, float]] = []
    for p in iter_sharded_files("chats", pattern="*.md"):
        try:
            mtime = p.stat().st_mtime
        except OSError:
            continue
        entries.append((p, mtime))
    entries.sort(key=lambda e: e[1], reverse=True)

    q = query.lower() if query else None
    results: list[ChatTranscriptInfo] = []
    for p, mtime in entries:
        path_str = str(p)
        head: str | None = None
        if q is not None:
            cheap = q in path_str.lower() or q in p.name.lower()
            if not cheap:
                head = _read_head(p)
                if q not in head.lower():
                    continue
        if head is None:
            head = _read_head(p)
        info = _build_info(p, mtime, head)
        if info is None:
            continue
        results.append(info)
        if limit is not None and len(results) >= limit:
            break
    return results


# pyvision: tests/history/test_chat_catalog.py
def chat_info_to_json(info: ChatTranscriptInfo) -> dict[str, object]:
    """Return a stable-key-ordered dict for JSON serialization.

    The order matches the documented ``sase chats list -j`` shape so the
    resulting JSON is diff-friendly across runs.  ``absolute_path`` is
    intentionally omitted from the public JSON; callers that want it can
    use the dataclass field directly.
    """
    return {
        "path": info.path,
        "basename": info.basename,
        "mtime": info.mtime,
        "size_bytes": info.size_bytes,
        "workflow": info.workflow,
        "agent": info.agent,
        "timestamp": info.timestamp,
        "prompt_snippet": info.prompt_snippet,
        "response_snippet": info.response_snippet,
    }


# pyvision: tests/history/test_chat_catalog.py
def resolve_chat_ref(
    agent: str | None = None,
    path: str | None = None,
    basename: str | None = None,
) -> str:
    """Resolve a chat reference to an absolute file path.

    Exactly one of ``agent``, ``path``, ``basename`` must be provided.

    - ``path``: ``~`` is expanded; the file must exist.
    - ``basename``: resolved via the existing chat-basename lookup
      (sharded location, then legacy top-level, then cross-shard scan).
    - ``agent``: follows the ``#resume`` fallback order — first
      ``done.json["response_path"]`` of the named done agent, then
      ``agent_meta.json["chat_path"]`` of any agent (running or done).

    Raises:
        ChatRefError: zero or multiple selectors were provided.
        FileNotFoundError: the selector resolved to no existing file.
    """
    selectors = [s for s in (agent, path, basename) if s]
    if len(selectors) == 0:
        raise ChatRefError("Exactly one of agent, path, or basename is required")
    if len(selectors) > 1:
        raise ChatRefError("Specify exactly one of agent, path, or basename")

    if path is not None:
        expanded = os.path.expanduser(path)
        if not os.path.isfile(expanded):
            raise FileNotFoundError(f"Chat file not found: {path}")
        return expanded

    if basename is not None:
        resolved = resolve_chat_file_path(basename)
        if resolved is None or not os.path.isfile(resolved):
            raise FileNotFoundError(f"Chat file not found: {basename}")
        return resolved

    # agent selector — defer the import so unrelated callers don't pay it.
    assert agent is not None
    from sase.agent.names import find_named_agent

    found = find_named_agent(agent, only_done=True)
    if found is not None:
        candidate = _read_path_from_json(
            os.path.join(found.artifacts_dir, "done.json"), "response_path"
        )
        if candidate is not None:
            return candidate

    found = find_named_agent(agent)
    if found is not None:
        candidate = _read_path_from_json(
            os.path.join(found.artifacts_dir, "agent_meta.json"), "chat_path"
        )
        if candidate is not None:
            return candidate

    raise FileNotFoundError(f"No chat history found for agent: {agent}")


def _read_path_from_json(json_path: str, key: str) -> str | None:
    """Read ``key`` from JSON at ``json_path`` and return it if it points
    at an existing file.  Returns ``None`` on any failure or if missing.
    """
    try:
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    value = data.get(key) if isinstance(data, dict) else None
    if not isinstance(value, str) or not value:
        return None
    expanded = os.path.expanduser(value)
    return expanded if os.path.isfile(expanded) else None
