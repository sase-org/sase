"""Cache keys and storage for file-hint agent documents."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import blake2b
from typing import Any, cast

from sase.project_display_names import project_display_name_map_signature

from ...agent_completion import agent_wait_status_maps_for_app
from ...models._agent_clan_sections import clan_section_member_rows
from ...models.agent import Agent, wait_display_agent
from ...models.agent_session_members import (
    concrete_agent_session_turn_rows,
    agent_session_roster_container,
)
from ...models.agent_hoods import agent_owns_sase_agent
from ...llm_calls.slow import slow_tool_call_threshold_ms_from_widget
from ...util.lazy_syntax import CachedRenderable
from ._agent_clan_aggregation import get_cached_clan_section_snapshot
from ._agent_display_clan import panel_fold_state_from_widget
from ._agent_display_content import get_prompt_content
from ._agent_display_context import runner_capacity_for_app
from ._agent_display_header_summary import detail_header_summary_cache_key
from ._agent_display_state import AgentHintRender
from ._agent_macro_highlighting import agent_prompt_highlight_context
from ._hint_caps import HintContentBudget

_AGENT_HINT_RENDER_CACHE_MAX_ENTRIES = 16


@dataclass(frozen=True)
class AgentHintRenderCacheKey:
    """Inputs whose changes can alter an annotated hint document."""

    agent_identity: tuple[object, ...]
    agent_state_digest: str
    source_digest: str
    summary_key: tuple[object, ...] | None
    fold_level: object
    fold_overrides: tuple[tuple[str, str], ...]
    context_digest: str
    cap_parameters: tuple[int, int]
    attempt_view_mode: str
    attempt_pinned_number: int | None
    detaches_identity_header: bool = False
    detaches_xprompt: bool = False
    identity_header_hints: bool = True


@dataclass(frozen=True)
class AgentHintRenderCacheEntry:
    """A memoized hint result and its width-cached Rich document."""

    result: AgentHintRender
    renderable: object


def agent_hint_render_cache(
    widget: object,
) -> OrderedDict[AgentHintRenderCacheKey, AgentHintRenderCacheEntry]:
    """Return the lazily initialized hint-document cache for ``widget``."""
    cache = getattr(widget, "_agent_hint_render_cache", None)
    if cache is None:
        cache = OrderedDict()
        cast(Any, widget)._agent_hint_render_cache = cache
    return cast(
        OrderedDict[AgentHintRenderCacheKey, AgentHintRenderCacheEntry],
        cache,
    )


def clear_agent_hint_render_cache(widget: object) -> None:
    """Clear the panel-local annotated-document cache, when initialized."""
    cache = getattr(widget, "_agent_hint_render_cache", None)
    if cache is not None:
        cache.clear()
    cast(Any, widget)._rendered_agent_hint_cache_key = None


def _digest_parts(*parts: object) -> str:
    digest = blake2b(digest_size=16)
    for part in parts:
        encoded = repr(part).encode("utf-8", errors="replace")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _source_digest_parts(agent: Agent) -> list[tuple[str, object]]:
    """Collect source values once so a cache hit can avoid repr-ing large text."""
    parts: list[tuple[str, object]] = []
    seen: set[int] = set()

    def visit(candidate: Agent) -> None:
        candidate_id = id(candidate)
        if candidate_id in seen:
            return
        seen.add(candidate_id)
        parts.extend(
            (
                ("identity", candidate.identity),
                ("finalizer_status", repr(candidate.finalizer_status)),
                ("error_traceback", candidate.error_traceback),
                ("raw_xprompt", candidate.get_raw_prompt_content()),
                ("prompt", get_prompt_content(candidate)),
                ("reply_chunks", candidate.get_timestamped_reply_chunks()),
                ("live_reply", candidate.get_live_reply_content()),
                ("response", candidate.get_response_content()),
                ("chat_response", candidate.get_chat_response_content()),
            )
        )
        for followup in candidate.followup_agents:
            visit(followup)

    visit(agent)
    return parts


def _update_source_digest(digest: Any, label: str, value: object) -> None:
    encoded_label = label.encode("utf-8")
    encoded_value = repr(value).encode("utf-8", errors="replace")
    digest.update(len(encoded_label).to_bytes(4, "big"))
    digest.update(encoded_label)
    digest.update(len(encoded_value).to_bytes(8, "big"))
    digest.update(encoded_value)


def _source_fingerprint(parts: list[tuple[str, object]]) -> tuple[object, ...]:
    """Fingerprint immutable text by identity without walking its full contents."""
    fingerprint: list[object] = []
    for label, value in parts:
        if label == "reply_chunks" and isinstance(value, list):
            chunk_refs: list[tuple[int, int]] = []
            for item in value:
                if isinstance(item, tuple) and len(item) == 2:
                    chunk_refs.append((id(item[0]), id(item[1])))
                else:
                    chunk_refs.append((id(item), 0))
            fingerprint.append((label, tuple(chunk_refs)))
        elif isinstance(value, str):
            fingerprint.append((label, id(value)))
        else:
            fingerprint.append((label, value))
    return tuple(fingerprint)


def _source_digest_cached(widget: object, agent: Agent) -> str:
    """Reuse a digest while artifact-cache strings remain the same objects."""
    parts = _source_digest_parts(agent)
    fingerprint = _source_fingerprint(parts)
    cache = getattr(widget, "_agent_hint_source_digest_cache", None)
    if not isinstance(cache, OrderedDict):
        cache = OrderedDict()
        cast(Any, widget)._agent_hint_source_digest_cache = cache
    key = id(agent)
    cached = cache.get(key)
    if cached is not None and cached[0] is agent and cached[1] == fingerprint:
        cache.move_to_end(key)
        return cached[2]

    digest = blake2b(digest_size=16)
    for label, value in parts:
        _update_source_digest(digest, label, value)
    result = digest.hexdigest()
    # Keep the source objects alive alongside their identity fingerprint so
    # Python cannot recycle an id while the entry is still eligible to match.
    references = tuple(value for _, value in parts)
    cache[key] = (agent, fingerprint, result, references)
    cache.move_to_end(key)
    while len(cache) > _AGENT_HINT_RENDER_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)
    return result


def _fold_overrides_key(
    overrides: Mapping[str, Any],
) -> tuple[tuple[str, str], ...]:
    return tuple(
        sorted((repr(section), repr(level)) for section, level in overrides.items())
    )


def _hint_context_digest(
    widget: object,
    agent: Agent,
    raw_xprompt: str | None,
) -> str:
    """Digest warm in-memory header and styling context outside ``agent``."""
    try:
        app = widget.app  # type: ignore[attr-defined]
    except Exception:
        app = None
    wait_status_maps = (
        agent_wait_status_maps_for_app(app)
        if wait_display_agent(agent).waiting_for
        else None
    )
    lane_owner = agent_owns_sase_agent(agent)
    projection_resolver = getattr(app, "lane_neighbor_projection_for", None)
    lane_neighbors = (
        projection_resolver(agent)
        if lane_owner and callable(projection_resolver)
        else None
    )
    clan_neighbor_identities: tuple[object, ...] | None = None
    if agent.is_clan_container:
        clan_resolver = getattr(app, "clan_neighbor_projection_for", None)
        if callable(clan_resolver):
            try:
                clan_rows = clan_resolver(agent)
                clan_neighbor_identities = tuple(
                    (row.identity, row.display_order) for row in clan_rows
                )
            except Exception:
                clan_neighbor_identities = ()
    highlight_fingerprint: tuple[object, ...] = ()
    if raw_xprompt is not None or not agent.is_clan_container:
        highlight_fingerprint = agent_prompt_highlight_context(
            widget,
            agent,
            raw_xprompt or "",
            schedule=False,
        ).fingerprint
    return _digest_parts(
        getattr(app, "_unread_completed_agent_ids", set()),
        getattr(app, "_marked_agents", set()),
        runner_capacity_for_app(app),
        wait_status_maps,
        lane_neighbors,
        clan_neighbor_identities,
        slow_tool_call_threshold_ms_from_widget(widget),
        project_display_name_map_signature(),
        highlight_fingerprint,
    )


def agent_hint_render_cache_key(
    widget: object,
    agent: Agent,
) -> AgentHintRenderCacheKey:
    """Build the conservative key for the current annotated document."""
    fold_level, fold_overrides = panel_fold_state_from_widget(widget)
    if agent.is_clan_container:
        snapshot = get_cached_clan_section_snapshot(widget, agent)
        member_states = tuple(
            (member.identity, member.display_status)
            for member in clan_section_member_rows(agent)
        )
        agent_state_digest = _digest_parts(
            member_states,
            agent.agent_clan,
            agent.agent_clan_generation,
            snapshot.revision if snapshot is not None else 0,
        )
        source_digest = _digest_parts(agent.clan_summary)
        summary_key = None
        raw_xprompt = None
    else:
        roster_container = agent_session_roster_container(agent)
        if roster_container is not None:
            member_states = tuple(
                (member.identity, member.display_status)
                for member in concrete_agent_session_turn_rows(roster_container)
            )
            agent_state_digest = _digest_parts(agent, member_states)
        else:
            agent_state_digest = _digest_parts(agent)
        source_digest = _source_digest_cached(widget, agent)
        summary_key = detail_header_summary_cache_key(widget, agent)
        raw_xprompt = agent.get_raw_prompt_content()
    return AgentHintRenderCacheKey(
        agent_identity=cast(tuple[object, ...], agent.identity),
        agent_state_digest=agent_state_digest,
        source_digest=source_digest,
        summary_key=summary_key,
        fold_level=fold_level,
        fold_overrides=_fold_overrides_key(fold_overrides),
        context_digest=_hint_context_digest(widget, agent, raw_xprompt),
        cap_parameters=(
            HintContentBudget().remaining_bytes,
            HintContentBudget().remaining_lines,
        ),
        attempt_view_mode=str(getattr(widget, "attempt_view_mode", "merged")),
        attempt_pinned_number=getattr(widget, "attempt_pinned_number", None),
        detaches_identity_header=bool(
            getattr(widget, "detaches_identity_header", False)
        ),
        detaches_xprompt=bool(getattr(widget, "detaches_xprompt", False)),
        identity_header_hints=bool(
            getattr(widget, "identity_header_hints_enabled", True)
        ),
    )


def trim_agent_hint_render_cache(
    cache: OrderedDict[AgentHintRenderCacheKey, AgentHintRenderCacheEntry],
) -> None:
    """Evict least-recently-used entries beyond the panel cache limit."""
    while len(cache) > _AGENT_HINT_RENDER_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)
