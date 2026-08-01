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
from ...models.agent_hoods import agent_owns_lane
from ...tools.slow import slow_tool_call_threshold_ms_from_widget
from ...util.lazy_syntax import CachedRenderable
from ._agent_clan_aggregation import get_cached_clan_section_snapshot
from ._agent_display_clan import panel_fold_state_from_widget
from ._agent_display_content import get_prompt_content
from ._agent_display_context import runner_capacity_for_app
from ._agent_display_header_summary import detail_header_summary_cache_key
from ._agent_display_state import AgentHintRender
from ._agent_xprompt_highlighting import known_xprompt_skill_names
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


@dataclass(frozen=True)
class AgentHintRenderCacheEntry:
    """A memoized hint result and its width-cached Rich document."""

    result: AgentHintRender
    renderable: CachedRenderable


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


def _source_digest(agent: Agent) -> str:
    """Digest every body source that can contribute hints for ``agent``."""
    digest = blake2b(digest_size=16)
    seen: set[int] = set()

    def add(label: str, value: object) -> None:
        encoded_label = label.encode("utf-8")
        encoded_value = repr(value).encode("utf-8", errors="replace")
        digest.update(len(encoded_label).to_bytes(4, "big"))
        digest.update(encoded_label)
        digest.update(len(encoded_value).to_bytes(8, "big"))
        digest.update(encoded_value)

    def visit(candidate: Agent) -> None:
        candidate_id = id(candidate)
        if candidate_id in seen:
            return
        seen.add(candidate_id)
        add("identity", candidate.identity)
        add("error_traceback", candidate.error_traceback)
        add("raw_xprompt", candidate.get_raw_xprompt_content())
        add("prompt", get_prompt_content(candidate))
        add("reply_chunks", candidate.get_timestamped_reply_chunks())
        add("live_reply", candidate.get_live_reply_content())
        add("response", candidate.get_response_content())
        add("chat_response", candidate.get_chat_response_content())
        for followup in candidate.followup_agents:
            visit(followup)

    visit(agent)
    return digest.hexdigest()


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
    lane_owner = agent_owns_lane(agent)
    projection_resolver = getattr(app, "lane_neighbor_projection_for", None)
    lane_neighbors = (
        projection_resolver(agent)
        if lane_owner and callable(projection_resolver)
        else None
    )
    known_skills = (
        known_xprompt_skill_names(widget, agent, raw_xprompt)
        if raw_xprompt
        else frozenset()
    )
    return _digest_parts(
        getattr(app, "_unread_completed_agent_ids", set()),
        getattr(app, "_marked_agents", set()),
        runner_capacity_for_app(app),
        wait_status_maps,
        lane_neighbors,
        slow_tool_call_threshold_ms_from_widget(widget),
        project_display_name_map_signature(),
        known_skills,
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
        agent_state_digest = _digest_parts(agent)
        source_digest = _source_digest(agent)
        summary_key = detail_header_summary_cache_key(widget, agent)
        raw_xprompt = agent.get_raw_xprompt_content()
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
    )


def trim_agent_hint_render_cache(
    cache: OrderedDict[AgentHintRenderCacheKey, AgentHintRenderCacheEntry],
) -> None:
    """Evict least-recently-used entries beyond the panel cache limit."""
    while len(cache) > _AGENT_HINT_RENDER_CACHE_MAX_ENTRIES:
        cache.popitem(last=False)
