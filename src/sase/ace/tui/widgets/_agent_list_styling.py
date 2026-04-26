"""Constants, colors, and icons for the agent list widget."""

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
# secondary.  ChangeSpec banners (L1 in 3-level mode) inherit the same
# bar+rule treatment but in a slightly cooler accent so the project still
# reads as the dominant header.  Name-root banners (L1 in 2-level mode,
# L2 in 3-level mode) use a single dim-gray style for the branch glyph,
# trailing rule, and chip; only the name-root label gets its own teal
# accent.
_PROJECT_BANNER_BAR_STYLE = "bold #5FAFFF"
_PROJECT_BANNER_RULE_STYLE = "dim #5FAFFF"
_CHANGESPEC_BANNER_BAR_STYLE = "bold #87D7FF"
_CHANGESPEC_BANNER_RULE_STYLE = "dim #87D7FF"
_NAME_ROOT_BANNER_BRANCH_STYLE = "dim #AFAFAF"
_NAME_ROOT_BANNER_LABEL_STYLE = "bold #87D7AF"

# Banner glyphs.  ``▌`` (left half-block) anchors L0 banners at the left
# edge as a colored bar; ``╶─`` starts ChangeSpec banners with a slight
# indent; ``╭─`` (rounded branch) starts name-root banners and reads as
# "subgroup begins here".  Rules use heavy ``━`` for project / ChangeSpec
# headers and light ``─`` for name-root so the project tier has visibly
# more weight.
_PROJECT_BAR_GLYPH = "▌"
_PROJECT_RULE = "━"
_CHANGESPEC_BAR_GLYPH = "▎"
_CHANGESPEC_INDENT = "  "
_NAME_ROOT_BRANCH_GLYPH = "╭─"
_NAME_ROOT_RULE = "─"
_NAME_ROOT_INDENT = "  "
_NAME_ROOT_DEEP_INDENT = "    "

# Status-bucket prefix glyphs for ``BY_STATUS`` mode L0 banners.  Reuses
# semantically-loaded glyphs from agent rendering so the banner reads as
# "this bucket is the X kind".  ``Needs Attention`` borrows the embedded-
# workflow ``▲`` (the only attention-grabbing arrow already in use);
# remaining buckets use minimal play / cross / check marks so the bucket
# title still leads visually.  Each glyph is rendered in the L0 sky-blue
# banner color — no per-bucket palette to keep the agents tab calm.
_STATUS_BUCKET_GLYPHS: dict[str, str] = {
    "Needs Attention": "▲",
    "Running": "▶",
    "Failed": "✗",
    "Done": "✓",
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

# Indentation prefix for workflow child agents
_CHILD_INDENT = "  └─ "

# Single- / two-glyph status badges replace the verbose ``(STATUS)`` text.
# Color mapping is handled separately in the renderer so colors remain
# unchanged; this table only supplies the glyphs.  Statuses not in the
# table fall back to rendering the literal status name in parens.
_STATUS_GLYPHS: dict[str, str] = {
    "RUNNING": "▶",
    "DONE": "✓",
    "PLAN DONE": "✓P",
    "PLAN APPROVED": "▶P",
    "EPIC CREATED": "★E",
    "PLANNING": "✎",
    "FAILED": "✗",
    "WAITING": "⏳",
    "QUESTION": "?",
    "RETRYING": "↻",
}

# Type glyphs for the small set of non-``RUNNING`` top-level rows.  The
# ``RUNNING`` (a.k.a. ``agent``) type is omitted entirely — its color
# already conveys the type.  Unknown display types fall back to ``[X]``.
_TYPE_GLYPHS: dict[str, str] = {
    "workflow": "≡",
    "cl": "❑",
    "changespec": "❑",
}
