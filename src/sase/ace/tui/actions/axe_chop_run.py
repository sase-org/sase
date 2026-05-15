"""Manual chop-run mixin for the AXE tab.

Wires the ``r`` action on a selected :class:`ChopItem` to the shared backend
runner (:func:`sase.axe.chop_runner.run_configured_chop_once`) so the TUI,
CLI, and scheduler share a single execution path.

The launch path is non-blocking: the actual backend invocation runs in a
worker thread via ``asyncio.to_thread``, so the TUI event loop stays
responsive even while a script chop streams output for many seconds. The
selected chop row is preserved across the launch so the user sees the new
run land at the head of history without losing their place.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from sase.axe.chop_runner import (
    AmbiguousChopError,
    ChopNotFoundError,
    ChopRunOutcome,
    find_configured_chop,
    run_configured_chop_once,
)
from sase.axe.config import load_axe_config

from ..widgets.bgcmd_list import ChopItem

if TYPE_CHECKING:
    from ..widgets.bgcmd_list import AxeItem

TabName = Literal["changespecs", "agents", "axe"]


class AxeChopRunMixin:
    """Mixin providing the manual ``r``-on-chop launch path."""

    current_tab: TabName
    current_idx: int
    _axe_items: list[AxeItem]

    def _run_selected_chop(self) -> None:
        """Manually run the chop currently highlighted on the AXE tab.

        Resolves the selected :class:`ChopItem`, then schedules the launch
        on the asyncio loop so the backend call doesn't block the UI. No-op
        when the selection is not a chop row.
        """
        if self.current_tab != "axe":
            return
        items = self._axe_items
        if not (0 <= self.current_idx < len(items)):
            return
        item = items[self.current_idx]
        if not isinstance(item, ChopItem):
            return
        self._launch_chop_run(item.lumberjack_name, item.chop_name)

    def _launch_chop_run(self, lumberjack_name: str, chop_name: str) -> None:
        """Schedule a manual chop run on the event loop.

        Split from :meth:`_run_selected_chop` so tests can stub the launch
        path without needing a textual app instance, and so the same entry
        point can be reused if a future feature (e.g. command palette)
        wants to run a chop by name.
        """
        self.call_later(  # type: ignore[attr-defined]
            self._launch_chop_run_async, lumberjack_name, chop_name
        )

    async def _launch_chop_run_async(
        self, lumberjack_name: str, chop_name: str
    ) -> None:
        """Resolve config, run the backend in a worker thread, surface outcome."""
        import asyncio

        try:
            config = await asyncio.to_thread(load_axe_config)
        except Exception as e:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to load axe config: {e}", severity="error"
            )
            return

        try:
            match = find_configured_chop(config, chop_name, lumberjack_name)
        except (ChopNotFoundError, AmbiguousChopError) as e:
            self.notify(str(e), severity="error")  # type: ignore[attr-defined]
            return

        chop_cfg = match.chop
        chop_timeout_default = match.lumberjack.chop_timeout

        def _run() -> ChopRunOutcome:
            return run_configured_chop_once(
                lumberjack_name=lumberjack_name,
                chop=chop_cfg,
                axe_config=config,
                chop_timeout_default=chop_timeout_default,
                source="manual",
                started_by="ace",
            )

        self.notify(  # type: ignore[attr-defined]
            f"Running chop '{chop_name}' under '{lumberjack_name}'..."
        )

        try:
            outcome = await asyncio.to_thread(_run)
        except Exception as e:
            self.notify(  # type: ignore[attr-defined]
                f"Failed to launch chop '{chop_name}': {e}", severity="error"
            )
            # Even on failure the runner may have written a partial run
            # entry; refresh so the dashboard reflects current on-disk state.
            self._schedule_axe_async_refresh()  # type: ignore[attr-defined]
            return

        self._notify_chop_outcome(outcome)
        # Always pull fresh state so the new (or updated) run entry shows
        # up in the dashboard and the sidebar status marker repaints.
        self._schedule_axe_async_refresh()  # type: ignore[attr-defined]

    def _notify_chop_outcome(self, outcome: ChopRunOutcome) -> None:
        """Translate a backend outcome into a user-facing notification."""
        chop = outcome.chop_name
        lj = outcome.lumberjack_name
        if outcome.status == "already_running":
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{chop}' is already running under '{lj}'",
                severity="warning",
            )
        elif outcome.status == "success":
            self.notify(f"Chop '{chop}' finished successfully")  # type: ignore[attr-defined]
        elif outcome.status == "failure":
            exit_str = (
                f" (exit {outcome.exit_code})" if outcome.exit_code is not None else ""
            )
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{chop}' failed{exit_str}", severity="error"
            )
        elif outcome.status == "timeout":
            self.notify(f"Chop '{chop}' timed out", severity="error")  # type: ignore[attr-defined]
        elif outcome.status == "missing_script":
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{chop}': script not found", severity="error"
            )
        elif outcome.status == "agent_launched":
            pid = outcome.agent_pid
            suffix = f" (PID {pid})" if pid is not None else ""
            self.notify(f"Agent chop '{chop}' launched{suffix}")  # type: ignore[attr-defined]
        elif outcome.status == "agent_failed":
            self.notify(  # type: ignore[attr-defined]
                f"Agent chop '{chop}' failed to launch", severity="error"
            )
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{chop}': unexpected outcome '{outcome.status}'",
                severity="warning",
            )
