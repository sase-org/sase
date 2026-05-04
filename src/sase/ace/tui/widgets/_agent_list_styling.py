"""Constants, colors, and icons for the agent list widget."""

from sase.agent.status_buckets import AGENT_STATUS_BUCKET_GLYPHS

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
# secondary.  Level-2 visual banners (STANDARD L1 ChangeSpec and real
# BY_DATE L1 subgroup banners) inherit the same bar+rule treatment but in
# a slightly cooler accent so the top-level bucket still reads as the
# dominant header.  Level-3 visual banners (name-root) use a single
# dim-gray style for the branch glyph, trailing rule, and chip; only the
# label gets its own teal accent.
_PROJECT_BANNER_BAR_STYLE = "bold #5FAFFF"
_PROJECT_BANNER_RULE_STYLE = "dim #5FAFFF"
_CHANGESPEC_BANNER_BAR_STYLE = "bold #87D7FF"
_CHANGESPEC_BANNER_RULE_STYLE = "dim #87D7FF"
_NAME_ROOT_BANNER_BRANCH_STYLE = "dim #AFAFAF"
_NAME_ROOT_BANNER_LABEL_STYLE = "bold #87D7AF"

# Banner glyphs.  ``▌`` (left half-block) anchors L0 banners at the left
# edge as a colored bar; ``▎`` starts level-2 visual banners; ``▸`` starts
# level-3 visual banners and reads as "expanded labelled group".  Rules
# use heavy ``━`` only for L0 and light ``─`` for the deeper levels so
# weight forms a clear three-tier gradient.
_PROJECT_BAR_GLYPH = "▌"
_PROJECT_RULE = "━"
_CHANGESPEC_BAR_GLYPH = "▎"
_CHANGESPEC_RULE = "─"
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
# "this bucket is the X kind".  ``Needs Attention`` borrows the embedded-
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

# Icon for autonomous (%approve) agents
_APPROVE_ICON = "⚡"

# Icon for hidden agents (shown when visibility is toggled on)
_HIDDEN_ICON = "◌"

# Bead context badge for agents launched by ``sase bead work``.
_BEAD_GLYPH = "◆"
_BEAD_GLYPH_STYLE = "bold #5FD7AF"
_BEAD_TEXT_STYLE = "dim #87D7AF"

# Indentation prefix for workflow child agents
_CHILD_INDENT = "  └─ "

# Type glyphs for the small set of non-``RUNNING`` top-level rows.  The
# ``RUNNING`` (a.k.a. ``agent``) type is omitted entirely — its color
# already conveys the type.  Unknown display types fall back to ``[X]``.
_TYPE_GLYPHS: dict[str, str] = {
    "workflow": "≡",
    "cl": "❑",
    "changespec": "❑",
}
