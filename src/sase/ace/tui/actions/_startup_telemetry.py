"""Durable one-record-per-session ACE startup telemetry.

Every startup claim this epic makes was previously unfalsifiable in a real
terminal: the visible startup stopwatch (``KeybindingFooter`` /
``_keybinding_status.py``) renders elapsed time and throws it away, and the
one durable signal that existed (``tui_agent_loads.jsonl``) is censored at
its 2 s slow-stage threshold. This module writes one JSONL record per ACE
session to ``tui_startup.jsonl`` (``sase/logs/tui_telemetry.py``) carrying
both readiness metrics below, from day one, so a later phase can change
which one drives the visible stopwatch without silently invalidating this
phase's baseline:

- ``all_surfaces_ready_seconds`` — today's semantics: elapsed time, from the
  App's mount (the same anchor the visible stopwatch badge uses), until
  *both* ``_agents_first_load_done`` and ``_axe_first_load_done`` are true.
- ``visible_ready_seconds`` — elapsed time, from the same mount anchor,
  until the *initially visible* tab's own surface is interactive. The
  initial tab is snapshotted once at mount so a mid-startup tab switch
  cannot retarget an in-flight measurement.

The record is built on the UI thread (every input is already in memory) and
the write itself is dispatched with ``spawn_pump_free_task`` +
``asyncio.to_thread`` so durable log I/O never touches the event loop or a
Textual pump callback (``sase/memory/tui_perf.md`` rules 1 and 2).
"""

from __future__ import annotations

import logging
import os
import time
from datetime import UTC, datetime
from typing import Any

from ..util.pump_tasks import spawn_pump_free_task

log = logging.getLogger(__name__)


class StartupTelemetryMixin:
    """Mixin recording one durable JSONL startup-timing record per session."""

    _startup_process_start_mono: float
    _startup_on_mount_mono: float | None
    _startup_first_paint_mono: float | None
    _startup_initial_tab: Any
    _startup_agents_ready_mono: float | None
    _startup_axe_ready_mono: float | None
    _startup_visible_ready_mono: float | None
    _startup_telemetry_recorded: bool

    def _mark_startup_on_mount(self: Any) -> None:
        """Anchor the mount checkpoint and snapshot the initially visible tab."""
        if self._startup_on_mount_mono is not None:
            return
        self._startup_on_mount_mono = time.monotonic()
        self._startup_initial_tab = self.current_tab

    def _mark_startup_first_paint(self: Any) -> None:
        """Anchor the first-paint checkpoint (``call_after_refresh`` fired)."""
        if self._startup_first_paint_mono is None:
            self._startup_first_paint_mono = time.monotonic()

    def _startup_visible_surface_ready(self: Any) -> bool:
        """Return whether the initially visible tab's own surface is loaded."""
        if self._startup_initial_tab == "agents":
            return bool(self._agents_first_load_done)
        if self._startup_initial_tab == "axe":
            return bool(self._axe_first_load_done)
        # The artifacts tab is composed synchronously during on_mount, so it
        # has no analogous async "first load" gate to wait on.
        return True

    def _mark_startup_agents_ready(self: Any) -> None:
        """Record the agents surface becoming ready and maybe finish telemetry."""
        if self._startup_agents_ready_mono is None:
            self._startup_agents_ready_mono = time.monotonic()
        self._maybe_record_startup_telemetry()

    def _mark_startup_axe_ready(self: Any) -> None:
        """Record the axe surface becoming ready and maybe finish telemetry."""
        if self._startup_axe_ready_mono is None:
            self._startup_axe_ready_mono = time.monotonic()
        self._maybe_record_startup_telemetry()

    def _maybe_record_startup_telemetry(self: Any) -> None:
        """Schedule the durable startup record once both surfaces are ready.

        Matches ``_maybe_end_startup_stopwatch``'s gating exactly so the
        durable record and the visible stopwatch always settle together.
        """
        if self._startup_telemetry_recorded:
            return
        if not (self._agents_first_load_done and self._axe_first_load_done):
            return
        if (
            self._startup_visible_ready_mono is None
            and self._startup_visible_surface_ready()
        ):
            self._startup_visible_ready_mono = time.monotonic()
        if self._startup_visible_ready_mono is None:
            return
        self._startup_telemetry_recorded = True
        record = self._build_startup_telemetry_record()

        import asyncio

        from sase.logs import log_tui_startup

        spawn_pump_free_task(
            self,
            asyncio.to_thread(log_tui_startup, record),
            name="sase-startup-telemetry",
            registry_attr="_startup_telemetry_async_tasks",
        )

    def _build_startup_telemetry_record(self: Any) -> dict[str, Any]:
        """Assemble the durable startup record from the marked checkpoints."""
        process_start = self._startup_process_start_mono
        on_mount = self._startup_on_mount_mono
        first_paint = self._startup_first_paint_mono
        agents_ready = self._startup_agents_ready_mono
        axe_ready = self._startup_axe_ready_mono
        visible_ready = self._startup_visible_ready_mono
        all_ready = time.monotonic()

        load_state = getattr(self, "_agent_load_state", None)

        def _since(start: float | None, end: float | None) -> float | None:
            if start is None or end is None:
                return None
            return round(end - start, 6)

        return {
            "timestamp": datetime.now(UTC).isoformat(),
            "event": "tui_startup",
            "pid": os.getpid(),
            "initial_tab": self._startup_initial_tab,
            "source": getattr(self, "_agents_refresh_active_source", "unknown"),
            "tier": getattr(load_state, "tier", None),
            "artifact_source": getattr(load_state, "artifact_source", None),
            "agent_row_count": len(getattr(self, "_agents", ())),
            "index_row_count": getattr(load_state, "record_count", None),
            "process_start_to_on_mount_seconds": _since(process_start, on_mount),
            "on_mount_to_first_paint_seconds": _since(on_mount, first_paint),
            "agents_ready_seconds": _since(process_start, agents_ready),
            "axe_ready_seconds": _since(process_start, axe_ready),
            "visible_ready_seconds": _since(on_mount, visible_ready),
            "all_surfaces_ready_seconds": _since(on_mount, all_ready),
        }
