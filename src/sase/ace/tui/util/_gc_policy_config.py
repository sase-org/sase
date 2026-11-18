"""Shared constants and kill switch for the idle-time full-GC policy."""

from __future__ import annotations

import os

ENV_DISABLE = "SASE_TUI_GC_POLICY_DISABLE"
ENV_CENSUS = "SASE_TUI_GC_CENSUS"
TICK_INTERVAL_S = 1.0
IDLE_QUIET_S = 3.0
BACKSTOP_QUIET_S = 3.0
MIN_FULL_INTERVAL_S = 60.0
FULL_BACKSTOP_S = 5 * 60.0
DUTY_FACTOR = 30.0
MAX_DUTY_DELAY_S = 15 * 60.0
RSS_GROWTH_BACKSTOP_BYTES = 500 * 1024 * 1024
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
