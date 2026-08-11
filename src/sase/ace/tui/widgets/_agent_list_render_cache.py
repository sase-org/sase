"""LRU caches and cache-key builders for agent-list row rendering.

The caches live on the AgentList widget instance (one per widget); the
key builders capture every input that affects the rendered Option so
that a cache hit only happens when the visible output would be
byte-identical to the prior render.
"""

from collections import OrderedDict
from collections.abc import Collection, Mapping
from datetime import datetime
from typing import Any, Literal

from rich.text import Text
from textual.widgets.option_list import Option

from ..models._agent_clan import (
    ClanStatusCounts as ParallelFamilyStatusCounts,
    clan_member_counts as parallel_family_member_counts,
)
from ..models.agent import Agent, AgentType
from ..models.agent_bead import agent_has_confirmed_bead
from ..models.agent_groups import GroupingMode, GroupRow
from ..models.agent_time import row_runtime_or_wait_ticks, wait_display_agent
from ..models.tribe_display import TRIBE_IDENTITY_FALLBACK_COLOR
from ._agent_list_helpers import ordered_row_providers

_AGENT_CACHE_MAX = 512
_BANNER_CACHE_MAX = 128
BannerMarkState = Literal["none", "partial", "all"]


def _bounded_lru_get(cache: "OrderedDict[Any, Any]", key: Any) -> Any:
    """Move *key* to most-recent if present and return its value, else ``None``.

    LRU eviction happens in :func:`_bounded_lru_put`; ``get`` only touches
    ordering when the key already exists.
    """
    value = cache.get(key)
    if value is not None:
        cache.move_to_end(key)
    return value


def _bounded_lru_put(
    cache: "OrderedDict[Any, Any]", key: Any, value: Any, *, maxsize: int
) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > maxsize:
        cache.popitem(last=False)


def _quantize_now(now: datetime | None) -> tuple[int, int, int, int, int, int] | None:
    """Quantize *now* to per-second precision so cache keys are hashable + stable.

    Returns ``None`` when *now* is ``None`` so cache entries built with the
    default clock don't collide with explicit-time renders.
    """
    if now is None:
        return None
    return (now.year, now.month, now.day, now.hour, now.minute, now.second)


def agent_file_change_hint(agent: Agent) -> bool:
    from .file_panel._diff import diff_badge_uses_live_hint

    classified = agent.diff_has_real_edits
    linked = agent.linked_file_change_hint
    if diff_badge_uses_live_hint(agent) and agent.live_file_change_hint is not None:
        # Active primary workspaces are fresh and win over their persisted
        # fallback. Persisted linked-repository commits remain an independent
        # pencil source, matching the separate linked DELTAS groups.
        if agent.live_file_change_hint is True or linked is True:
            return True
        if agent.live_file_change_hint is False or linked is False:
            return False
    if classified is True:
        return True
    if linked is True:
        return True
    if classified is False or linked is False:
        return False
    live = agent.live_file_change_hint
    if live is not None:
        return live
    return bool(agent.diff_path)


def _runtime_signature(
    agent: Agent, now: datetime | None, _seen: set[int] | None = None
) -> tuple[Any, ...]:
    """Return a tuple of agent fields that drive the runtime suffix.

    Runtime-ticking rows fold in quantized *now* so a cache hit only
    happens within the same wall-clock second. Terminal rows have a
    stable signature regardless of *now*.
    """
    if _seen is None:
        _seen = set()
    agent_id = id(agent)
    if agent_id in _seen:
        return ("cycle", agent.identity)
    seen = _seen | {agent_id}

    time_sensitive = row_runtime_or_wait_ticks(agent)
    wait_agent = wait_display_agent(agent)
    child_signature = tuple(
        _runtime_signature(child, now, seen)
        for child in getattr(agent, "runtime_children", ())
    )
    return (
        agent.status,
        agent.start_time,
        agent.run_start_time,
        agent.stop_time,
        tuple(agent.plan_times),
        tuple(agent.feedback_times),
        agent.code_time,
        tuple(agent.questions_times),
        agent.question_response_path,
        agent.runner_slot_yielded,
        child_signature,
        getattr(wait_agent, "wait_until", None),
        getattr(wait_agent, "wait_duration", None),
        tuple(getattr(wait_agent, "waiting_for", ())),
        tuple(getattr(wait_agent, "waiting_for_beads", ())),
        getattr(agent, "retry_next_at_epoch", None),
        agent.retry_count,
        agent.using_fallback,
        agent.fallback_model,
        _quantize_now(now) if time_sensitive else None,
    )


