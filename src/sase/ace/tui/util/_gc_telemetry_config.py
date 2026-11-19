"""Shared constants and kill switch for ACE TUI GC telemetry."""

from __future__ import annotations

import os

ENV_DISABLE = "SASE_TUI_GC_TELEMETRY_DISABLE"
ENV_FLUSH_INTERVAL = "SASE_TUI_GC_TELEMETRY_FLUSH_SECONDS"
ENV_HEARTBEAT_INTERVAL = "SASE_TUI_GC_TELEMETRY_HEARTBEAT_SECONDS"

FLUSH_INTERVAL_S = 2.0
HEARTBEAT_INTERVAL_S = 5 * 60.0
FIRST_HEARTBEAT_DELAY_S = 15.0
PRESSURE_SAMPLE_INTERVAL_S = 5.0
RATE_LIMIT_PER_MIN = 60
RATE_LIMIT_WINDOW_S = 60.0
RECENT_RING_MAX = 256
QUEUE_MAX = 2048
NOTABLE_PAUSE_S = 0.050
# Young (gen-0/1) collections write a ``tui_gc_pause`` row only from this
# duration up. Shorter notable young pauses were ~80% of athena's stall-log
# rows; they roll into the heartbeat's ``gc_young_notable`` counters instead,
# so ``tui_stalls.jsonl`` keeps 48 hours under its size cap.
YOUNG_PAUSE_ROW_MIN_S = 0.5
FULL_GENERATION = 2
THREAD_NAME = "sase-tui-gc-telemetry"

UNTAGGED_TRIGGER = "automatic"


def _disabled_by_env() -> bool:
    return os.environ.get(ENV_DISABLE) == "1"


def is_enabled() -> bool:
    """Return whether GC telemetry may install (kill switch aware)."""
    return not _disabled_by_env()
