"""Constants, colors, and icons for the agent list widget."""

from __future__ import annotations

from typing import Protocol

from sase.agent.status_buckets import AGENT_STATUS_BUCKET_GLYPHS
from sase.monitor_state import (
    MONITOR_GLYPH,
    MONITOR_GLYPH_COLOR,
    MONITOR_SETTLED_GLYPH_COLOR,
)
from sase.monitor_status import (
    monitor_status_glyph,
    monitor_status_pair,
    monitor_status_style,
)

from .._restore_markers import ARMED_RESTORE_STYLE, FOLD_RESTORE_GLYPH
from ..models.agent import AgentType

# Sentinel agent_idx in ``_row_entries`` for banner (group) rows.
_BANNER_ROW = -1

# Minimum width for group banner rules.
_MIN_BANNER_WIDTH = 40

# Banner styles per level (rule + accent color).
#
# L0 (project) banners split into a heavyweight bar+label region (bold sky
# blue) and a dimmer rule+chip region (dim sky blue) so the label reads as
# the brightest element while the rule and right-aligned chip stay
# secondary.  Level-2 visual banners (STANDARD L1 Patch and real
# BY_DATE L1 subgroup banners) inherit the same bar+rule treatment but in
# a slightly cooler accent so the top-level bucket still reads as the
# dominant header.  Level-3 visual banners (name-root) use a single
# dim-gray style for the branch glyph, trailing rule, and chip; only the
# label gets its own teal accent.
_PROJECT_BANNER_BAR_STYLE = "bold #5FAFFF"
_PROJECT_BANNER_RULE_STYLE = "dim #5FAFFF"
_PATCH_BANNER_BAR_STYLE = "bold #87D7FF"
_PATCH_BANNER_RULE_STYLE = "dim #87D7FF"
_CHANGESPEC_BANNER_BAR_STYLE = _PATCH_BANNER_BAR_STYLE  # legacy compatibility alias
_CHANGESPEC_BANNER_RULE_STYLE = _PATCH_BANNER_RULE_STYLE  # legacy compatibility alias
_NAME_ROOT_BANNER_BRANCH_STYLE = "dim #AFAFAF"
_NAME_ROOT_BANNER_LABEL_STYLE = "bold #87D7AF"

# Banner glyphs.  ``▌`` (left half-block) anchors L0 banners at the left
# edge as a colored bar; ``▎`` starts level-2 visual banners; ``▸`` starts
# level-3 visual banners and reads as "expanded labelled group".  Rules
# use heavy ``━`` only for L0 and light ``─`` for the deeper levels so
# weight forms a clear three-tier gradient.
_PROJECT_BAR_GLYPH = "▌"
_PROJECT_RULE = "━"
_PATCH_BAR_GLYPH = "▎"
_PATCH_RULE = "─"
_CHANGESPEC_BAR_GLYPH = _PATCH_BAR_GLYPH  # legacy compatibility alias
_CHANGESPEC_RULE = _PATCH_RULE  # legacy compatibility alias
_NAME_ROOT_BRANCH_GLYPH = "▸"
_NAME_ROOT_RULE = "─"

# Tier guide gutter: every row carries one ``│  `` segment per ancestor
# L0/L1 banner so the nesting reads as a tree at a glance.  Width is 3
# cells (bar + 2 spaces).  Segment color reflects the tier the segment
# descends from, reusing the dim banner-rule colors.
_TIER_GUIDE_SEGMENT = "│  "
_TIER_GUIDE_SEGMENT_WIDTH = 3

# Status-bucket prefix glyphs for ``BY_STATUS`` mode L0 banners.  Reuses
# semantically-loaded glyphs from agent rendering so the banner reads as
# "this bucket is the X kind".  ``Stopped`` borrows the embedded-
# workflow ``▲`` (the only attention-grabbing arrow already in use);
# remaining buckets use minimal play / cross / check marks so the bucket
# title still leads visually.  Each glyph is rendered in the L0 sky-blue
# banner color — no per-bucket palette to keep the agents tab calm.
_STATUS_BUCKET_GLYPHS: dict[str, str] = {
    **AGENT_STATUS_BUCKET_GLYPHS,
}

