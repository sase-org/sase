"""Idle-time and marker polling triggers for agent loading refreshes."""

from __future__ import annotations

import os
import time
from pathlib import Path

from ._loading_state import AgentLoadingStateMixin

_StartingPollSignature = tuple[int, int] | None
_StartingPollMarkerState = tuple[_StartingPollSignature, _StartingPollSignature]

# Seconds of input quiet required before the deferred Tier 2
# full-history reconcile is scheduled in the background. Picked to land
# well outside any j/k burst while still completing before the user
# would typically reach for historic data.
TIER2_RECONCILE_INPUT_QUIET_THRESHOLD_S = 30.0
TIER1_INDEX_REVALIDATE_INPUT_QUIET_THRESHOLD_S = 2.0
TIER1_INDEX_REVALIDATE_MIN_INTERVAL_S = 300.0
TIER1_INDEX_REVALIDATE_SOURCE = "tier1_index_revalidate"


def _marker_signature(path: Path) -> _StartingPollSignature:
    try:
        st = os.stat(path)
    except FileNotFoundError:
        return None
    return (st.st_mtime_ns, st.st_size)


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
        """Nudge a refresh when a STARTING agent's markers land on disk.

        The inotify watcher is the intended fast path for the
        STARTING→RUNNING/WAITING transition, but it races the creation of
        the per-agent ``artifacts/<workflow>/<timestamp>/`` subtree and is
        unavailable on some platforms. This poll runs once per countdown
        tick (cheap; one ``stat`` per marker per STARTING agent) and
        bounds the worst-case visible time-to-row to ~1 s in that window.

        No-op when no STARTING agent is present, which is the steady
        state. The cache is keyed by ``agent.identity`` and shrinks back
        to empty once all STARTING agents have transitioned.
        """
        panel_index = self._agent_panel_index()  # type: ignore[attr-defined]
        starting_indices = panel_index.hidden_starting_indices
        cache = self._starting_poll_meta_cache
        if not starting_indices:
            if cache:
                cache.clear()
            return

        live_identities: set[tuple] = set()  # type: ignore[type-arg]
        dirty_artifact_dirs: list[Path] = []
        for i in starting_indices:
            agent = self._agents[i]
            identity = agent.identity
            live_identities.add(identity)
            artifacts_dir = agent.get_artifacts_dir()
            if not artifacts_dir:
                continue
            artifacts_path = Path(artifacts_dir)
            meta_path = artifacts_path / "agent_meta.json"
            waiting_path = artifacts_path / "waiting.json"
            try:
                current: _StartingPollMarkerState = (
                    _marker_signature(meta_path),
                    _marker_signature(waiting_path),
                )
            except OSError:
                continue
            had_entry = identity in cache
            previous = cache[identity] if had_entry else None
            cache[identity] = current
            if not had_entry:
                # First observation — record the baseline; only nudge if
                # either marker already exists, since that means the
                # watcher likely missed the CREATE event and the agent has
                # already written a loader-visible marker.
                if current != (None, None):
                    dirty_artifact_dirs.append(artifacts_path)
                continue
            if previous is not None and current != previous:
                # Marker appearance, removal, or update — watcher likely
                # missed a loader-visible event.
                dirty_artifact_dirs.append(artifacts_path)

        # Eviction: drop identities no longer STARTING.
        stale = [identity for identity in cache if identity not in live_identities]
        for identity in stale:
            cache.pop(identity, None)

        if dirty_artifact_dirs:
            self._schedule_agent_artifact_delta_refresh(  # type: ignore[attr-defined]
                dirty_artifact_dirs,
                source="starting_poll",
            )
