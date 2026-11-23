"""Pump-free Archive corpus controller around the shared core cache.

Corpus-controller seam for the Agents Archive epic (child epic
``sase-1jm.3.1``). UI callbacks only schedule work or apply still-current
results. Disk probing, facet loading, compile, and corpus queries run
off-thread via :func:`spawn_pump_free_task`.

Public facade for the split controller modules. Behavior lives in
:mod:`sase.ace.tui.actions.agents._archive_controller_pulse` (snapshot,
pulse, init, cancel), ``_archive_controller_schedule`` (opens, idle ticks,
windows, prewarm), and ``_archive_controller_apply`` (generation-safe
publication). Shared helpers live as public names in the already-private
``_archive_controller_support`` module so no split module imports a
``_``-prefixed name across modules. This module re-exports the public
names only so every existing import path keeps working.
"""

from __future__ import annotations

from ._archive_controller_pulse import (
    archive_corpus_snapshot,
    archive_inbox_pulse,
    cancel_archive_controller,
    init_agents_archive_controller,
    note_inbox_load_finished_for_archive,
    refresh_archive_inbox_pulse,
)
from ._archive_controller_schedule import (
    lookup_archive_light_row,
    note_inbox_applied_for_archive,
    request_archive_view_load,
    request_archive_windows,
    schedule_archive_idle_tick,
)

# Quiet-tick cadence for the background Archive idle revalidation. The
# auto-refresh tick fires every ~10 s; running a full corpus IDLE build on
# every tick costs p50 ~29 ms / mean ~158 ms even when nothing changed
# (grade-20261123). When the Archive view is not visible an explicit open
# rebuilds on demand, so the auto-refresh caller throttles background idle
# work to once per minute. Foreground (Archive visible) keeps the 10 s
# cadence. The constants live here so the caller and tests share them;
# schedule_archive_idle_tick itself always schedules (its contract), and
# the caller applies the cadence.
_ARCHIVE_IDLE_BACKGROUND_SECONDS = 60.0
_ARCHIVE_IDLE_FOREGROUND_SECONDS = 10.0

__all__ = [
    "archive_corpus_snapshot",
    "archive_inbox_pulse",
    "cancel_archive_controller",
    "init_agents_archive_controller",
    "lookup_archive_light_row",
    "note_inbox_applied_for_archive",
    "note_inbox_load_finished_for_archive",
    "refresh_archive_inbox_pulse",
    "request_archive_view_load",
    "request_archive_windows",
    "schedule_archive_idle_tick",
]
