"""TTL-cached agent-session plan/bead preview resolution for sase's TUI.

Mirrors :mod:`sase.ace.tui.models.agent_bead`'s ``_BeadDisplayCache`` shape.
The cache expresses three states for one session's cache key:

* **cache miss** (:data:`AGENT_SESSION_PREVIEW_CACHE_MISS`) — never resolved; render
  the prompt-snippet rung.
* ``None`` — resolved, nothing to show; render the prompt-snippet rung and
  stop retrying until the (short) empty-result TTL expires.
* :class:`~sase.agent_session_plan_preview.AgentSessionPlanPreview` — render
  the plan/bead ladder.

Resolution (:func:`warm_agent_session_plan_previews`) may touch plan and bead
storage and must only run off the Textual event loop; the getters below are
pure memory reads safe from a render or keystroke path (see
``sase/memory/tui_perf.md`` rule 11).
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterable
from threading import RLock
from time import monotonic
from typing import Final, Literal, cast

from sase.agent.bead_display import BeadIssueLookupSession
from sase.agent_session_plan_preview import (
    AgentSessionPlanPreview,
    agent_session_plan_preview_from_bead,
    agent_session_plan_preview_from_plan,
)

from ._agent_associated_plan_types import AgentPlanEnrichment
from .agent import Agent
from .agent_associated_plan import resolve_agent_plan_enrichment
from .agent_session_members import concrete_agent_session_member_rows

AGENT_SESSION_PREVIEW_CACHE_MISS: Final = object()
_CACHE_TTL_SECONDS = 300.0
_CACHE_EMPTY_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 256

AgentSessionPreviewMemberToken = tuple[
    str,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    str | None,
    bool | None,
    str | None,
    str | None,
    str | None,
    str | None,
    int | None,
]
AgentSessionPreviewCacheKey = tuple[str, tuple[AgentSessionPreviewMemberToken, ...]]


class _AgentSessionPreviewCache:
    """Small TTL-bounded cache for resolved agent-session plan previews."""

    def __init__(
        self,
        *,
        ttl_seconds: float = _CACHE_TTL_SECONDS,
        empty_ttl_seconds: float = _CACHE_EMPTY_TTL_SECONDS,
        max_entries: int,
    ) -> None:
        self._ttl_seconds = ttl_seconds
        self._empty_ttl_seconds = empty_ttl_seconds
        self._max_entries = max_entries
        self._entries: OrderedDict[
            AgentSessionPreviewCacheKey, tuple[float, AgentSessionPlanPreview | None]
        ] = OrderedDict()
        self._lock = RLock()

    def get(
        self,
        key: AgentSessionPreviewCacheKey,
    ) -> AgentSessionPlanPreview | None | object:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return AGENT_SESSION_PREVIEW_CACHE_MISS

            _, value = entry
            self._entries.move_to_end(key)
            return value

    def should_resolve(self, key: AgentSessionPreviewCacheKey) -> bool:
        """Return whether *key* has no entry or needs TTL revalidation."""
        now = monotonic()
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return True

            expires_at, _ = entry
            self._entries.move_to_end(key)
            return expires_at <= now

    def set(
        self,
        key: AgentSessionPreviewCacheKey,
        value: AgentSessionPlanPreview | None,
    ) -> None:
        ttl_seconds = (
            self._ttl_seconds if value is not None else self._empty_ttl_seconds
        )
        expires_at = monotonic() + ttl_seconds
        with self._lock:
            self._entries[key] = (expires_at, value)
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


_AGENT_SESSION_PREVIEW_CACHE = _AgentSessionPreviewCache(max_entries=_CACHE_MAX_ENTRIES)


def _agent_session_plan_preview_cache_key(
    agent: Agent,
) -> AgentSessionPreviewCacheKey | None:
    """Return the memory-only inputs that can change a agent session's preview.

    ``None`` for a non-agent session row: ``agent_session_reference_name()`` falls back to
    the bare agent name for those, which would otherwise collide with a real
    agent session sharing the same name.
    """
    if not agent.is_agent_session_root_entry:
        return None
    name = agent.agent_session_reference_name()
    if name is None:
        return None
    return (
        name,
        tuple(
            _agent_session_member_token(row)
            for row in _agent_session_resolution_order(agent)
        ),
    )


def _agent_session_member_token(agent: Agent) -> AgentSessionPreviewMemberToken:
    return (
        agent.agent_name or "",
        agent.raw_suffix,
        agent.parent_timestamp,
        agent.plan_path,
        agent.archived_plan_path,
        agent.sdd_plan_path,
        agent.epic_plan_ref,
        agent.plan_committed,
        agent.plan_action,
        agent.epic_bead_id,
        agent.phase_bead_id,
        agent.workspace_dir,
        agent.effective_workspace_num,
    )


def cached_agent_session_plan_preview(
    agent: Agent,
) -> AgentSessionPlanPreview | None | object:
    """Return the cached preview state for *agent*'s agent session.

    Returns :data:`AGENT_SESSION_PREVIEW_CACHE_MISS` when never resolved, ``None``
    when resolved but empty, or the preview otherwise.
    """
    key = _agent_session_plan_preview_cache_key(agent)
    if key is None:
        return None
    return _AGENT_SESSION_PREVIEW_CACHE.get(key)


def should_resolve_agent_session_plan_preview(agent: Agent) -> bool:
    """Return whether *agent* is a session row whose preview needs resolving."""
    if not agent.is_agent_session_root_entry or agent.is_clan_container:
        return False
    key = _agent_session_plan_preview_cache_key(agent)
    if key is None:
        return False
    return _AGENT_SESSION_PREVIEW_CACHE.should_resolve(key)


def warm_agent_session_plan_previews(
    candidates: Iterable[Agent],
) -> dict[AgentSessionPreviewCacheKey, AgentSessionPlanPreview | None]:
    """Resolve uncached/expired agent session previews off the event loop.

    Opens one :class:`BeadIssueLookupSession` for the whole batch. Resolves
    each session's concrete members newest first, then the root as a
    compatibility fallback, taking the first non-empty result. Never raises:
    one bad plan file or bead store must not lose the rest of the batch.
    Returns a key-indexed mapping of every key resolved this call, so the
    caller can decide what changed.
    """
    resolved: dict[AgentSessionPreviewCacheKey, AgentSessionPlanPreview | None] = {}
    with BeadIssueLookupSession() as lookup_session:
        for agent in candidates:
            key = _agent_session_plan_preview_cache_key(agent)
            if key is None or key in resolved:
                continue
            try:
                preview = _resolve_agent_session_plan_preview(
                    agent,
                    lookup_session=lookup_session,
                )
            except Exception:
                continue
            _AGENT_SESSION_PREVIEW_CACHE.set(key, preview)
            resolved[key] = preview
    return resolved


def _resolve_agent_session_plan_preview(
    agent: Agent,
    *,
    lookup_session: BeadIssueLookupSession,
) -> AgentSessionPlanPreview | None:
    for candidate in _agent_session_resolution_order(agent):
        enrichment = resolve_agent_plan_enrichment(
            candidate,
            lookup_session=lookup_session,
        )
        preview = _preview_from_enrichment(enrichment)
        if preview is not None:
            return preview
    return None


def _agent_session_resolution_order(agent: Agent) -> tuple[Agent, ...]:
    members = concrete_agent_session_member_rows(agent)
    if len(members) <= 1:
        return members or (agent,)
    ordered = list(reversed(members))
    if all(member is not agent for member in ordered):
        ordered.append(agent)
    return tuple(ordered)


def _preview_from_enrichment(
    enrichment: AgentPlanEnrichment,
) -> AgentSessionPlanPreview | None:
    if enrichment.associated_plan is not None:
        preview = agent_session_plan_preview_from_plan(enrichment.associated_plan)
        if not preview.is_empty:
            return preview

    bead = enrichment.phase_bead
    if bead is not None and bead.bead_type in ("phase", "task"):
        bead_type = cast("Literal['phase', 'task']", bead.bead_type)
        preview = agent_session_plan_preview_from_bead(
            bead_type=bead_type,
            title=bead.title,
            parent_title=bead.epic_title,
            size=bead.size,
            description=bead.description,
        )
        if not preview.is_empty:
            return preview

    return None


__all__ = [
    "AGENT_SESSION_PREVIEW_CACHE_MISS",
    "AgentSessionPreviewCacheKey",
    "AgentSessionPreviewMemberToken",
    "cached_agent_session_plan_preview",
    "should_resolve_agent_session_plan_preview",
    "warm_agent_session_plan_previews",
]
