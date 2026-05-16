"""Content-aware search cache for Agent prompts/replies.

The Agents tab ``/`` filter uses this to search the text of each agent's
xprompt, reply (live / response / chat fallback), and prior attempt replies
— not just metadata fields. Reads are cached by ``(path, mtime_ns)`` so that
auto-refresh while a query is active does not re-read unchanged files.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import TYPE_CHECKING, Any, Literal
from collections.abc import Iterable

if TYPE_CHECKING:
    from .agent import Agent

# Safety rail: cap the amount of text cached per file. Live replies are
# KB-sized in practice; this bounds worst-case memory if an agent has a
# pathologically large transcript.
_MAX_BYTES_PER_FILE = 512 * 1024


# Phase 5 of bead ``sase-3r`` (Fast Agents Tab Disk Loading) splits the
# content-search cache into two explicit modes:
#
# - ``"inbox"`` (default): used by ordinary Agents-tab filtering. Searches
#   the visible inbox: prompt + reply + chat for each agent. Attempt
#   history paths are intentionally excluded so the haystack does not
#   require per-agent ``attempts/<N>/`` directory walks — the loader
#   leaves ``attempt_history`` empty for unselected rows.
#
# - ``"archive"``: used by explicit historical / dismissed search flows
#   (revive, archive cleanup). Includes attempt-history paths so older
#   replies are searchable. Callers in this mode hydrate
#   ``agent.attempt_history`` (via
#   :func:`sase.ace.tui.actions.agents._loading_helpers.hydrate_attempt_history_for`
#   or ``load_agents_from_disk_with_state(..., hydrate_attempt_history=True)``)
#   before building the index.
ContentSearchMode = Literal["inbox", "archive"]


@dataclass(frozen=True)
class AgentContentSearchIndex:
    """In-memory content haystacks keyed by stable agent identity."""

    _haystacks_by_identity: dict[tuple[Any, str, str | None], str]

    def get_haystack(self, agent: Agent) -> str:
        """Return the prepared content haystack for *agent*, if present."""
        return self._haystacks_by_identity.get(agent.identity, "")


class AgentContentSearchCache:
    """Caches lowercased file contents by ``(path, mtime_ns)``.

    Exposes :meth:`get_haystack` which returns the concatenated searchable
    text for an agent (prompt + reply + attempt replies), all lowercased.
    Missing files and read errors are treated as empty strings so the UI
    filter keeps functioning from metadata-only matches.
    """

    def __init__(self, *, mode: ContentSearchMode = "inbox") -> None:
        self._cache: dict[str, tuple[int, str]] = {}
        # chat_path values parsed out of agent_meta.json, keyed by meta_path
        # -> (meta_mtime_ns, resolved_chat_path_or_empty).
        self._meta_cache: dict[str, tuple[int, str]] = {}
        self._mode: ContentSearchMode = mode

    @property
    def mode(self) -> ContentSearchMode:
        """Search scope for this cache. See :data:`ContentSearchMode`."""
        return self._mode

    def get_haystack(
        self, agent: Agent, *, mode: ContentSearchMode | None = None
    ) -> str:
        """Return the concatenated, lowercased searchable text for an agent.

        ``mode`` overrides the cache's default mode for one call. See
        :data:`ContentSearchMode` for the semantics of each mode.
        """
        paths = self._paths_for(agent, mode=mode or self._mode)
        if not paths:
            return ""
        parts: list[str] = []
        for path in paths:
            text = self._read_lowered(path)
            if text:
                parts.append(text)
        return "\n".join(parts)

    def fork(self) -> AgentContentSearchCache:
        """Return a shallow snapshot safe for worker-thread population."""
        clone = type(self)(mode=self._mode)
        clone._cache = dict(self._cache)
        clone._meta_cache = dict(self._meta_cache)
        return clone

    def merge(self, other: AgentContentSearchCache) -> None:
        """Merge cache state populated by a worker snapshot."""
        self._cache.update(other._cache)
        self._meta_cache.update(other._meta_cache)

    def build_index(
        self,
        agents: Iterable[Agent],
        *,
        mode: ContentSearchMode | None = None,
    ) -> AgentContentSearchIndex:
        """Build an in-memory content index for *agents* using this cache.

        ``mode`` overrides the cache's default mode for the duration of
        the build. See :data:`ContentSearchMode` for the contract of each
        mode — in particular, archive-mode callers are responsible for
        hydrating ``agent.attempt_history`` themselves before the build.
        """
        active_mode: ContentSearchMode = mode or self._mode
        haystacks_by_identity = {
            agent.identity: self.get_haystack(agent, mode=active_mode)
            for agent in agents
        }
        return AgentContentSearchIndex(haystacks_by_identity)

    def prune(self, active_agents: Iterable[Agent]) -> None:
        """Drop cache entries for paths no longer referenced by any agent.

        Inbox mode never seeds attempt-history paths into the cache, so
        the prune sweep keeps any attempt entries left over from a prior
        archive-mode build alive only while their owning agent is still
        active. This deliberately does not include attempt paths from
        agents whose ``attempt_history`` is unloaded — those rows would
        be re-hydrated explicitly on the archive path.
        """
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

    def _paths_for(
        self, agent: Agent, *, mode: ContentSearchMode = "inbox"
    ) -> list[str]:
        """Enumerate the filesystem paths whose content counts for this agent.

        In ``"inbox"`` mode, attempt-history paths are skipped — the
        default Agents-tab refresh does not hydrate ``attempt_history``
        (Phase 5 of bead ``sase-3r``), so the haystack would otherwise
        be silently inconsistent across rows. Callers that want
        attempts included pass ``mode="archive"`` after hydrating the
        attempt history explicitly.
        """
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
        if mode == "archive":
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
