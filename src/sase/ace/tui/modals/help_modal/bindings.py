"""Keybinding definitions and constants for the help modal."""

from typing import Literal

TabName = Literal["changespecs", "agents", "axe"]

# Box dimensions for consistent formatting
BOX_WIDTH = 57  # Total box width in characters
CONTENT_WIDTH = 50  # Inner content width (BOX_WIDTH - borders)

# Keybinding definitions for each tab
# Each section is (section_name, list of (key, description) tuples)
CLS_BINDINGS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Navigation",
        [
            ("j / k", "Move to next / previous CL"),
            ("< / > / ~", "Navigate to ancestor / child / sibling"),
            ("Ctrl+O / K", "Jump back / forward in history"),
            ("Ctrl+D / U", "Scroll detail panel down / up"),
        ],
    ),
    (
        "CL Actions",
        [
            ("a", "Accept (! = spec only, @ = mail)"),
            ("b", "Rebase CL onto parent"),
            ("C / c1-c9", "Checkout CL (workspace 1-9)"),
            ("d", "Show diff"),
            ("h", "Edit hooks"),
            ("H", "Add hooks from failed targets"),
            ("L", "Agent run log"),
            ("M", "Mail CL"),
            ("m", "Mark/unmark current CL"),
            ("n", "Rename CL (non-Sub/Rev)"),
            ("R", "Rewind to prev commit (non-Sub/Rev)"),
            ("s", "Change status"),
            ("S", "Bulk status change (marked CLs)"),
            ("T / t1-t9", "Checkout + tmux (workspace 1-9)"),
            ("u", "Clear all marks"),
            ("v", "View files"),
            ("w", "Reword CL description"),
            ("W", "Add tag to CL description"),
            ("Y", "Sync workspace"),
            ("e", "Edit spec file"),
        ],
    ),
    (
        "Fold Mode",
        [
            ("z c", "Cycle commits folding"),
            ("z h", "Cycle hooks folding"),
            ("z m", "Cycle mentors folding"),
            ("z z", "Cycle all sections"),
        ],
    ),
    (
        "Workflows & Agents",
        [
            ("r", "Run workflow"),
            ("@", "Run an agent"),
            ("<space>", "Repeat last @/<space> selection"),
        ],
    ),
    (
        "Bang Mode (!)",
        [
            ("!!", "Run background command"),
            ("!x", "Start / stop axe (or select process)"),
        ],
    ),
    (
        "Leader Mode (,)",
        [
            (",!", "Run command (use current CL)"),
            (",h", "Run agent (home)"),
            (",m", "Kill running mentors"),
            (",r", "Show runners info"),
            (",<space>", "Run agent from current CL"),
        ],
    ),
    (
        "Queries",
        [
            ("/", "Edit search query"),
            ("0-9", "Load saved query"),
            ("^", "Previous query"),
            ("_", "Next query"),
        ],
    ),
    (
        "Copy Mode (%)",
        [
            ("%%", "Copy ChangeSpec"),
            ("%!", "Copy ChangeSpec + snapshot"),
            ("%b", "Copy bug number"),
            ("%c", "Copy CL number"),
            ("%n", "Copy CL name"),
            ("%p", "Copy project spec file"),
            ("%s", "Copy sase ace snapshot"),
        ],
    ),
    (
        "General",
        [
            ("Tab / Shift+Tab", "Switch tabs"),
            (".", "Show/hide reverted CLs"),
            ("#", "Browse xprompts"),
            ("N", "Show notifications"),
            ("Q", "Stop axe and quit"),
            ("y", "Refresh"),
            ("q", "Quit"),
            ("?", "Show this help"),
        ],
    ),
]

