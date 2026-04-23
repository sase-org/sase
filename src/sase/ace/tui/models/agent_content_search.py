"""Content-aware search cache for Agent prompts/replies.

The Agents tab ``/`` filter uses this to search the text of each agent's
xprompt, reply (live / response / chat fallback), and prior attempt replies
— not just metadata fields. Reads are cached by ``(path, mtime_ns)`` so that
auto-refresh while a query is active does not re-read unchanged files.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING
from collections.abc import Iterable

if TYPE_CHECKING:
    from .agent import Agent

# Safety rail: cap the amount of text cached per file. Live replies are
# KB-sized in practice; this bounds worst-case memory if an agent has a
# pathologically large transcript.
_MAX_BYTES_PER_FILE = 512 * 1024


class AgentContentSearchCache:
    """Caches lowercased file contents by ``(path, mtime_ns)``.

    Exposes :meth:`get_haystack` which returns the concatenated searchable
    text for an agent (prompt + reply + attempt replies), all lowercased.
    Missing files and read errors are treated as empty strings so the UI
    filter keeps functioning from metadata-only matches.
    """

    def __init__(self) -> None:
        self._cache: dict[str, tuple[int, str]] = {}
        # chat_path values parsed out of agent_meta.json, keyed by meta_path
        # -> (meta_mtime_ns, resolved_chat_path_or_empty).
        self._meta_cache: dict[str, tuple[int, str]] = {}

    def get_haystack(self, agent: Agent) -> str:
        """Return the concatenated, lowercased searchable text for an agent."""
        paths = self._paths_for(agent)
        if not paths:
            return ""
        parts: list[str] = []
        for path in paths:
            text = self._read_lowered(path)
            if text:
                parts.append(text)
        return "\n".join(parts)

    def prune(self, active_agents: Iterable[Agent]) -> None:
        """Drop cache entries for paths no longer referenced by any agent."""
        active_content: set[str] = set()
        active_meta: set[str] = set()
        for agent in active_agents:
            artifacts_dir = agent.get_artifacts_dir()
            if artifacts_dir:
                active_content.add(os.path.join(artifacts_dir, "raw_xprompt.md"))
                active_content.add(os.path.join(artifacts_dir, "live_reply.md"))
                meta_path = os.path.join(artifacts_dir, "agent_meta.json")
                active_meta.add(meta_path)
                cached = self._meta_cache.get(meta_path)
                if cached is not None and cached[1]:
                    active_content.add(cached[1])
            if agent.response_path:
                active_content.add(os.path.expanduser(agent.response_path))
            for attempt in agent.attempt_history:
                if attempt.live_reply_path:
                    active_content.add(attempt.live_reply_path)
        for path in list(self._cache):
            if path not in active_content:
                del self._cache[path]
        for path in list(self._meta_cache):
            if path not in active_meta:
                del self._meta_cache[path]

    # --- Internal helpers ---

    def _paths_for(self, agent: Agent) -> list[str]:
        """Enumerate the filesystem paths whose content counts for this agent."""
        paths: list[str] = []
        artifacts_dir = agent.get_artifacts_dir()
        if artifacts_dir:
            paths.append(os.path.join(artifacts_dir, "raw_xprompt.md"))
            paths.append(os.path.join(artifacts_dir, "live_reply.md"))
            meta_path = os.path.join(artifacts_dir, "agent_meta.json")
            chat_path = self._resolve_chat_path(meta_path)
            if chat_path:
                paths.append(chat_path)
        if agent.response_path:
            paths.append(os.path.expanduser(agent.response_path))
        for attempt in agent.attempt_history:
            if attempt.live_reply_path:
                paths.append(attempt.live_reply_path)
        return paths

    def _read_lowered(self, path: str) -> str:
        """Read up to ``_MAX_BYTES_PER_FILE`` from ``path``, lowercase, cache."""
        try:
            mtime_ns = os.stat(path).st_mtime_ns
        except OSError:
            return ""
        cached = self._cache.get(path)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1]
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                content = f.read(_MAX_BYTES_PER_FILE)
        except OSError:
            return ""
        lowered = content.lower()
        self._cache[path] = (mtime_ns, lowered)
        return lowered

    def _resolve_chat_path(self, meta_path: str) -> str | None:
        """Return the expanded ``chat_path`` from ``agent_meta.json``, cached."""
        try:
            mtime_ns = os.stat(meta_path).st_mtime_ns
        except OSError:
            return None
        cached = self._meta_cache.get(meta_path)
        if cached is not None and cached[0] == mtime_ns:
            return cached[1] or None
        try:
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._meta_cache[meta_path] = (mtime_ns, "")
            return None
        chat_path = data.get("chat_path")
        resolved = os.path.expanduser(chat_path) if chat_path else ""
        self._meta_cache[meta_path] = (mtime_ns, resolved)
        return resolved or None
