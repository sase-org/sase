"""Idle-time full-GC policy for the ACE TUI.

CPython's classic collector fires a stop-the-world gen-2 collection after a
handful of gen-1 collections *and* 25% old-generation growth, which lands
multi-second freezes on the interactive path. This module moves that decision
off the interactive path:

- after startup loads settle and input first goes idle, one ``gc.collect()``
  followed by ``gc.freeze()``, exactly once per app instance (never re-frozen:
  cyclic garbage among frozen objects is never reclaimed);
- ``threshold2`` raised to 10_000 on the classic three-generation collector so
  automatic full collections become a rare backstop;
- tagged full collections only while input is quiet, no prompt is active, and
  a collection is due, with 5-minute and RSS-growth backstops;
- duty-cycle bound: each own full collection's pause (timed with the
  injected clock) defers the next full collection by ``pause * DUTY_FACTOR``
  (clamped to 15 min, floored at 60 s), applied to idle and backstop
  triggers alike;
- freed arenas returned with ``malloc_trim`` on a worker thread.

Every collection runs under ``gc_trigger`` (from
:mod:`sase.ace.tui.util.gc_telemetry`) so ``tui_gc_pause`` rows carry the
``startup_freeze`` / ``idle`` / ``backstop`` / ``rss_backstop`` trigger and the
watchdog can attribute any resulting hitch. The policy is driven by a 1 s
``set_interval`` whose callback stays thin and synchronous; it never reads
``/proc`` on the UI thread (RSS comes from the telemetry heartbeat sample)
and never auto-installs under the ``sase.ace.testing`` harness. The opt-in
survivor census (``SASE_TUI_GC_CENSUS=1``) needs Python 3.14+; earlier
CPython versions skip ``gc.get_objects()`` and record collected-garbage
types only. Census rows rank types by count and shallow ``sys.getsizeof``
bytes, always emit a watchlist of suspected heap owners, and probe
already-imported snapshot caches so later diet phases can name owners.
"""

from __future__ import annotations

from ._gc_policy_config import (
    BACKSTOP_QUIET_S as BACKSTOP_QUIET_S,
    CENSUS_INTERVAL_S as CENSUS_INTERVAL_S,
    CENSUS_TOP_N as CENSUS_TOP_N,
    CENSUS_WATCHLIST as CENSUS_WATCHLIST,
    DUTY_FACTOR as DUTY_FACTOR,
    ENV_CENSUS as ENV_CENSUS,
    ENV_DISABLE as ENV_DISABLE,
    FULL_BACKSTOP_S as FULL_BACKSTOP_S,
    FULL_GENERATION as FULL_GENERATION,
    GEN1_DUE_COUNT as GEN1_DUE_COUNT,
    HEARTBEAT_PROVIDER_NAME as HEARTBEAT_PROVIDER_NAME,
    IDLE_QUIET_S as IDLE_QUIET_S,
    MAX_DUTY_DELAY_S as MAX_DUTY_DELAY_S,
    MIN_FULL_INTERVAL_S as MIN_FULL_INTERVAL_S,
    NONCLASSIC_DUE_S as NONCLASSIC_DUE_S,
    RAISED_THRESHOLD2 as RAISED_THRESHOLD2,
    RSS_GROWTH_BACKSTOP_BYTES as RSS_GROWTH_BACKSTOP_BYTES,
    THRESHOLD_RAISED as THRESHOLD_RAISED,
    THRESHOLD_UNSUPPORTED as THRESHOLD_UNSUPPORTED,
    TICK_INTERVAL_S as TICK_INTERVAL_S,
    TIMER_NAME as TIMER_NAME,
    TRIM_INTERVAL_S as TRIM_INTERVAL_S,
    TRIM_THREAD_NAME as TRIM_THREAD_NAME,
    is_enabled as is_enabled,
)
from ._gc_policy_lifecycle import (
    install_gc_policy as install_gc_policy,
    uninstall_gc_policy as uninstall_gc_policy,
)
from ._gc_policy_policy import GCPolicy as GCPolicy