def agent_render_key(
    agent: Agent,
    index: int,
    *,
    is_selected: bool,
    fold_annotation: str,
    is_expanded: bool,
    is_marked: bool,
    fold_restore_marked: bool = False,
    is_unread: bool = False,
    hint_char: str | None = None,
    tribe_label: str | None = None,
    panel_tribe: str | None = None,
    tribe_colors: Mapping[str, str] | None = None,
    now: datetime | None = None,
    tier_styles: tuple[str, ...] = (),
    wait_deps_satisfied: bool | None = None,
    has_missing_wait_target: bool = False,
    has_unresolvable_wait_target: bool = False,
    parallel_family_counts: ParallelFamilyStatusCounts | None = None,
    unread_agent_ids: Collection[tuple[AgentType, str, str | None]] = (),
) -> tuple[Any, ...]:
    """Build the cache key for a single agent row.

    Captures every input that affects ``format_agent_option``'s output,
    plus conservative grouping inputs such as ``agent.tribe``. The key is
    intentionally explicit (no ``vars(agent)``) so adding a new visible
    field is a deliberate edit here rather than a silent cache desync.
    """
    wait_agent = wait_display_agent(agent)
    family_counts = (
        (
            parallel_family_member_counts(agent, unread_agent_ids)
            if unread_agent_ids
            else parallel_family_member_counts(agent)
        )
        if parallel_family_counts is None
        else parallel_family_counts
    )
    semantic_tribes = tuple(
        dict.fromkeys(
            (
                *agent.clan_tribes,
                *((tribe_label,) if tribe_label is not None else ()),
            )
        )
    )
    tribe_color_fingerprint = tuple(
        (
            tribe,
            (
                tribe_colors.get(tribe, TRIBE_IDENTITY_FALLBACK_COLOR)
                if tribe_colors is not None
                else TRIBE_IDENTITY_FALLBACK_COLOR
            ),
        )
        for tribe in semantic_tribes
    )
    return (
        agent.identity,
        index,
        is_selected,
        fold_annotation,
        is_expanded,
        is_marked,
        fold_restore_marked,
        is_unread,
        hint_char,
        tribe_label,
        panel_tribe,
        tribe_color_fingerprint,
        agent.approve,
        agent.auto_approve_plan_action,
        agent.tribe,
        agent.agent_clan,
        agent.agent_clan_generation,
        agent.is_clan_container,
        agent.is_family_container_row,
        agent.tree_parent_key,
        agent.tree_depth,
        agent.clan_tribes,
        agent.agent_name,
        agent.presented_agent_name,
        tuple(wait_agent.waiting_for),
        tuple(wait_agent.waiting_for_beads),
        wait_deps_satisfied,
        has_missing_wait_target,
        has_unresolvable_wait_target,
        wait_agent.wait_runners,
        wait_agent.wait_runners_explicit,
        wait_agent.wait_priority,
        wait_agent.wait_priority_explicit,
        wait_agent.slot_requested_at,
        wait_agent.runner_slots_in_use,
        wait_agent.runner_slot_queue_position,
        wait_agent.runner_slot_queue_size,
        agent_file_change_hint(agent),
        agent.reverted,
        agent_has_confirmed_bead(agent),
        ordered_row_providers(agent),
        family_counts,
        agent.hidden,
        agent.retry_attempt,
        agent.is_workflow_child,
        agent.appears_as_agent,
        agent.is_anonymous,
        agent.step_type,
        agent.embedded_workflow_name,
        agent.is_pre_prompt_step,
        agent.agent_type,
        agent.display_name,
        agent.display_status,
        agent.cl_name,
        tier_styles,
        _runtime_signature(agent, now),
    )


def banner_render_key(
    group: GroupRow,
    agents: list[Agent],
    *,
    width: int,
    sequence: int,
    selectable: bool,
    mode: GroupingMode,
    tier_styles: tuple[str, ...],
    hint_char: str | None,
    mark_state: BannerMarkState = "none",
) -> tuple[Any, ...]:
    """Stable cache key for :func:`format_banner_option`.

    The chip portion of a banner reflects the agent set's status
    distribution, so the key folds in a tuple of ``(identity, status)``
    pairs for that group's agents. ``width`` and ``sequence`` are part
    of the key because they affect the rendered Option directly.
    """
    member_sig = tuple(
        (
            a.identity,
            a.status,
            a.hidden,
            a.is_workflow_child,
            a.is_clan_container,
            a.tree_parent_key,
            a.tree_depth,
            tuple((child.identity, child.status) for child in a.runtime_children),
        )
        for a in agents
    )
    return (
        group.group_key,
        group.level,
        bool(group.is_collapsed),
        bool(group.has_child_groups),
        width,
        sequence,
        selectable,
        mode,
        tier_styles,
        hint_char,
        mark_state,
        member_sig,
    )


class AgentRenderCache:
    """Per-widget LRU cache for agent and banner row rendering.

    Lives on the AgentList instance so each widget owns its own bounded
    cache (separate widgets render independently and a process-wide
    cache would let an idle panel pin entries for an active one).
    """

    def __init__(self) -> None:
        self._agent: OrderedDict[tuple[Any, ...], tuple[Text, Text, str]] = (
            OrderedDict()
        )
        self._banner: OrderedDict[tuple[Any, ...], Option] = OrderedDict()

    def get_agent(self, key: tuple[Any, ...]) -> tuple[Text, Text, str] | None:
        return _bounded_lru_get(self._agent, key)

    def put_agent(self, key: tuple[Any, ...], value: tuple[Text, Text, str]) -> None:
        _bounded_lru_put(self._agent, key, value, maxsize=_AGENT_CACHE_MAX)

    def get_banner(self, key: tuple[Any, ...]) -> Option | None:
        return _bounded_lru_get(self._banner, key)

    def put_banner(self, key: tuple[Any, ...], value: Option) -> None:
        _bounded_lru_put(self._banner, key, value, maxsize=_BANNER_CACHE_MAX)

    def invalidate_agent(self, identity: Any) -> None:
        """Drop every cached entry whose key starts with *identity*.

        Used by ``patch_agent_row`` callers to bust stale renders without
        flushing the whole cache. Keys are tuples whose first element is
        ``agent.identity`` (see :func:`agent_render_key`).
        """
        stale = [k for k in self._agent if k and k[0] == identity]
        for k in stale:
            self._agent.pop(k, None)

    def clear(self) -> None:
        self._agent.clear()
        self._banner.clear()

    def __len__(self) -> int:
        return len(self._agent) + len(self._banner)
