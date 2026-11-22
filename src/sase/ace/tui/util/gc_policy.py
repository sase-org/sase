"""Idle-time full-GC policy for the ACE TUI.

CPython's classic collector can spend seconds in a stop-the-world gen-2
collection. This module bounds policy-initiated sweeps with freeze generations,
swap-pressure deferral, and a pause estimate:

- after startup loads settle and input first goes idle, ``gc.freeze()`` moves
  the existing heap out of future ordinary sweeps without running a full
  collection;
- after each policy full collection that provably ran (the gen-2 counter
  advanced; ``gc.collect()`` is a no-op while another thread collects),
  survivors are frozen again, so ordinary sweeps cover only the new
  generation; an unfreeze-and-collect pass reclaims frozen garbage after 15
  minutes without input (no more often than every 30 minutes), and
  additionally at most hourly on an ordinary quiet window when its
  per-block full-heap estimate fits the pause budget;
- ``threshold2`` raised to 10_000 on the classic three-generation collector so
  automatic full collections become a rare backstop;
- tagged full collections only while input is quiet, no prompt is active, and
  a collection is due, with 5-minute and RSS-growth backstops; cached paging
  activity (VmSwap growth or a high major-fault rate, never a residual VmSwap
  level) defers full collections, but holds the backstops for at most 10
  minutes before one runs after 60 s of quiet; the pause estimate is the
  sampled pause rate times the seconds since the last full collection, and a
  sweep becomes due once it reaches half the 2 s budget; an estimate over the
  budget defers a sweep only while the expected pause grows by 0.5 s (at
  most 10 minutes) before it runs on the next ordinary quiet window; with no
  estimate yet the first post-freeze sweep runs at once and seeds it; every
  observed full collection (automatic gen-2 included) refreshes the sample;
- duty-cycle bound: each own full collection's pause (timed with the
  injected clock) defers the next full collection by ``pause * DUTY_FACTOR``
  (clamped to 15 min, floored at 60 s, or 15 s once the estimate makes a
  sweep cost-due), applied to idle and backstop triggers alike;
- freed arenas returned with ``malloc_trim`` on a worker thread.

Full collections run under ``gc_trigger`` (from
:mod:`sase.ace.tui.util.gc_telemetry`) so ``tui_gc_pause`` rows carry the
``idle`` / ``backstop`` / ``rss_backstop`` trigger and the watchdog can attribute
any resulting hitch. Startup freeze does not run a collection. The policy is
driven by a 1 s ``set_interval`` whose callback stays thin and synchronous. It
never reads ``/proc`` on the UI thread (RSS and pressure come from the telemetry worker)
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
    COST_DEFERRAL_GROWTH_S as COST_DEFERRAL_GROWTH_S,
    COST_DUE_FRACTION as COST_DUE_FRACTION,
    COST_DUE_MIN_INTERVAL_S as COST_DUE_MIN_INTERVAL_S,
    COST_MAX_DEFERRAL_S as COST_MAX_DEFERRAL_S,
    COST_OVERRIDE_QUIET_S as COST_OVERRIDE_QUIET_S,
    COST_PREDICTION_SAFETY_FACTOR as COST_PREDICTION_SAFETY_FACTOR,
    DEEP_COST_PER_BLOCK_S as DEEP_COST_PER_BLOCK_S,
    DEEP_SWEEP_INTERVAL_S as DEEP_SWEEP_INTERVAL_S,
    DEFERRED_TELEMETRY_INTERVAL_S as DEFERRED_TELEMETRY_INTERVAL_S,
    DUTY_FACTOR as DUTY_FACTOR,
    ENV_CENSUS as ENV_CENSUS,
    ENV_DISABLE as ENV_DISABLE,
    FULL_BACKSTOP_S as FULL_BACKSTOP_S,
    FULL_GENERATION as FULL_GENERATION,
    GEN1_DUE_COUNT as GEN1_DUE_COUNT,
    HEARTBEAT_PROVIDER_NAME as HEARTBEAT_PROVIDER_NAME,
    IDLE_QUIET_S as IDLE_QUIET_S,
    LONG_IDLE_COLLECTION_INTERVAL_S as LONG_IDLE_COLLECTION_INTERVAL_S,
    LONG_IDLE_QUIET_S as LONG_IDLE_QUIET_S,
    MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD as MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD,
    MAX_PREDICTED_FULL_PAUSE_S as MAX_PREDICTED_FULL_PAUSE_S,
    MAX_DUTY_DELAY_S as MAX_DUTY_DELAY_S,
    MIN_COST_SAMPLE_ACCUM_S as MIN_COST_SAMPLE_ACCUM_S,
    MIN_FULL_INTERVAL_S as MIN_FULL_INTERVAL_S,
    NONCLASSIC_DUE_S as NONCLASSIC_DUE_S,
    PRESSURE_MAX_DEFERRAL_S as PRESSURE_MAX_DEFERRAL_S,
    PRESSURE_OVERRIDE_QUIET_S as PRESSURE_OVERRIDE_QUIET_S,
    PRESSURE_SAMPLE_MAX_AGE_S as PRESSURE_SAMPLE_MAX_AGE_S,
    SWAP_GROWTH_PRESSURE_BYTES as SWAP_GROWTH_PRESSURE_BYTES,
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