AGENTS_BINDINGS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Navigation",
        [
            ("j / k", "Move to next / previous agent"),
            ("g / G", "Scroll file panel to top / bottom"),
            ("Ctrl+D / U", "Scroll file panel down / up"),
            ("Ctrl+F / B", "Scroll prompt panel down / up"),
        ],
    ),
    (
        "Agent Actions",
        [
            ("@", "Run custom agent"),
            ("a", "Toggle auto-approve / answer HITL"),
            ("n", "Name agent"),
            ("r", "Revive chat as agent"),
            ("x", "Kill / dismiss agent"),
            ("e", "Edit chat in editor"),
            ("E", "Edit panel content in editor"),
            ("i", "Cycle panels: file → thinking → metadata"),
            ("p", "Toggle file/prompt layout"),
            ("Ctrl+N / P", "Next / prev file in panel"),
            ("=", "Reset file trim to default"),
            ("-", "Show all file lines"),
        ],
    ),
    (
        "Workflow Folding",
        [
            ("l / h", "Expand / collapse workflow steps"),
            ("L / H", "Expand / collapse all workflows"),
        ],
    ),
    (
        "Leader Mode (,)",
        [
            (",h", "Run agent (home)"),
            (",r", "Show runners info"),
        ],
    ),
    (
        "Bang Mode (!)",
        [
            ("!!", "Run background command"),
            ("!x", "Start / stop axe (or select process)"),
        ],
    ),
    (
        "Copy Mode (%)",
        [
            ("%c", "Copy chat file path"),
            ("%s", "Copy sase ace snapshot"),
        ],
    ),
    (
        "Search",
        [
            ("/", "Filter agents by name"),
        ],
    ),
    (
        "General",
        [
            ("Tab / Shift+Tab", "Switch tabs"),
            ("<space>", "Repeat last @/<space> selection"),
            (".", "Show/hide non-run agents"),
            ("#", "Browse xprompts"),
            ("N", "Show notifications"),
            ("Q", "Stop axe and quit"),
            ("y", "Refresh"),
            ("q", "Quit"),
            ("?", "Show this help"),
        ],
    ),
]

AXE_BINDINGS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Navigation",
        [
            ("j / k", "Move to next / previous command"),
            ("Ctrl+N / P", "Next / prev lumberjack output"),
            ("g", "Scroll to top"),
            ("G", "Scroll to bottom"),
        ],
    ),
    (
        "Background Commands",
        [
            ("@", "Run agent"),
            ("X", "Kill current command (or toggle axe)"),
        ],
    ),
    (
        "Leader Mode (,)",
        [
            (",h", "Run agent (home)"),
            (",r", "Show runners info"),
        ],
    ),
    (
        "Bang Mode (!)",
        [
            ("!!", "Run background command"),
            ("!x", "Start / stop axe (or select process)"),
        ],
    ),
    (
        "Copy Mode (%)",
        [
            ("%o", "Copy visible output"),
            ("%O", "Copy full output"),
            ("%s", "Copy sase ace snapshot"),
        ],
    ),
    (
        "Axe Control",
        [
            ("x", "Clear output"),
            ("X", "Start / stop axe daemon"),
            ("Q", "Stop axe and quit"),
        ],
    ),
    (
        "General",
        [
            ("Tab / Shift+Tab", "Switch tabs"),
            ("<space>", "Repeat last @/<space> selection"),
            ("#", "Browse xprompts"),
            ("N", "Show notifications"),
            ("y", "Refresh"),
            ("q", "Quit"),
            ("?", "Show this help"),
        ],
    ),
]

TAB_DISPLAY_NAMES = {
    "changespecs": "CLs",
    "agents": "Agents",
    "axe": "Axe",
}

# Column split indices for each tab (left column gets indices < split, right gets >= split)
COLUMN_SPLITS = {
    "changespecs": 2,  # Left: Navigation, CL Actions; Right: rest
    "agents": 3,  # Left: Navigation, Agent Actions, Workflow Folding; Right: rest
    "axe": 3,  # Left: Navigation, BgCmds, Leader Mode; Right: rest
}