# Color mapping for agent types
_AGENT_TYPE_COLORS: dict[AgentType, str] = {
    AgentType.RUNNING: "#87AFFF",  # Blue
    AgentType.WORKFLOW: "#FF87D7",  # Pink for workflow agent steps
}

# Per-step-type colors for workflow child entries
_STEP_TYPE_COLORS: dict[str, str] = {
    "agent": "#5FD7FF",  # Bright cyan — LLM agent steps stand out
    "bash": "#FFAF5F",  # Warm amber — shell commands
    "python": "#87D787",  # Soft green — code execution
    "parallel": "#D7AFFF",  # Soft lavender — parallel orchestration
}

# Per-step-type glyphs for workflow child entries. Only python/bash get
# a glyph: agent rows already carry a meaningful display name (and are
# the common case, so a glyph would be noise), parallel uses its accent
# + structural fan-out children, and prompt_part is invisible by default.
#
# Bash and python steps are both "a command the machine runs"; the
# per-step-type color carries the distinction, so one prompt chevron is
# enough — and unlike the old 🐍/🐚 emoji it is one cell wide and takes
# the row's Rich style.
_STEP_RUN_GLYPH = "❯"
_STEP_TYPE_GLYPHS: dict[str, str] = {"python": _STEP_RUN_GLYPH, "bash": _STEP_RUN_GLYPH}

_MONITOR_GLYPH = MONITOR_GLYPH
_MONITOR_GLYPH_STYLE = f"bold {MONITOR_GLYPH_COLOR}"
# Same non-bold grey as ``_MONITOR_SETTLED_COUNT_GLYPH_STYLE`` below; do not
# bold this — the weight-plus-hue rationale there applies to the row gear too.
_MONITOR_SETTLED_GLYPH_STYLE = MONITOR_SETTLED_GLYPH_COLOR
_MONITOR_ROW_STYLE = MONITOR_GLYPH_COLOR
_MONITOR_COUNT_GLYPH_STYLE = f"bold {MONITOR_GLYPH_COLOR}"

# Settled (finished) monitor lane. Deliberately non-bold, unlike the running
# lane above: hue *and* weight both separate the quieter settled badge from
# the live amber one, so the two stay distinguishable on low-color terminals
# and for red/green color vision deficiency. Reuses this codebase's existing
# neutral-grey token (see ``_IMPLICIT_TAG_STYLE`` in ``model_alias_styles.py``).
_MONITOR_SETTLED_COUNT_GLYPH_STYLE = MONITOR_SETTLED_GLYPH_COLOR

# A terminal monitor whose supervisor never reported a real exit code (died
# on arrival, or belongs to a previous boot): the command's outcome is
# unknown and the lane needs a human, not merely a finished-looking row.
_MONITOR_STALLED_GLYPH = "⚠"
_MONITOR_STALLED_GLYPH_STYLE = "bold #FF5F5F"

# A monitor whose ``--next`` follow-up action did not launch (or launched
# degraded). Independent of ``_MONITOR_STALLED_GLYPH``: a monitor can finish
# cleanly and still strand its follow-up.
_MONITOR_FOLLOWUP_ERROR_GLYPH = "⚑"
_MONITOR_FOLLOWUP_ERROR_GLYPH_STYLE = "bold #FFAF00"

# ``Agent.monitor_followup_outcome`` for a follow-up that launched only after
# falling back to a fresh claim or workspace 0. Mirrors
# ``sase.monitor.models.MONITOR_FOLLOWUP_DEGRADED_OUTCOME``, which the agent
# list cannot import without pulling the monitor supervisor stack onto this
# hot render path. A degraded launch records no ``monitor_followup_error``,
# so the flag has to key off the outcome as well.
_MONITOR_FOLLOWUP_DEGRADED_OUTCOME = "launched-degraded"

# Icon for auto-approve agents. Rendered bare for a normal-plan approval and
# suffixed ``E``/``T`` for epic/tale plan actions in
# ``_agent_list_render_agent``.
_APPROVE_ICON = "⚡"

