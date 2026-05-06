"""LRU caches and cache-key builders for agent-list row rendering.

The caches live on the AgentList widget instance (one per widget); the
key builders capture every input that affects the rendered Option so
that a cache hit only happens when the visible output would be
byte-identical to the prior render.
"""

from collections import OrderedDict
from datetime import datetime
from typing import Any

from rich.text import Text
from textual.widgets.option_list import Option

from ..models.agent import Agent
from ..models.agent_bead import derive_agent_bead_id
from ..models.agent_groups import GroupingMode, GroupRow

_AGENT_CACHE_MAX = 512
_BANNER_CACHE_MAX = 128


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


def _runtime_signature(agent: Agent, now: datetime | None) -> tuple[Any, ...]:
    """Return a tuple of agent fields that drive the runtime suffix.

    ``RUNNING`` / ``WAITING`` / ``RETRYING`` agents have a status display
    that depends on time-of-day; their signature folds in the quantized
    *now* so a cache hit only happens within the same wall-clock second.
    Terminal agents have a stable signature regardless of *now*.
    """
    time_sensitive = agent.status in ("RUNNING", "WAITING", "RETRYING")
    return (
        agent.status,
        agent.start_time,
        getattr(agent, "wait_until", None),
        getattr(agent, "wait_duration", None),
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
    hint_char: str | None,
    now: datetime | None,
    tier_styles: tuple[str, ...] = (),
) -> tuple[Any, ...]:
    """Build the cache key for a single agent row.

    Captures every input that affects ``format_agent_option``'s output —
    if any of these values changes, the cached entry is no longer valid
    and the row must be re-rendered. The key is intentionally explicit
    (no ``vars(agent)``) so adding a new visible field is a deliberate
    edit here rather than a silent cache desync.
    """
    return (
        agent.identity,
        index,
        is_selected,
        fold_annotation,
        is_expanded,
        is_marked,
        hint_char,
        agent.approve,
        agent.auto_approve_plan_action,
        agent.tag,
        agent.agent_name,
        derive_agent_bead_id(agent),
        agent.hidden,
        agent.retry_attempt,
        agent.is_workflow_child,
        agent.appears_as_agent,
        agent.is_anonymous,
        agent.step_index,
        agent.total_steps,
        agent.parent_step_index,
        agent.parent_total_steps,
        agent.step_type,
        agent.embedded_workflow_name,
        agent.is_pre_prompt_step,
        agent.agent_type,
        agent.display_name,
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
) -> tuple[Any, ...]:
    """Stable cache key for :func:`format_banner_option`.

    The chip portion of a banner reflects the agent set's status
    distribution, so the key folds in a tuple of ``(identity, status)``
    pairs for that group's agents. ``width`` and ``sequence`` are part
    of the key because they affect the rendered Option directly.
    """
    member_sig = tuple(
        (a.identity, a.status, a.hidden, a.is_workflow_child) for a in agents
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
