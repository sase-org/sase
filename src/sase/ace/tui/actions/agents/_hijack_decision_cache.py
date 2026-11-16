"""Per-selection Agent Hijack decision cache computed off the UI thread."""

from __future__ import annotations

import asyncio
import logging
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from time import monotonic
from typing import TYPE_CHECKING, Any

from ...util.pump_tasks import spawn_pump_free_task
from ._hijack_decision import (
    HijackDecisionView,
    cheap_hijack_ingress_available,
    compute_hijack_decision,
    hijack_decision_fingerprint,
    row_identity,
)
from ._roster_generation import get_roster_generation

if TYPE_CHECKING:
    from sase.agent.hijack._stop_models import StopDeps

    from ...models import Agent

log = logging.getLogger(__name__)

_HIJACK_DECISION_CACHE_MAX = 64
_HIJACK_DECISION_MAX_AGE_S = 30.0
_HIJACK_EXPLICIT_QUEUE_MAX = 8
_Then = Callable[[HijackDecisionView], None]


@dataclass
class _HijackDecisionRequest:
    """One scheduled compute, captured on the UI thread."""

    agent: Agent
    key: tuple[Any, ...]
    deps: StopDeps
    callbacks: list[_Then] = field(default_factory=list)
    explicit: bool = False


class AgentHijackDecisionCacheMixin:
    """Cache ``resolve_and_decide`` results keyed by row identity and fingerprint."""

    _hijack_decision_cache: OrderedDict[tuple[Any, ...], HijackDecisionView]
    _hijack_decision_inflight: dict[tuple[Any, ...], list[_Then]]
    _hijack_decision_pool: ThreadPoolExecutor | None
    _hijack_decision_busy: bool
    _hijack_decision_waiting_passive: _HijackDecisionRequest | None
    _hijack_decision_waiting_explicit: list[_HijackDecisionRequest]

    def _hijack_decision_cache_store(
        self,
    ) -> OrderedDict[tuple[Any, ...], HijackDecisionView]:
        cache = getattr(self, "_hijack_decision_cache", None)
        if cache is None:
            cache = OrderedDict()
            self._hijack_decision_cache = cache
        return cache

    def _hijack_decision_key(self, agent: Agent) -> tuple[Any, ...] | None:
        identity = row_identity(agent)
        return (identity, hijack_decision_fingerprint(agent))

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

    def _hijack_decision_is_fresh(self, view: HijackDecisionView) -> bool:
        computed_at = view.computed_at
        if computed_at <= 0:
            return True
        return (monotonic() - computed_at) <= _HIJACK_DECISION_MAX_AGE_S

    def _store_hijack_decision(
        self, agent: Agent, view: HijackDecisionView
    ) -> HijackDecisionView:
        key = self._hijack_decision_key(agent)
        if key is None:
            return view
        return self._store_hijack_decision_for_key(key, view)

    def _store_hijack_decision_for_key(
        self, key: tuple[Any, ...], view: HijackDecisionView
    ) -> HijackDecisionView:
        cache = self._hijack_decision_cache_store()
        stored = HijackDecisionView(
            identity=view.identity,
            roster_generation=view.roster_generation,
            occupant_name=view.occupant_name,
            occupant_reason=view.occupant_reason,
            workspace_num=view.workspace_num,
            decision=view.decision,
            computed_at=view.computed_at if view.computed_at > 0 else monotonic(),
        )
        cache[key] = stored
        cache.move_to_end(key)
        while len(cache) > _HIJACK_DECISION_CACHE_MAX:
            cache.popitem(last=False)
        return stored

    def _hijack_decision_executor(self) -> ThreadPoolExecutor:
        pool = getattr(self, "_hijack_decision_pool", None)
        if pool is None:
            pool = ThreadPoolExecutor(
                max_workers=1,
                thread_name_prefix="sase-hijack-decision",
            )
            self._hijack_decision_pool = pool
        return pool

    def _shutdown_hijack_decision_executor(self) -> None:
        """Cancel queued hijack computes and detach the dedicated worker."""
        self._hijack_decision_waiting_passive = None
        self._hijack_decision_waiting_explicit = []
        inflight = getattr(self, "_hijack_decision_inflight", None)
        if isinstance(inflight, dict):
            inflight.clear()
        self._hijack_decision_busy = False
        pool = getattr(self, "_hijack_decision_pool", None)
        self._hijack_decision_pool = None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)

    def _compute_hijack_decision_sync(
        self, agent: Agent, deps: StopDeps | None = None
    ) -> HijackDecisionView:
        """Compute one decision on a worker thread or a loop-less test double."""
        override = getattr(self, "_hijack_decision_compute", None)
        if callable(override):
            return override(agent, deps)
        return compute_hijack_decision(
            agent,
            roster_generation=get_roster_generation(self),
            deps=deps,
        )

    def _schedule_hijack_decision(
        self,
        agent: Agent | None,
        then: _Then | None = None,
    ) -> None:
        """Compute the selected row's decision on the dedicated worker.

        Passive requests (no ``then``) run only when the cheap ingress check
        passes and the Agents tab is visible. At most one compute runs and one
        passive request waits; a newer passive request replaces the waiting
        one. Explicit requests keep their callbacks and go ahead of passive
        ones. A matching in-flight key coalesces callbacks.
        """
        if agent is None:
            return
        key = self._hijack_decision_key(agent)
        if key is None:
            return
        explicit = then is not None
        if not explicit:
            if not cheap_hijack_ingress_available(agent):
                return
            if not self._hijack_footer_refresh_allowed():
                return
        cached = self._cached_hijack_decision(agent)
        fresh = cached is not None and self._hijack_decision_is_fresh(cached)
        if cached is not None:
            if then is not None:
                then(cached)
                then = None
            if fresh:
                return
        inflight = self._hijack_decision_inflight_store()
        pending = inflight.get(key)
        if pending is not None:
            if then is not None:
                pending.append(then)
            return
        from ._hijack_roster_snapshot import hijack_row_local_deps

        deps = hijack_row_local_deps(self, agent)
        request = _HijackDecisionRequest(
            agent=agent,
            key=key,
            deps=deps,
            callbacks=[] if then is None else [then],
            explicit=explicit,
        )
        if getattr(self, "_hijack_decision_busy", False):
            self._enqueue_hijack_decision_request(request)
            return
        self._start_hijack_decision_request(request)

    def _hijack_decision_inflight_store(self) -> dict[tuple[Any, ...], list[_Then]]:
        inflight = getattr(self, "_hijack_decision_inflight", None)
        if inflight is None:
            inflight = {}
            self._hijack_decision_inflight = inflight
        return inflight

    def _enqueue_hijack_decision_request(self, request: _HijackDecisionRequest) -> None:
        waiting_passive = getattr(self, "_hijack_decision_waiting_passive", None)
        if (
            isinstance(waiting_passive, _HijackDecisionRequest)
            and waiting_passive.key == request.key
        ):
            waiting_passive.callbacks.extend(request.callbacks)
            if request.explicit:
                waiting_passive.explicit = True
            return
        waiting_explicit = getattr(self, "_hijack_decision_waiting_explicit", None)
        if waiting_explicit is None:
            waiting_explicit = []
            self._hijack_decision_waiting_explicit = waiting_explicit
        for queued in waiting_explicit:
            if queued.key == request.key:
                queued.callbacks.extend(request.callbacks)
                if request.explicit:
                    queued.explicit = True
                return
        if request.explicit:
            waiting_explicit.append(request)
            overflow = len(waiting_explicit) - _HIJACK_EXPLICIT_QUEUE_MAX
            if overflow > 0:
                del waiting_explicit[:overflow]
            return
        self._hijack_decision_waiting_passive = request

    def _start_hijack_decision_request(self, request: _HijackDecisionRequest) -> None:
        inflight = self._hijack_decision_inflight_store()
        inflight[request.key] = list(request.callbacks)
        self._hijack_decision_busy = True

        async def _run() -> None:
            view: HijackDecisionView | None = None
            try:
                loop = asyncio.get_running_loop()
                view = await loop.run_in_executor(
                    self._hijack_decision_executor(),
                    self._compute_hijack_decision_sync,
                    request.agent,
                    request.deps,
                )
            except Exception:
                log.debug("background hijack decision failed", exc_info=True)
            if view is None:
                inflight.pop(request.key, None)
                self._hijack_decision_busy = False
                self._dispatch_next_hijack_decision()
                return
            self._finish_hijack_decision(request.agent, request.key, view)

        task = spawn_pump_free_task(
            self,
            _run(),
            name="sase-hijack-decision",
            registry_attr="_hijack_decision_tasks",
        )
        if task is None:
            view = self._compute_hijack_decision_sync(request.agent, request.deps)
            self._finish_hijack_decision(request.agent, request.key, view)

    def _dispatch_next_hijack_decision(self) -> None:
        if getattr(self, "_hijack_decision_busy", False):
            return
        waiting_explicit = getattr(self, "_hijack_decision_waiting_explicit", None)
        if waiting_explicit:
            request = waiting_explicit.pop(0)
            if self._start_or_skip_hijack_decision_request(request):
                return
        waiting_passive = getattr(self, "_hijack_decision_waiting_passive", None)
        self._hijack_decision_waiting_passive = None
        if isinstance(waiting_passive, _HijackDecisionRequest):
            self._start_or_skip_hijack_decision_request(waiting_passive)

    def _start_or_skip_hijack_decision_request(
        self, request: _HijackDecisionRequest
    ) -> bool:
        cached = self._cached_hijack_decision(request.agent)
        if (
            cached is not None
            and self._hijack_decision_is_fresh(cached)
            and self._hijack_decision_key(request.agent) == request.key
        ):
            for callback in request.callbacks:
                callback(cached)
            self._dispatch_next_hijack_decision()
            return True
        inflight = self._hijack_decision_inflight_store()
        pending = inflight.get(request.key)
        if pending is not None:
            pending.extend(request.callbacks)
            return True
        self._start_hijack_decision_request(request)
        return True

    def _finish_hijack_decision(
        self,
        agent: Agent,
        key: tuple[Any, ...],
        view: HijackDecisionView,
    ) -> None:
        inflight = getattr(self, "_hijack_decision_inflight", None)
        callbacks = list(inflight.pop(key, ()) if isinstance(inflight, dict) else ())
        stored = self._store_hijack_decision_for_key(key, view)
        self._hijack_decision_busy = False
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
        self._dispatch_next_hijack_decision()

    def _hijack_footer_refresh_allowed(self) -> bool:
        """Skip chip refresh while a modal owns the screen or Agents is hidden."""
        if getattr(self, "current_tab", None) != "agents":
            return False
        stack = getattr(self, "screen_stack", None)
        if stack is not None and len(stack) > 1:
            return False
        return True


__all__ = ["AgentHijackDecisionCacheMixin"]
