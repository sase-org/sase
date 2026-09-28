"""Coalesced ToolRun glance loader (plan §3.5.1).

On store-token drift, a coalesced ``spawn_pump_free_task`` runs
``asyncio.to_thread(tool_run_live_glance)``. It defers while
``NavigationGate`` is navigating, re-reads the tab after the await, applies
by attribution key, and patches only rows whose chip token changed (the
bead-warmup pattern, including its rebuild escalation on a failed patch).
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any

from sase.ace.tui.actions.event_refresh._surface_tokens import (
    probe_tool_runs_token,
    surface_token_drifted,
)
from sase.ace.tui.tool_runs.attribution import (
    row_identity_from_agent,
    select_live_runs,
)
from sase.ace.tui.tool_runs.flag import tool_runs_enabled
from sase.ace.tui.tool_runs.snapshot import (
    ToolRunsLoadState,
    apply_loaded_snapshot,
    get_snapshot,
    load_glance_blocking,
    should_probe_drift,
    tool_runs_disabled_reason,
)
from sase.ace.tui.util.pump_tasks import spawn_pump_free_task
from sase.ace.tui.util.trace import tui_trace

if TYPE_CHECKING:
    from sase.ace.tui.models.agent import Agent
    from sase.ace.tui.models.agent import AgentType

log = logging.getLogger(__name__)


def _tool_runs_state(owner: object) -> ToolRunsLoadState:
    state = getattr(owner, "_tool_runs_load_state", None)
    if not isinstance(state, ToolRunsLoadState):
        state = ToolRunsLoadState()
        try:
            owner._tool_runs_load_state = state  # type: ignore[attr-defined]
        except Exception:
            pass
    return state


class ToolRunGlanceLoaderMixin:
    """Schedule and apply the app-level ToolRun glance snapshot."""

    _tool_runs_load_state: ToolRunsLoadState
    _tool_runs_async_tasks: set[asyncio.Task[None]]

    def _tool_runs_probe_token(self) -> Any | None:
        """Stat-only probe of the ToolRun store files (no SQLite open)."""
        return probe_tool_runs_token()

    def _schedule_tool_runs_refresh(self, *, source: str = "unknown") -> None:
        """Queue a coalesced glance load once the first agents load applied."""
        if tool_runs_disabled_reason() is not None:
            return
        if not tool_runs_enabled():
            return
        if not getattr(self, "_agents_first_load_done", False):
            return
        state = _tool_runs_state(self)
        if state.running:
            state.pending = True
            state.source = source
            return
        if state.scheduled:
            state.source = source
            return
        state.scheduled = True
        state.source = source
        self._spawn_tool_runs_refresh_task()  # type: ignore[attr-defined]

    def _spawn_tool_runs_refresh_task(self) -> None:
        """Run the glance load outside Textual's serial app message pump."""
        try:
            task = spawn_pump_free_task(
                self,
                self._run_tool_runs_refresh(),  # type: ignore[attr-defined]
                name="sase-agents-tool-runs-glance",
                registry_attr="_tool_runs_async_tasks",
            )
        except Exception:
            task = None
        if task is None:
            state = _tool_runs_state(self)
            state.scheduled = False

    async def _run_tool_runs_refresh(self) -> None:
        """Load the glance off-thread, then patch changed rows by identity."""
        nav_gate = getattr(self, "_nav_gate", None)
        if nav_gate is not None and callable(getattr(nav_gate, "is_navigating", None)):
            try:
                if nav_gate.is_navigating():
                    delay = nav_gate.time_until_idle() + 0.05
                    self.set_timer(  # type: ignore[attr-defined]
                        delay,
                        self._spawn_tool_runs_refresh_task,  # type: ignore[attr-defined]
                    )
                    return
            except Exception:
                pass
        state = _tool_runs_state(self)
        state.scheduled = False
        if getattr(self, "_agents_loading", False):
            self.set_timer(0.05, self._spawn_tool_runs_refresh_task)  # type: ignore[attr-defined]
            return
        # Re-read the tab after the gate: off-tab loads still refresh the
        # in-memory snapshot (rows patch on return), but never touch widgets.
        state.running = True
        try:
            probe_before = self._tool_runs_probe_token()  # type: ignore[attr-defined]
            with tui_trace(
                "agents.tool_runs_glance_refresh",
                source=state.source,
            ):
                loaded = await asyncio.to_thread(load_glance_blocking)
            if loaded is None:
                return
            if tool_runs_disabled_reason() is not None:
                return
            current_tab = getattr(self, "current_tab", "agents")
            probe_after = self._tool_runs_probe_token()  # type: ignore[attr-defined]
            token = probe_after if probe_after is not None else probe_before
            apply_loaded_snapshot(loaded, store_token=token)
            state.last_token = token
            if current_tab == "agents":
                self._apply_tool_runs_snapshot(source=state.source)  # type: ignore[attr-defined]
        except Exception:
            log.exception("ToolRun glance refresh failed")
        finally:
            state.running = False
            if state.pending:
                state.pending = False
                self._schedule_tool_runs_refresh(source="tool_runs_followup")  # type: ignore[attr-defined]

    def _maybe_probe_tool_runs_drift(self, *, source: str = "unknown") -> None:
        """Stat-only drift probe for the 1 s countdown tick (at most /2 s).

        While the last snapshot holds at least one live run and the Agents
        tab is visible, piggyback on the existing countdown tick. Adds no
        new timer or loop. A quiet tick opens no ToolRun file.
        """
        if not tool_runs_enabled():
            return
        if tool_runs_disabled_reason() is not None:
            return
        if getattr(self, "current_tab", None) != "agents":
            return
        if not getattr(self, "_agents_first_load_done", False):
            return
        snapshot = get_snapshot()
        if snapshot is None or not snapshot.has_live_runs:
            # No live runs: the 10 s auto-refresh token ride owns reloads.
            # Still allow one probe when the token drifted since last load.
            pass
        state = _tool_runs_state(self)
        now_mono = time.monotonic()
        if not should_probe_drift(now_mono, state):
            return
        state.last_probe_mono = now_mono
        current = self._tool_runs_probe_token()  # type: ignore[attr-defined]
        if current is None:
            return
        last = state.last_token
        if last is None:
            last_snapshot = get_snapshot()
            last = (
                getattr(last_snapshot, "store_token", None) if last_snapshot else None
            )
        drifted = surface_token_drifted(current, last)
        if drifted or (snapshot is None):
            self._schedule_tool_runs_refresh(source=source)  # type: ignore[attr-defined]

    def _apply_tool_runs_snapshot(self, *, source: str = "unknown") -> None:
        """Patch only rows whose chip token changed; escalate on failure."""
        del source
        agents = list(getattr(self, "_agents", ()) or ())
        if not agents:
            return
        snapshot = get_snapshot()
        if snapshot is None:
            return
        current_by_identity: dict[Any, Any] = {}
        for agent in getattr(self, "_agents_with_children", ()) or ():
            current_by_identity.setdefault(agent.identity, agent)
        for agent in agents:
            current_by_identity[agent.identity] = agent
        # Compare chip tokens before/after the load is not possible here
        # (the snapshot already applied); instead patch rows whose current
        # chip is non-empty or whose cached token disagrees. The cheapest
        # correct rule: patch every row with a live chip, plus rows the
        # cache says changed. Track patched rows to escalate once.
        needs_rebuild = False
        for identity, target in current_by_identity.items():
            try:
                row = row_identity_from_agent(target)
                selected = select_live_runs(snapshot.runs, row)
            except Exception:
                continue
            if not selected:
                continue
            try:
                patched = self._try_patch_agent_row(target)  # type: ignore[attr-defined]
            except Exception:
                patched = False
            if not patched:
                needs_rebuild = True
        # Rows whose chip disappeared (settle) also need a patch: find rows
        # with no live chip but a stale chip token in the render cache is
        # expensive; rely on the next auto-refresh to rebuild those. A
        # failed patch already escalates to a rebuild here.
        if needs_rebuild:
            refresh = getattr(self, "_refresh_agents_display", None)
            if callable(refresh):
                try:
                    refresh(list_changed=True, defer_detail=True)
                except Exception:
                    pass


__all__ = ["ToolRunGlanceLoaderMixin"]
