"""GC pause recorder and memory heartbeat for the ACE TUI.

A lock-free ``gc.callbacks`` recorder tags every collection with its trigger
(``"automatic"`` unless wrapped in :func:`gc_trigger`), keeps exact
per-generation running totals, a bounded ring of recent collections for
watchdog overlap attribution, and a bounded queue of notable pauses (every
full collection, plus young collections of at least
``YOUNG_PAUSE_ROW_MIN_S``). A daemon flush thread drains the queue into
``tui_gc_pause`` rows and writes a 5-minute ``tui_memory_heartbeat`` row,
whose ``gc_young_notable`` counters cover every young pause of at least
``NOTABLE_PAUSE_S``. The same worker samples cached RSS, swap, and major-fault
pressure every few seconds for the GC policy; policy deferral rows use the
worker queue instead of writing from the UI timer. Telemetry rows go through
``sase.logs.log_tui_stall`` into ``tui_stalls.jsonl``; the Rust perf-log
aggregator only counts ``STALL_EVENTS``/``RECOVERY_EVENTS``, so the new row
kinds need no ``sase-core`` change.

Only the ``gc.callbacks`` entry point is constrained: a collection can fire
while the flusher holds a lock, so the callback performs plain attribute
updates and ``deque`` appends only. The flush thread may use locks, I/O,
and logging freely.
"""

from __future__ import annotations

from ._gc_telemetry_config import (
    ENV_DISABLE as ENV_DISABLE,
    ENV_FLUSH_INTERVAL as ENV_FLUSH_INTERVAL,
    ENV_HEARTBEAT_INTERVAL as ENV_HEARTBEAT_INTERVAL,
    FIRST_HEARTBEAT_DELAY_S as FIRST_HEARTBEAT_DELAY_S,
    FLUSH_INTERVAL_S as FLUSH_INTERVAL_S,
    FULL_GENERATION as FULL_GENERATION,
    HEARTBEAT_INTERVAL_S as HEARTBEAT_INTERVAL_S,
    NOTABLE_PAUSE_S as NOTABLE_PAUSE_S,
    QUEUE_MAX as QUEUE_MAX,
    RATE_LIMIT_PER_MIN as RATE_LIMIT_PER_MIN,
    RATE_LIMIT_WINDOW_S as RATE_LIMIT_WINDOW_S,
    RECENT_RING_MAX as RECENT_RING_MAX,
    THREAD_NAME as THREAD_NAME,
    UNTAGGED_TRIGGER as UNTAGGED_TRIGGER,
    YOUNG_PAUSE_ROW_MIN_S as YOUNG_PAUSE_ROW_MIN_S,
    is_enabled as is_enabled,
)
from ._gc_telemetry_lifecycle import (
    app_instance_id as app_instance_id,
    emit_row as emit_row,
    gc_trigger as gc_trigger,
    install_gc_telemetry as install_gc_telemetry,
    latest_memory_pressure as latest_memory_pressure,
    latest_rss_bytes as latest_rss_bytes,
    new_app_instance_id as new_app_instance_id,
    note_last_input_mono as note_last_input_mono,
    queue_row as queue_row,
    recent_collections as recent_collections,
    uninstall_gc_telemetry as uninstall_gc_telemetry,
)
from ._gc_telemetry_recorder import (
    GCTelemetry as GCTelemetry,
    default_executor_heartbeat_fields as default_executor_heartbeat_fields,
    register_heartbeat_provider as register_heartbeat_provider,
    unregister_heartbeat_provider as unregister_heartbeat_provider,
)
