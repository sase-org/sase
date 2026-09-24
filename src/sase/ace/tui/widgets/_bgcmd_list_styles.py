"""Row taxonomy palette for the background command list widget.

Each row family gets its own dominant hue so the three categories are
distinguishable at a glance even before reading the label text.

- Lumberjacks: gold accent + bold name (top-level).
- Chops:      dimmer copper/amber, subordinate to the parent lumberjack.
- Oneshots:   muted slate/teal, visibly quieter than daemon service proc rows.
"""

_LJ_ACCENT_STYLE = "bold #FFD700"
_LJ_NAME_STYLE = "#FFD700"
_LJ_NAME_SELECTED_STYLE = "bold #FFD700"

_CHOP_TREE_STYLE = "dim #FFD700"
_CHOP_NAME_STYLE = "#D7AF87"
_CHOP_NAME_SELECTED_STYLE = "bold #FFD700"

_ONESHOT_BADGE_STYLE = "#5F8787"
_ONESHOT_NAME_RUN_STYLE = "#87AFAF"
_ONESHOT_NAME_RUN_SELECTED_STYLE = "bold #87D7D7"
_ONESHOT_NAME_DONE_STYLE = "dim #87AFAF"
_ONESHOT_NAME_DONE_SELECTED_STYLE = "bold #87AFAF"
_ONESHOT_RUN_GLYPH = ("▷", "#5FAFD7")
_ONESHOT_OK_GLYPH = ("✓", "#87AF87")
_ONESHOT_FAIL_GLYPH = ("✗", "#D78787")
_ONESHOT_RUN_CHIP_STYLE = "#5FAFAF"
_ONESHOT_OK_CHIP_STYLE = "dim #87AF87"
_ONESHOT_FAIL_CHIP_STYLE = "#D78787"
_ONESHOT_DONE_CHIP_STYLE = "dim"

_SERVICE_ACCENT_STYLE = "bold #00D7AF"
_SERVICE_NAME_STYLE = "#00D7AF"
_SERVICE_NAME_SELECTED_STYLE = "bold #00D7AF"
_SERVICE_DISABLED_STYLE = "dim #87AFAF"
_SERVICE_WARN_STYLE = "bold #FFAF5F"

_DIVIDER_STYLE = "dim #5FD7FF"
_DIVIDER_LABEL = "── oneshots ──"

__all__ = [
    "_CHOP_NAME_SELECTED_STYLE",
    "_CHOP_NAME_STYLE",
    "_CHOP_TREE_STYLE",
    "_DIVIDER_LABEL",
    "_DIVIDER_STYLE",
    "_LJ_ACCENT_STYLE",
    "_LJ_NAME_SELECTED_STYLE",
    "_LJ_NAME_STYLE",
    "_ONESHOT_BADGE_STYLE",
    "_ONESHOT_DONE_CHIP_STYLE",
    "_ONESHOT_FAIL_CHIP_STYLE",
    "_ONESHOT_FAIL_GLYPH",
    "_ONESHOT_NAME_DONE_SELECTED_STYLE",
    "_ONESHOT_NAME_DONE_STYLE",
    "_ONESHOT_NAME_RUN_SELECTED_STYLE",
    "_ONESHOT_NAME_RUN_STYLE",
    "_ONESHOT_OK_CHIP_STYLE",
    "_ONESHOT_OK_GLYPH",
    "_ONESHOT_RUN_CHIP_STYLE",
    "_ONESHOT_RUN_GLYPH",
    "_SERVICE_ACCENT_STYLE",
    "_SERVICE_DISABLED_STYLE",
    "_SERVICE_NAME_SELECTED_STYLE",
    "_SERVICE_NAME_STYLE",
    "_SERVICE_WARN_STYLE",
]
