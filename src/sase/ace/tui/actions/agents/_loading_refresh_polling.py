"""Idle-time and marker polling triggers for agent loading refreshes."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

from sase.agent.status_buckets import QUEUED_STATUS

from ._live_watch_coverage import MAX_LIVE_AGENT_WATCHES
from ._loading_state import AgentLoadingStateMixin
from ..event_refresh._constants import _LIVE_FILE_REFRESH_STATUSES
from ...models.agent_family_members import agent_row_is_in_flight
from ...util.pump_tasks import spawn_pump_free_task

_InFlightPollSignature = tuple[int, int] | None
_InFlightPollMarkerState = tuple[_InFlightPollSignature, ...]
_InFlightPollCacheKey = tuple[tuple[Any, str, str | None], str]
_InFlightPollCandidate = tuple[_InFlightPollCacheKey, str, Path]
_InFlightPollResult = tuple[
    _InFlightPollCacheKey,
    str,
    Path,
    _InFlightPollMarkerState,
]
_INFLIGHT_POLL_MARKERS = (
    "agent_meta.json",
    "done.json",
    "waiting.json",
    "retry_state.json",
    "pending_question.json",
)
_WAITING_STATUSES = frozenset({"WAITING", QUEUED_STATUS})
_QUESTION_STATUSES = frozenset({"QUESTION", "WAITING INPUT", "ANSWERED"})

# Seconds of input quiet required before the deferred Tier 2
# full-history reconcile is scheduled in the background. Picked to land
# well outside any j/k burst while still completing before the user
# would typically reach for historic data.
TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S = 30.0
TIER1_INDEX_REVALIDATE_INPUT_QUIET_THRESHOLD_S = 2.0
TIER1_INDEX_REVALIDATE_MIN_INTERVAL_S = 300.0
TIER1_INDEX_REVALIDATE_SOURCE = "tier1_index_revalidate"
STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S = 2.0
STARTUP_PREFIX_COMPLETION_SOURCE = "startup_prefix_completion"
INFLIGHT_POLL_SOURCE = "inflight_poll"


def _marker_signature(path: Path) -> _InFlightPollSignature:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _marker_signatures(artifacts_path: Path) -> _InFlightPollMarkerState:
    return tuple(
        _marker_signature(artifacts_path / marker) for marker in _INFLIGHT_POLL_MARKERS
    )


def _first_observation_needs_refresh(
    status: str,
    marker_state: _InFlightPollMarkerState,
) -> bool:
    """Return whether an already-present marker contradicts the visible row."""
    marker = {
        name: marker_state[i] if i < len(marker_state) else None
        for i, name in enumerate(_INFLIGHT_POLL_MARKERS)
    }
    if marker["done.json"] is not None:
        return True
    if status == "STARTING" and marker["agent_meta.json"] is not None:
        return True
    if status not in _WAITING_STATUSES and marker["waiting.json"] is not None:
        return True
    if status not in _QUESTION_STATUSES and marker["pending_question.json"] is not None:
        return True
    return status != "RETRYING" and marker["retry_state.json"] is not None


def _collect_inflight_poll_results(
    candidates: tuple[_InFlightPollCandidate, ...],
) -> tuple[_InFlightPollResult, ...]:
    results: list[_InFlightPollResult] = []
    for cache_key, status, artifacts_path in candidates:
        try:
            current = _marker_signatures(artifacts_path)
        except OSError:
            continue
        results.append((cache_key, status, artifacts_path, current))
    return tuple(results)


class AgentRefreshPollingMixin(AgentLoadingStateMixin):
    """Methods that trigger refreshes from quiet time and marker polling."""

    def _arm_tier1_index_revalidate_reconcile(
        self,
        load_state: object | None,
        *,
        source: str,
        now_mono: float | None = None,
    ) -> None:
        """Arm the long-cadence revalidating Tier 1 query after cached loads."""
        cur = time.monotonic() if now_mono is None else now_mono
        if source == TIER1_INDEX_REVALIDATE_SOURCE:
            self._agents_index_revalidate_pending = False
            self._agents_index_revalidate_armed_mono = 0.0
            self._agents_index_revalidate_last_mono = cur
            return
        if getattr(load_state, "tier", None) != "tier1":
            return
        if getattr(load_state, "artifact_source", None) != "artifact_index":
            return
        if not getattr(load_state, "used_artifact_index", False):
            return
        if getattr(self, "_agents_index_revalidate_pending", False):
            return
        last = getattr(self, "_agents_index_revalidate_last_mono", 0.0)
        if last > 0.0 and cur - last < TIER1_INDEX_REVALIDATE_MIN_INTERVAL_S:
            return
        self._agents_index_revalidate_pending = True
        self._agents_index_revalidate_armed_mono = cur

    def _maybe_trigger_tier1_index_revalidate_reconcile(
        self, *, now_mono: float | None = None
    ) -> bool:
        """Schedule a coalesced revalidating Tier 1 query once input is quiet."""
        if not getattr(self, "_agents_index_revalidate_pending", False):
            return False
        if self._agents_loading or self._agents_refresh_scheduled:
            return False
        if getattr(self, "_agents_artifact_delta_scheduled", None) is not None:
            return False

        cur = time.monotonic() if now_mono is None else now_mono
        last = getattr(self, "_agents_index_revalidate_last_mono", 0.0)
        if last > 0.0 and cur - last < TIER1_INDEX_REVALIDATE_MIN_INTERVAL_S:
            return False
        last_input = getattr(self, "_last_input_mono", 0.0)
        armed_at = getattr(self, "_agents_index_revalidate_armed_mono", 0.0)
        reference = max(last_input, armed_at)
        if reference <= 0.0:
            return False
        if cur - reference < TIER1_INDEX_REVALIDATE_INPUT_QUIET_THRESHOLD_S:
            return False

        self._agents_index_revalidate_pending = False
        self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
            source=TIER1_INDEX_REVALIDATE_SOURCE,
            revalidate_index=True,
        )
        return True

    def _arm_startup_prefix_completion(
        self,
        load_state: object | None,
        *,
        source: str,
        now_mono: float | None = None,
    ) -> None:
        """Arm the one-shot cached unwindowed prefix completion after first paint."""
        del source
        if load_state is None:
            return
        if not getattr(load_state, "bounded_prefix", False):
            self._agents_prefix_completion_done = True
            self._agents_prefix_completion_pending = False
            return
        if getattr(self, "_agents_prefix_completion_done", False):
            return
        if getattr(self, "_agents_prefix_completion_pending", False):
            return
        if not getattr(load_state, "has_more", False):
            return
        cur = time.monotonic() if now_mono is None else now_mono
        self._agents_prefix_completion_pending = True
        self._agents_prefix_completion_armed_mono = cur

    def _maybe_trigger_startup_prefix_completion(
        self, *, now_mono: float | None = None
    ) -> bool:
        """Schedule the one-shot unwindowed prefix completion once input is quiet."""
        if not getattr(self, "_agents_prefix_completion_pending", False):
            return False
        if getattr(self, "_agents_prefix_completion_done", False):
            self._agents_prefix_completion_pending = False
            return False
        if self._agents_loading or self._agents_refresh_scheduled:
            return False
        if getattr(self, "_agents_artifact_delta_scheduled", None) is not None:
            return False

        cur = time.monotonic() if now_mono is None else now_mono
        last_input = getattr(self, "_last_input_mono", 0.0)
        armed_at = getattr(self, "_agents_prefix_completion_armed_mono", 0.0)
        reference = max(last_input, armed_at)
        if reference <= 0.0:
            return False
        if cur - reference < STARTUP_PREFIX_COMPLETION_INPUT_QUIET_THRESHOLD_S:
            return False

        self._agents_prefix_completion_pending = False
        self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
            source=STARTUP_PREFIX_COMPLETION_SOURCE,
            complete_prefix=True,
        )
        return True

    def _maybe_trigger_input_quiet_tier2_reconcile(
        self, *, now_mono: float | None = None
    ) -> bool:
        """Schedule the deferred Tier 2 reconcile once input has been quiet.

        Returns True iff a refresh was scheduled. The reconcile is the
        single largest startup span (~2.7 s) and is deferred until input
        has been quiet for ``TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S``; the
        quiet window is measured from the later of the last recorded
        input and the moment the pending flag was armed, so users
        who never touch input still get the reconcile in the
        background.
        """
        if not getattr(self, "_agents_history_reconcile_pending", False):
            return False
        if self._agents_loading or self._agents_refresh_scheduled:
            return False
        cur = time.monotonic() if now_mono is None else now_mono
        last_input = getattr(self, "_last_input_mono", 0.0)
        armed_at = getattr(self, "_agents_history_reconcile_armed_mono", 0.0)
        reference = max(last_input, armed_at)
        if reference <= 0.0:
            return False
        if cur - reference < TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S:
            return False
        self._agents_history_reconcile_pending = False
        self._schedule_agents_async_refresh(  # type: ignore[attr-defined]
            source="input_quiet_tier2_reconcile",
            full_history=True,
            full_history_reason="input_quiet_tier2_reconcile",
        )
        return True

    def _poll_starting_agent_transitions(self) -> None:
        """Compatibility wrapper for the broadened in-flight marker poll."""
        self._poll_inflight_agent_transitions()

    def _poll_inflight_agent_transitions(self) -> None:
        """Nudge exact refreshes when in-flight agents' status markers change.

        The inotify watcher is the intended fast path for status markers, but
        it can miss events for newly-created or live artifact directories. This
        poll is a bounded backstop: once per countdown tick it snapshots the
        currently in-flight roster, caps it to the newest live-watch budget, and
        stats only loader-visible marker files off the UI thread. A marker
        appearance, removal, or signature change schedules an exact
        artifact-delta refresh for that agent directory.
        """
        if self._agents_loading or self._agents_refresh_scheduled:
            return
        nav_gate = getattr(self, "_nav_gate", None)
        if nav_gate is not None and nav_gate.is_navigating():
            return
        if getattr(self, "_inflight_poll_scheduled", False):
            return

        candidates = self._inflight_agent_transition_poll_candidates()
        cache = self._inflight_poll_marker_cache
        if not candidates:
            if cache:
                cache.clear()
            return

        self._inflight_poll_scheduled = True
        self._spawn_inflight_agent_transition_poll_task(candidates)

    def _spawn_inflight_agent_transition_poll_task(
        self,
        candidates: tuple[_InFlightPollCandidate, ...],
    ) -> None:
        """Run marker stats outside Textual's serial message pump."""
        task = spawn_pump_free_task(
            self,
            self._run_inflight_agent_transition_poll(candidates),
            name="sase-agents-inflight-marker-poll",
            registry_attr="_pump_free_async_tasks",
        )
        if task is None:
            self._inflight_poll_scheduled = False

    async def _run_inflight_agent_transition_poll(
        self,
        candidates: tuple[_InFlightPollCandidate, ...],
    ) -> None:
        try:
            import asyncio

            results = await asyncio.to_thread(
                _collect_inflight_poll_results,
                candidates,
            )
            live_candidates = self._inflight_agent_transition_poll_candidates()
            live_keys = {cache_key for cache_key, _, _ in live_candidates}
            self._apply_inflight_agent_transition_poll_results(results, live_keys)
        finally:
            self._inflight_poll_scheduled = False

    def _inflight_agent_transition_poll_candidates(
        self,
    ) -> tuple[_InFlightPollCandidate, ...]:
        agents = list(getattr(self, "_agents_with_children", None) or self._agents)
        by_dir: dict[str, tuple[tuple[str, str], _InFlightPollCandidate]] = {}
        for agent in agents:
            if not _poll_agent_status_is_inflight(agent):
                continue
            artifacts_dir = agent.get_artifacts_dir()
            if not artifacts_dir:
                continue
            artifacts_path = Path(artifacts_dir)
            cache_key = (agent.identity, str(artifacts_path.expanduser()))
            candidate: _InFlightPollCandidate = (
                cache_key,
                agent.status,
                artifacts_path,
            )
            by_dir[str(artifacts_path.expanduser())] = (
                _poll_agent_sort_key(agent),
                candidate,
            )

        ordered = [
            candidate
            for _, candidate in sorted(
                by_dir.values(),
                key=lambda item: item[0],
                reverse=True,
            )
        ]
        return tuple(ordered[:MAX_LIVE_AGENT_WATCHES])

    def _apply_inflight_agent_transition_poll_results(
        self,
        results: tuple[_InFlightPollResult, ...],
        live_keys: set[_InFlightPollCacheKey],
    ) -> None:
        cache = self._inflight_poll_marker_cache
        dirty_artifact_dirs: list[Path] = []
        seen_dirty_dirs: set[str] = set()

        for cache_key, status, artifacts_path, current in results:
            if cache_key not in live_keys:
                continue
            had_entry = cache_key in cache
            previous = cache[cache_key] if had_entry else None
            cache[cache_key] = current
            if not had_entry:
                dirty = _first_observation_needs_refresh(status, current)
            else:
                dirty = previous is not None and current != previous
            if dirty:
                key = str(artifacts_path.expanduser())
                if key not in seen_dirty_dirs:
                    seen_dirty_dirs.add(key)
                    dirty_artifact_dirs.append(artifacts_path)

        stale = [cache_key for cache_key in cache if cache_key not in live_keys]
        for cache_key in stale:
            cache.pop(cache_key, None)

        if dirty_artifact_dirs:
            self._schedule_agent_artifact_delta_refresh(  # type: ignore[attr-defined]
                dirty_artifact_dirs,
                source=INFLIGHT_POLL_SOURCE,
            )


def _poll_agent_status_is_inflight(agent: Any) -> bool:
    try:
        if agent_row_is_in_flight(agent):
            return True
    except AttributeError:
        pass
    if getattr(agent, "stop_time", None) is not None:
        return False
    if getattr(agent, "status", None) == "STARTING":
        return True
    return getattr(agent, "status", None) in _LIVE_FILE_REFRESH_STATUSES


def _poll_agent_sort_key(agent: Any) -> tuple[str, str]:
    start = getattr(agent, "start_time", None)
    start_key = start.strftime("%Y%m%d%H%M%S") if start is not None else ""
    return (start_key, getattr(agent, "raw_suffix", None) or "")
