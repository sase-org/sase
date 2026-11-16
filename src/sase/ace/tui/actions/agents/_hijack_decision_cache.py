"""Per-selection Agent Hijack decision cache computed off the UI thread."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ...util.pump_tasks import spawn_pump_free_task
from ._hijack_decision import HijackDecisionView, compute_hijack_decision
from ._roster_generation import get_roster_generation

if TYPE_CHECKING:
    from ...models import Agent

log = logging.getLogger(__name__)

_HIJACK_DECISION_CACHE_MAX = 64
_Then = Callable[[HijackDecisionView], None]


class AgentHijackDecisionCacheMixin:
    """Cache ``resolve_and_decide`` results keyed by row identity and roster."""

    _hijack_decision_cache: OrderedDict[tuple[Any, ...], HijackDecisionView]
    _hijack_decision_inflight: dict[tuple[Any, ...], list[_Then]]

    def _hijack_decision_cache_store(
        self,
    ) -> OrderedDict[tuple[Any, ...], HijackDecisionView]:
        cache = getattr(self, "_hijack_decision_cache", None)
        if cache is None:
            cache = OrderedDict()
            self._hijack_decision_cache = cache
        return cache

    def _hijack_decision_key(self, agent: Agent) -> tuple[Any, ...] | None:
        identity = getattr(agent, "identity", None)
        if not isinstance(identity, tuple):
            return None
        return (identity, get_roster_generation(self))

    def _cached_hijack_decision(self, agent: Agent | None) -> HijackDecisionView | None:
        """Probe the decision cache without touching the filesystem."""
        if agent is None:
            return None
        key = self._hijack_decision_key(agent)
        if key is None:
            return None
        cache = getattr(self, "_hijack_decision_cache", None)
        if not cache:
            return None
        view = cache.get(key)
        if view is None:
            return None
        cache.move_to_end(key)
        return view

    def _store_hijack_decision(
        self, agent: Agent, view: HijackDecisionView
    ) -> HijackDecisionView:
        cache = self._hijack_decision_cache_store()
        key = self._hijack_decision_key(agent)
        if key is None:
            return view
        generation = key[1] if isinstance(key[1], int) else view.roster_generation
        stored = HijackDecisionView(
            identity=view.identity,
            roster_generation=generation,
            occupant_name=view.occupant_name,
            occupant_reason=view.occupant_reason,
            workspace_num=view.workspace_num,
            decision=view.decision,
        )
        cache[key] = stored
        cache.move_to_end(key)
        while len(cache) > _HIJACK_DECISION_CACHE_MAX:
            cache.popitem(last=False)
        return stored

    def _compute_hijack_decision_sync(self, agent: Agent) -> HijackDecisionView:
        """Compute one decision on a worker thread or a loop-less test double."""
        return compute_hijack_decision(
            agent, roster_generation=get_roster_generation(self)
        )

    def _schedule_hijack_decision(
        self,
        agent: Agent | None,
        then: _Then | None = None,
    ) -> None:
        """Compute the selected row's decision off the UI thread.

        No-op when a matching compute is already in flight. ``then`` runs on
        the event loop after the result is stored, and only if the roster
        generation still matches.
        """
        if agent is None:
            return
        key = self._hijack_decision_key(agent)
        if key is None:
            return
        cached = self._cached_hijack_decision(agent)
        if cached is not None:
            if then is not None:
                then(cached)
            return
        inflight = getattr(self, "_hijack_decision_inflight", None)
        if inflight is None:
            inflight = {}
            self._hijack_decision_inflight = inflight
        pending = inflight.get(key)
        if pending is not None:
            if then is not None:
                pending.append(then)
            return
        callbacks: list[_Then] = [] if then is None else [then]
        inflight[key] = callbacks

        async def _run() -> None:
            try:
                view = await asyncio.to_thread(
                    self._compute_hijack_decision_sync, agent
                )
            except Exception:
                log.debug("background hijack decision failed", exc_info=True)
                inflight.pop(key, None)
                return
            self._finish_hijack_decision(agent, key, view)

        task = spawn_pump_free_task(
            self,
            _run(),
            name="sase-hijack-decision",
            registry_attr="_hijack_decision_tasks",
        )
        if task is None:
            view = self._compute_hijack_decision_sync(agent)
            self._finish_hijack_decision(agent, key, view)

    def _finish_hijack_decision(
        self,
        agent: Agent,
        key: tuple[Any, ...],
        view: HijackDecisionView,
    ) -> None:
        inflight = getattr(self, "_hijack_decision_inflight", None)
        callbacks = list(inflight.pop(key, ()) if isinstance(inflight, dict) else ())
        current_key = self._hijack_decision_key(agent)
        if current_key != key:
            return
        stored = self._store_hijack_decision(agent, view)
        getter = getattr(self, "_get_selected_agent", None)
        selected = getter() if callable(getter) else None
        selected_identity = getattr(selected, "identity", None)
        if (
            selected_identity == stored.identity
            and self._hijack_footer_refresh_allowed()
        ):
            refresh = getattr(self, "_refresh_agent_footer_bindings_only", None)
            if callable(refresh):
                refresh()
        for callback in callbacks:
            callback(stored)

    def _hijack_footer_refresh_allowed(self) -> bool:
        """Skip chip refresh while a modal owns the screen or Agents is hidden."""
        if getattr(self, "current_tab", None) != "agents":
            return False
        stack = getattr(self, "screen_stack", None)
        if stack is not None and len(stack) > 1:
            return False
        return True


__all__ = ["AgentHijackDecisionCacheMixin"]