# Icon for hidden agents (shown when visibility is toggled on)
_HIDDEN_ICON = "◌"

# Agent-name annotation color, shared by the list row trailing name
# annotation and the metadata header ``Name:`` value so the two stay in
# lockstep.
_AGENT_NAME_ANNOTATION_STYLE = "#FFD700"  # Gold

# Bead context badge for agents launched by ``sase bead work``.
_BEAD_GLYPH = "◆"
_BEAD_GLYPH_STYLE = "bold #5FD7AF"

# File-change badge for agents whose persisted diff includes reviewable edits.
# Plan/prompt bookkeeping-only diffs are classified at load time and omitted.
_FILE_CHANGE_GLYPH = "✏️"
_FILE_CHANGE_GLYPH_STYLE = "bold #FFD75F"

# Missing named agent wait target. Shared by the compact WAITING row marker
# and the per-target metadata badge so both surfaces use one visual contract.
_MISSING_WAIT_TARGET_GLYPH = "?"
_MISSING_WAIT_TARGET_GLYPH_STYLE = "bold #FFAF5F"

# Reserved tribe wait target. This means the wait cannot ever resolve, unlike a
# missing agent name that may be a typo or stale reference.
_UNRESOLVABLE_WAIT_TARGET_GLYPH = "!"
_UNRESOLVABLE_WAIT_TARGET_GLYPH_STYLE = "bold #FF5F5F"

# Reverted badge for agents whose commits were intentionally undone via `,r`.
_REVERTED_GLYPH = "↺"
_REVERTED_GLYPH_STYLE = "bold #D7875F"

# Restore preview for folds swept by `-`. Uses the same gold as the `▿N`
# panel-title chip so every armed fold-restore marker reads as one affordance.
_FOLD_RESTORE_GLYPH = FOLD_RESTORE_GLYPH
_FOLD_RESTORE_GLYPH_STYLE = ARMED_RESTORE_STYLE

# Indentation prefix for workflow child agents
_CHILD_INDENT = "  └─ "
_TREE_GUIDE = "│  "

# Agent-grouping row identity colors. These saturated colors distinguish each
# grouping kind without adding a trailing marker to the displayed name.
_CLAN_IDENTITY_COLOR = "#D75FFF"
_CLAN_NAME_STYLE = _CLAN_IDENTITY_COLOR
_FAMILY_IDENTITY_COLOR = "#00AFFF"
_FAMILY_NAME_STYLE = _FAMILY_IDENTITY_COLOR

# Type glyphs for the small set of non-``RUNNING`` top-level rows.  The
# ``RUNNING`` (a.k.a. ``agent``) type is omitted entirely — its color
# already conveys the type.  Unknown display types fall back to ``[X]``.
_TYPE_GLYPHS: dict[str, str] = {
    "workflow": "≡",
    "cl": "❑",
    "patch": "❑",
}


class _MonitorStatusPresentationRow(Protocol):
    status: str
    monitor_start_status: str | None
    monitor_stop_status: str | None
    monitor_state: str | None


def monitor_status_presentation(
    row: _MonitorStatusPresentationRow,
) -> tuple[str, str] | None:
    """Return ``(style, glyph)`` when *row* is displaying a monitor status.

    A row uses monitor-status styling when its ``status`` equals either
    half of its recorded pair. That covers the monitor member itself and a
    family container currently mirroring one. Rows with no recorded pair,
    or whose status matches neither half, return ``None`` so ordinary
    status styling applies.

    The returned glyph is the status-outcome marker. Failed monitors
    return an empty glyph so the existing ``✗ <code>`` / stalled-``⚠``
    branches remain the only cross — otherwise a dead-on-arrival row
    would show both ``✗`` and ``⚠``.
    """
    start = row.monitor_start_status
    stop = row.monitor_stop_status
    if not start and not stop:
        return None
    pair = monitor_status_pair(start, stop)
    if row.status.casefold() not in {pair.start.casefold(), pair.stop.casefold()}:
        return None
    glyph = monitor_status_glyph(row.monitor_state)
    if row.monitor_state == "failed":
        glyph = ""
    return monitor_status_style(pair, monitor_state=row.monitor_state), glyph
