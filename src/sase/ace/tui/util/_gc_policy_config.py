"""Shared constants and kill switch for the idle-time full-GC policy."""

from __future__ import annotations

import os

ENV_DISABLE = "SASE_TUI_GC_POLICY_DISABLE"
ENV_CENSUS = "SASE_TUI_GC_CENSUS"
TICK_INTERVAL_S = 1.0
IDLE_QUIET_S = 3.0
BACKSTOP_QUIET_S = 3.0
LONG_IDLE_QUIET_S = 15 * 60.0
LONG_IDLE_COLLECTION_INTERVAL_S = 30 * 60.0
MIN_FULL_INTERVAL_S = 60.0
FULL_BACKSTOP_S = 5 * 60.0
DUTY_FACTOR = 30.0
MAX_DUTY_DELAY_S = 15 * 60.0
RSS_GROWTH_BACKSTOP_BYTES = 500 * 1024 * 1024
# Paging activity, not a residual VmSwap level, is memory pressure: VmSwap
# growth between two consecutive telemetry samples (5 s apart) or a recent
# major-fault rate above these thresholds defers a full collection.
SWAP_GROWTH_PRESSURE_BYTES = 16 * 1024 * 1024
MAJOR_FAULTS_PER_S_PRESSURE_THRESHOLD = 100.0
PRESSURE_SAMPLE_MAX_AGE_S = 20.0
# Pressure may hold the ``backstop`` / ``rss_backstop`` triggers this long at
# most; afterwards a backstop runs once input has been quiet this long.
PRESSURE_MAX_DEFERRAL_S = 10 * 60.0
PRESSURE_OVERRIDE_QUIET_S = 60.0
MAX_PREDICTED_FULL_PAUSE_S = 2.0
COST_PREDICTION_SAFETY_FACTOR = 2.0
# Ordinary sweeps are priced by time, not by allocated-block deltas: a
# frozen-heap sweep's pause tracks the garbage and survivors created since
# the last full collection, and those accumulate at a steady rate under
# steady use. Net allocated blocks are no scan count: old frozen objects
# freed by refcount shrink the total while new cyclic garbage still needs
# scanning (the R3 spot check on sase a52054ed45 recorded a 0.647 s sweep
# priced as one block, then predicted 645,427 s). A cost sample is a pause
# over the seconds of accumulation it swept; samples shorter than this
# floor are stretched to it so a sweep right after another cannot divide
# by ~0.
MIN_COST_SAMPLE_ACCUM_S = 1.0
# Cost-due cadence: once the estimate (safety factor included) reaches this
# share of the pause budget, a sweep is due on the next quiet window even
# before 100 gen-1 collections pile up, and the 60 s duty minimum relaxes
# to ``COST_DUE_MIN_INTERVAL_S`` (``pause * DUTY_FACTOR`` still applies).
# R3 arithmetic (sase a52054ed45, j/k input every 30-150 s): sweeps 60 s
# apart paused 0.56-0.86 s, ~0.0117 s of pause per second of accumulation
# at ~8.5k blocks/s. Due at 0.5 x 2 s = 1.0 s estimated (0.5 s expected)
# means a sweep about every 43 s, leaving 4x headroom under the budget for
# a missing quiet window or a faster heap.
COST_DUE_FRACTION = 0.5
COST_DUE_MIN_INTERVAL_S = 15.0
# The cost gate (``cost_gate``) may hold the ``idle``, ``backstop``, and
# ``rss_backstop`` triggers only while the expected pause grows by at most
# ``COST_DEFERRAL_GROWTH_S``: the cap is that growth divided by the sampled
# pause rate, clamped to ``COST_MAX_DEFERRAL_S``. Afterwards a sweep runs on
# the next ordinary quiet window (``COST_OVERRIDE_QUIET_S`` of input quiet,
# no prompt/navigation/modal active). A fixed cap cannot be calibrated:
# R3's 600 s cap let the heap grow ~5.1M blocks at ~1.1 us/block (7x the
# baseline's 0.15 us/block full-heap rate) into 5.6-5.7 s sweeps. At R3's
# 0.0117 s/s the cap is 0.5 / 0.0117 ~= 43 s; at the baseline's
# 0.34 s / 600 s it clamps to 600 s. An unknown estimate never defers:
# deferral only grows the heap, so the first post-freeze sweep seeds the
# sample on the first quiet window.
COST_DEFERRAL_GROWTH_S = 0.5
COST_MAX_DEFERRAL_S = 10 * 60.0
# Ordinary quiet window that lets a cost-capped sweep run: same 3 s the idle
# gate already requires, stated separately so the cap's promise reads here.
COST_OVERRIDE_QUIET_S = 3.0
# Bounded deep cadence: frozen-set garbage is reclaimed by an unfreeze sweep
# at most this often on an ordinary quiet window, and only when its
# full-heap estimate fits the pause budget; an over-budget deep sweep never
# runs while the user is active and never holds an ordinary sweep (the
# 15-minute-idle deep pass still reclaims it). Baseline deep passes
# reclaimed ~5-8.6M objects per 30 min under active input (~0.5-1 GB/h, far
# above the 25 MB/h gate). Anchored at the startup freeze, so short spot
# checks never trip it.
DEEP_SWEEP_INTERVAL_S = 60 * 60.0
# Deep sweeps scan GC-tracked objects (``gc.get_freeze_count()`` plus the
# generation counts from ``gc.get_count()``), not allocated blocks. Until a
# verified deep sample exists they are priced at the attribute-phase
# measured rate: 1.479 s / 1_937_310 frozen containers = 0.763 us/object
# (attribute-20261122T165600Z long-idle deep pass). Allocated-block pricing
# (0.3 us × 8.34M × 2) predicted 5.0 s and gated every hourly pass; the
# same sweep paused 1.479 s. With the safety factor a 1.8M-object heap
# predicts 0.763 us × 1.8M × 2 ≈ 2.75 s, still over the 2 s budget, so the
# hourly cadence stays gated there and the 15-minute-idle pass reclaims.
DEEP_COST_PER_OBJECT_S = 0.763e-6
DEFERRED_TELEMETRY_INTERVAL_S = 60.0
GEN1_DUE_COUNT = 100
NONCLASSIC_DUE_S = 120.0
RAISED_THRESHOLD2 = 10_000
TRIM_INTERVAL_S = 10 * 60.0
CENSUS_INTERVAL_S = 10 * 60.0
CENSUS_TOP_N = 40
CENSUS_WATCHLIST: frozenset[str] = frozenset(
    {
        "sase.ace.tui.models.agent.Agent",
        "sase.ace.tui.provider_contract.AceRowHandle",
        "sase.agents.catalog._query.AgentCatalogLinkFacets",
        "sase.artifact_read_log.ArtifactReadEvent",
        "sase.ace.tui.artifact_reads.ArtifactReadDisplayEvent",
        # Defining module, not the ``sase.core.agent_scan_wire``
        # re-export: ``gc.get_objects()`` keys on ``__module__``.
        "sase.core.agent_scan_wire_records.AgentArtifactRecordWire",
        # Compact list projection retained by the one-generation snapshot
        # cache and the bounded selected-detail owner.
        "sase.core.agent_scan_list_wire.AgentArtifactListRecordWire",
        "sase.core.artifact_file_types.ArtifactFile",
        "sase.core.bead_touch_index_models.BeadTouch",
        "sase.ace.tui._bead_touches_shared.BeadTouchDisplayEvent",
        "sase.bead.stranded.StrandedReport",
        "sase.memory._read_log_models.MemoryReadEvent",
        "sase.ace.tui.memory_reads.MemoryReadDisplayEvent",
        "sase.skills.use_log.SkillUseEvent",
        "sase.core.stranded_work_facade.StrandedWorkReport",
        "sase.core.stranded_work_facade.StrandedWorkVerdict",
        "sase.notifications.models.Notification",
        "sase.notifications.models.NotificationPlusOne",
        "textual.cache.FIFOCache",
    }
)
TIMER_NAME = "gc-policy"
TRIM_THREAD_NAME = "sase-tui-gc-trim"
HEARTBEAT_PROVIDER_NAME = "gc_policy"
THRESHOLD_RAISED = "raised"
THRESHOLD_UNSUPPORTED = "unsupported"
FULL_GENERATION = 2


def is_enabled() -> bool:
    """Return whether the GC policy may install (kill switch aware)."""
    return os.environ.get(ENV_DISABLE) != "1"
