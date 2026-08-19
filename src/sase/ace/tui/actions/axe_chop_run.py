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

import os
import subprocess
from typing import TYPE_CHECKING, Literal

from sase.axe.chop_runner import (
    AmbiguousChopError,
    ChopNotFoundError,
    ChopRunOutcome,
    find_configured_chop,
    run_configured_chop_once,
)
from sase.axe.config import load_axe_config
from sase.axe.state import chop_run_log_path

from ..util.pump_tasks import spawn_pump_free_task
from ..widgets.bgcmd_list import ChopItem
from .failure_messages import notify_registered_error

if TYPE_CHECKING:
    from .axe_display import ChopSnapshot
    from ..widgets.bgcmd_list import AxeItem

TabName = Literal["artifacts", "agents", "axe"]


class AxeChopRunMixin:
    """Mixin providing the manual ``r``-on-chop launch path."""

    current_tab: TabName
    current_idx: int
    _axe_items: list[AxeItem]
    _axe_chop_snapshots: dict[tuple[str, str], ChopSnapshot]

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
        snapshot = getattr(self, "_axe_chop_snapshots", {}).get(
            (item.lumberjack_name, item.chop_name)
        )
        if snapshot is not None and not snapshot.enabled:
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{item.chop_name}' is disabled; edit its config to enable it",
                severity="warning",
            )
            return
        self._launch_chop_run(item.lumberjack_name, item.chop_name)

    def _launch_chop_run(self, lumberjack_name: str, chop_name: str) -> None:
        """Schedule a manual chop run on the event loop.

        Split from :meth:`_run_selected_chop` so tests can stub the launch
        path without needing a textual app instance, and so the same entry
        point can be reused if a future feature (e.g. command palette)
        wants to run a chop by name.
        """
        spawn_pump_free_task(
            self,
            self._launch_chop_run_async(lumberjack_name, chop_name),
            name="sase-axe-chop-run",
            registry_attr="_pump_free_async_tasks",
        )

    def _open_selected_chop_output(self) -> None:
        """Open the selected chop run's persisted output log in ``$EDITOR``."""
        if self.current_tab != "axe":
            return

        self._derive_axe_view_from_selection()  # type: ignore[attr-defined]
        items = self._axe_items
        if not (0 <= self.current_idx < len(items)):
            self.notify(  # type: ignore[attr-defined]
                "No chop selected", severity="warning"
            )
            return

        item = items[self.current_idx]
        if not isinstance(item, ChopItem):
            self.notify(  # type: ignore[attr-defined]
                "No chop output selected", severity="warning"
            )
            return

        chop_key = (item.lumberjack_name, item.chop_name)
        snap = self._axe_chop_snapshots.get(chop_key)
        if snap is None or not snap.runs:
            self.notify(  # type: ignore[attr-defined]
                f"No runs recorded for chop '{item.chop_name}'",
                severity="warning",
            )
            return

        run_offset = self._axe_resolve_chop_run_offset(  # type: ignore[attr-defined]
            chop_key
        )
        run = snap.runs[run_offset].entry
        log_path = chop_run_log_path(item.lumberjack_name, item.chop_name, run.run_id)
        if not log_path.exists():
            self.notify(  # type: ignore[attr-defined]
                f"No output log found for chop '{item.chop_name}'",
                severity="warning",
            )
            return

        editor = os.environ.get("EDITOR") or "nvim"
        with self.suspend():  # type: ignore[attr-defined]
            subprocess.run([editor, str(log_path)], check=False)

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
        wait_runners_default = match.lumberjack.wait_runners

        def _run() -> ChopRunOutcome:
            return run_configured_chop_once(
                lumberjack_name=lumberjack_name,
                chop=chop_cfg,
                axe_config=config,
                chop_timeout_default=chop_timeout_default,
                wait_runners_default=wait_runners_default,
                source="manual",
                started_by="ace",
            )

        self.notify(  # type: ignore[attr-defined]
            f"Running chop '{chop_name}' under '{lumberjack_name}'..."
        )

        try:
            outcome = await asyncio.to_thread(_run)
        except Exception as e:
            from sase.logs import log_launch_failure, new_error_id

            error_id = new_error_id()
            await asyncio.to_thread(
                log_launch_failure,
                kind="chop",
                display_name=chop_name,
                exc=e,
                chop=chop_name,
                lumberjack=lumberjack_name,
                error_id=error_id,
            )
            notify_registered_error(
                self,
                f"Failed to launch chop '{chop_name}': {e}",
                error_id=error_id,
            )
            # Even on failure the runner may have written a partial run
            # entry; refresh so the dashboard reflects current on-disk state.
            self._schedule_axe_async_refresh()  # type: ignore[attr-defined]
            return

        outcome_error_id: str | None = None
        if _is_failure_chop_outcome(outcome):
            outcome_error_id = await asyncio.to_thread(
                _log_chop_failure_outcome, outcome
            )
        self._notify_chop_outcome(outcome, error_id=outcome_error_id)
        # Always pull fresh state so the new (or updated) run entry shows
        # up in the dashboard and the sidebar status marker repaints.
        self._schedule_axe_async_refresh()  # type: ignore[attr-defined]

    def _notify_chop_outcome(
        self, outcome: ChopRunOutcome, *, error_id: str | None = None
    ) -> None:
        """Translate a backend outcome into a user-facing notification."""
        chop = outcome.chop_name
        lj = outcome.lumberjack_name

        def _fail(prefix: str, *, severity: str = "error") -> None:
            if error_id is not None:
                notify_registered_error(
                    self, prefix, error_id=error_id, severity=severity
                )
            else:
                self.notify(prefix, severity=severity)  # type: ignore[attr-defined]

        if outcome.status == "already_running":
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{chop}' is already running under '{lj}'",
                severity="warning",
            )
        elif outcome.status == "success":
            self.notify(f"Chop '{chop}' finished successfully")  # type: ignore[attr-defined]
        elif outcome.status == "skipped":
            reason = outcome.reason or "a declarative policy did not fire"
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{chop}' skipped: {reason}", severity="warning"
            )
        elif outcome.status == "no_op":
            self.notify(f"Chop '{chop}' completed with no work to do")  # type: ignore[attr-defined]
        elif outcome.status == "launched":
            count = len(outcome.launches)
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{chop}' launched {count} agent action(s)"
            )
        elif outcome.status == "action_succeeded":
            self.notify(f"Chop '{chop}' action succeeded")  # type: ignore[attr-defined]
        elif outcome.status == "failure":
            exit_str = (
                f" (exit {outcome.exit_code})" if outcome.exit_code is not None else ""
            )
            _fail(f"Chop '{chop}' failed{exit_str}")
        elif outcome.status == "timeout":
            _fail(f"Chop '{chop}' timed out")
        elif outcome.status == "missing_script":
            _fail(f"Chop '{chop}': script not found")
        elif outcome.status == "check_error":
            _fail(f"Chop '{chop}' check is degraded", severity="warning")
        elif outcome.status == "action_failed":
            _fail(f"Chop '{chop}' action failed")
        else:
            self.notify(  # type: ignore[attr-defined]
                f"Chop '{chop}': unexpected outcome '{outcome.status}'",
                severity="warning",
            )


def _is_failure_chop_outcome(outcome: ChopRunOutcome) -> bool:
    return outcome.status in {
        "failure",
        "timeout",
        "missing_script",
        "check_error",
        "action_failed",
    }


def _log_chop_failure_outcome(outcome: ChopRunOutcome) -> str:
    """Durably record non-exception chop failure outcomes for the Logs tab."""
    from sase.logs import log_launch_failure

    exc = outcome.error
    if exc is None:
        exc = RuntimeError(f"Chop '{outcome.chop_name}' failed: {outcome.status}")
    return log_launch_failure(
        kind="chop",
        display_name=outcome.chop_name,
        exc=exc,
        chop=outcome.chop_name,
        lumberjack=outcome.lumberjack_name,
        status=outcome.status,
        run_id=outcome.run_id,
        exit_code=outcome.exit_code,
        agent_pid=outcome.agent_pid,
        traceback=outcome.traceback,
    )
