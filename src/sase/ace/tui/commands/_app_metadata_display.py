"""Grouping, query, display, workspace, and mode app-command metadata.

Split out of ``_app_metadata.py`` to keep each module under the 500-line cap.
"""

from __future__ import annotations

from sase.ace.tui.commands._tabs import (
    AGENTS_AXE,
    AGENTS_ONLY,
    ALL_TABS,
    CL_AGENTS,
    CL_AXE,
    CL_ONLY,
)
from sase.ace.tui.commands.types import AppCommandMeta


DISPLAY_COMMAND_META: tuple[AppCommandMeta, ...] = (
    # Grouping (grouping-capable Artifacts panes + Agents)
    ("cycle_grouping_mode", "Cycle grouping mode", "Grouping", CL_AGENTS, ()),
    (
        "cycle_grouping_mode_reverse",
        "Cycle grouping mode (reverse)",
        "Grouping",
        CL_AGENTS,
        (),
    ),
    # Tools panel
    ("toggle_thinking", "Toggle tools panel", "Display", AGENTS_ONLY, ()),
    (
        "toggle_thinking_reverse",
        "Toggle tools panel (reverse)",
        "Display",
        AGENTS_ONLY,
        (),
    ),
    # Queries
    (
        "edit_query",
        "Edit query or filter",
        "Queries",
        CL_AXE,
        ("filter", "query", "/"),
    ),
    (
        "search_forward",
        "Search metadata forward",
        "Queries",
        AGENTS_ONLY,
        ("find", "forward", "/"),
    ),
    (
        "search_reverse",
        "Reverse metadata search order",
        "Queries",
        AGENTS_ONLY,
        ("find", "reverse", "search direction", "ctrl+r"),
    ),
    (
        "open_saved_query_picker",
        "Choose saved Patch query",
        "Saved Queries",
        CL_ONLY,
        ("saved query", "query slots", "star query"),
    ),
    (
        "start_saved_query_mode",
        "Load saved Patch query by slot",
        "Saved Queries",
        CL_ONLY,
        ("saved query slot", "query slot"),
    ),
    ("prev_query", "Previous saved query", "Queries", ALL_TABS, ()),
    ("next_query", "Next saved query", "Queries", ALL_TABS, ()),
    # Display / misc
    ("toggle_hide_reverted", "Toggle hide reverted", "Display", AGENTS_AXE, ()),
    (
        "patches_toggle_reverted",
        "Toggle hide reverted",
        "Display",
        CL_ONLY,
        (),
    ),
    (
        "toggle_relation_panel",
        "Collapse relations panel",
        "Display",
        CL_ONLY,
        ("relations", "ancestors", "children", "relation panel"),
    ),
    ("toggle_hide_submitted", "Toggle hide submitted", "Display", CL_ONLY, ()),
    ("show_notifications", "Show notifications", "Display", ALL_TABS, ()),
    (
        "open_config_center",
        "Open SASE Admin Center",
        "Display",
        ALL_TABS,
        (
            "#",
            "admin",
            "admin center",
            "settings",
            "config",
            "configuration",
            "procs",
            "proc queue",
            "tasks",
            "task queue",
            "logs",
            "log panel",
            "updates",
            "plugins",
            "plugin catalog",
            "xprompts",
            "browse xprompts",
            "glossary",
            "memory",
            "snippets",
        ),
    ),
    (
        "show_help",
        "Show help",
        "Display",
        ALL_TABS,
        ("help", "keybindings", "?", "guide"),
    ),
    (
        "dismiss_toasts",
        "Dismiss toasts",
        "Display",
        ALL_TABS,
        ("clear toasts", "clear notifications"),
    ),
    # Workspace prefixes
    ("checkout", "Checkout workspace (primary)", "Workspace", ALL_TABS, ()),
    ("start_checkout_mode", "Checkout workspace mode", "Modes", ALL_TABS, ()),
    ("open_tmux", "Open tmux (primary)", "Workspace", ALL_TABS, ()),
    ("start_tmux_mode", "Open tmux mode", "Modes", ALL_TABS, ()),
    # Tree navigation prefixes
    (
        "start_ancestor_mode",
        "Ancestor navigation",
        "Tree Navigation",
        CL_ONLY,
        (),
    ),
    ("start_child_mode", "Child navigation", "Tree Navigation", CL_ONLY, ()),
    ("start_sibling_mode", "Sibling navigation", "Tree Navigation", CL_AGENTS, ()),
    # Mode activation prefixes
    ("start_fold_mode", "Enter fold mode", "Modes", CL_AGENTS, ()),
    ("start_leader_mode", "Enter leader mode", "Modes", ALL_TABS, ()),
    ("start_bang_mode", "Enter bang mode", "Modes", ALL_TABS, ()),
    ("copy_tab_content", "Enter copy mode", "Modes", ALL_TABS, ()),
    # Palette itself
    (
        "open_command_palette",
        "Open command palette",
        "Misc",
        ALL_TABS,
        ("commands", ":"),
    ),
)
