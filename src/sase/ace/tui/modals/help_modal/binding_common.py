"""Shared helpers and constants for help modal keybinding sections."""

from typing import Literal

from ...keymaps import BUILTIN_MODE_NAMES, KeymapRegistry, key_display_name

TabName = Literal["changespecs", "agents", "axe"]

# Box dimensions for consistent formatting
BOX_WIDTH = 57  # Total box width in characters
CONTENT_WIDTH = 50  # Inner content width (BOX_WIDTH - borders)

# Type alias for binding sections
Sections = list[tuple[str, list[tuple[str, str]]]]
_Sections = Sections

PROMPT_INPUT_SECTION: tuple[str, list[tuple[str, str]]] = (
    "Prompt Input",
    [
        ("{{ }} / {% %}", "Jinja highlighting"),
        ("jinja chip", "Parse and unknown-var status"),
        ("{{ / {% / {#", "Auto-pair delimiters"),
        ("Ctrl+T / Ctrl+L", "Manual completion / accept"),
        ("Tab / Shift+Tab", "Indent / dedent bullet marker"),
        ("<...>", "Complete raw placeholders"),
        ("Prompt Inputs", "Collect raw <...> on submit"),
        ("Ctrl+L in panel", "Keep placeholder literal"),
        ("Ctrl+D in panel", "Delete saved completion entry"),
        ("#name / #!name", "Auto-open xprompt menu"),
        ("%model: / %auto: / %effort:", "Auto-open directive values"),
        ("%model:@", "Model aliases only"),
        ("%wait: / #fork:", "Complete agents, real @tribes"),
        ("#@ Ctrl+I", "Inline-expand xprompt"),
        ("K", "Preview xprompt/skill/file/word"),
        ("Ctrl+]", "Jump to xprompt/skill/file"),
        ("/ / ?", "Search prompt fwd/rev (NORMAL)"),
        ("n / N", "Repeat prompt search fwd/rev"),
        ("Enter / Esc", "Confirm / cancel prompt search"),
        ("gf / Ctrl+G f", "Format current prompt"),
        ("g=", "Frontmatter panel"),
        ("q/Esc (panel)", "Return to originating pane"),
        ("gj/gk (panel)", "Top / bottom prompt pane"),
        ("Ctrl+S", "Stash pane (panel if empty)"),
        ("gs / Ctrl+G s", "Stash all panes"),
        ("gx / Ctrl+G x / Ctrl+G Ctrl+X", "Open xprompt/snippet save panel"),
        ("gX / Ctrl+G X", "Save pane as local xprompt"),
        ("Ctrl+G p / @", "Stashed prompts panel"),
        ("Enter", "Submit (chooser when stacked)"),
        ("g<enter>", "Submit current pane only"),
        ("gj / gk", "Focus prompt panes (NORMAL)"),
        ("gJ / gK", "Move prompt pane (NORMAL)"),
        ("g-", "Add prompt pane"),
    ],
)

ADMIN_CENTER_TASKS_SECTION: tuple[str, list[tuple[str, str]]] = (
    "Admin Center Tasks",
    [
        ("j / k", "Move through tasks"),
        ("a", "Scope: this session / all"),
        ("K", "Kill selected running task"),
        ("d / D", "Dismiss done / all done"),
        ("e / y", "Edit / copy task output"),
        ("Ctrl+D / Ctrl+U, g / G", "Scroll output"),
    ],
)

ADMIN_CENTER_UPDATES_SECTION: tuple[str, list[tuple[str, str]]] = (
    "Admin Center Updates",
    [
        ("Core / Plugins / Agent CLIs", "Three update sub-tabs"),
        ("] / [", "Next / previous sub-tab"),
        ("u", "Update SASE core + plugins"),
        ("A", "Update agent CLIs"),
        ("a", "Full sync all enabled agents repositories"),
        ("Space", "Mark plugin / agent CLI"),
        ("r / o", "Refresh / offline mode"),
    ],
)


def sk(keys: dict[str, str | dict[str, str]], name: str) -> str:
    """Extract a string value from a mode keys dict."""
    v = keys[name]
    assert isinstance(v, str)
    return v


_sk = sk


def key_sequence_display(*keys: str) -> str:
    """Format a prefix-mode sequence for readable help display."""
    parts = [key_display_name(key) for key in keys]
    if all(len(part) == 1 for part in parts):
        return "".join(parts)
    if len(parts) == 2 and len(parts[1]) == 1 and not parts[1].isalnum():
        return "".join(parts)
    return " ".join(parts)


def custom_mode_sections(km: KeymapRegistry) -> Sections:
    """Build help sections for user-defined (non-builtin) custom modes."""
    d = key_display_name
    sections: Sections = []
    for mode_name, mode in km.modes.items():
        if mode_name in BUILTIN_MODE_NAMES:
            continue
        display_name = mode_name.replace("_", " ").title()
        bindings: list[tuple[str, str]] = []
        for action_name, spec in mode.keys.items():
            if not isinstance(spec, dict):
                continue
            key = spec.get("key", "")
            desc = spec.get("description", action_name)
            bindings.append((key_sequence_display(mode.prefix, key), desc))
        if bindings:
            sections.append((f"{display_name} ({d(mode.prefix)})", bindings))
    return sections


_custom_mode_sections = custom_mode_sections


TAB_DISPLAY_NAMES = {
    "changespecs": "Artifacts",
    "agents": "Agents",
    "axe": "Axe",
}

# Column split indices for each tab (left column gets indices < split, right gets >= split)
COLUMN_SPLITS = {
    "changespecs": 2,  # Left: Artifact Sub-tabs, Navigation; Right: PR Actions + rest
    "agents": 3,  # Left: Navigation, Agent Actions, Workflow Folding; Right: rest
    "axe": 3,  # Left: Navigation, BgCmds, Leader Mode; Right: rest
}
