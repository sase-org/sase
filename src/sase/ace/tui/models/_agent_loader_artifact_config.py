"""Shared artifact scan settings for the TUI agent loader."""

from dataclasses import replace

from sase.core.agent_scan_wire import AgentArtifactScanOptionsWire


TUI_SCAN_OPTIONS = AgentArtifactScanOptionsWire(
    include_prompt_step_markers=True,
    # The TUI reads prompt-step markers (workflow agent steps + meta_*
    # propagation) but does not render the raw_prompt.md snippet; skip
    # the snippet read to keep the scan compact.
    include_raw_prompt_snippets=False,
)

TIER1_RECENT_COMPLETED_LIMIT = 200
# First-paint safety valve for the visible inbox (about 6x the measured inbox
# of 316 completed candidates), not a working-set definition. Baseline reads
# use this cap; the 200-row cap above only bounds O(archive) source scans.
TIER1_VISIBLE_COMPLETED_LIMIT = 2000
TIER1_ACTIVE_LIMIT = 1000
TIER1_FALLBACK_SCAN_OPTIONS = replace(
    TUI_SCAN_OPTIONS,
    max_records=TIER1_RECENT_COMPLETED_LIMIT,
    newest_first=True,
)
PLAN_LIVE_SCAN_OPTIONS = replace(
    TUI_SCAN_OPTIONS,
    include_prompt_step_markers=False,
)
PLAN_LIVE_FALLBACK_SCAN_OPTIONS = replace(
    PLAN_LIVE_SCAN_OPTIONS,
    max_records=TIER1_RECENT_COMPLETED_LIMIT,
    newest_first=True,
)
