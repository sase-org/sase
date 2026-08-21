"""Shared helpers and constants for help modal keybinding sections."""

from typing import Literal

from ...keymaps import BUILTIN_MODE_NAMES, KeymapRegistry, key_display_name
from ..numbered_link_keys import NUMBERED_LINK_HELP_KEYS

TabName = Literal["artifacts", "agents", "axe"]

# Box dimensions for consistent formatting
BOX_WIDTH = 57  # Total box width in characters
CONTENT_WIDTH = 50  # Inner content width (BOX_WIDTH - borders)

# Type alias for binding sections
Sections = list[tuple[str, list[tuple[str, str]]]]
_Sections = Sections


def admin_center_opener_help_label() -> str:
    """Return the opener help summary for the active Admin Center catalog."""
    return "Admin Center: 1-6 jump, # back"


PROMPT_INPUT_SECTION: tuple[str, list[tuple[str, str]]] = (
    "Prompt Input",
    [
        ("{{ }} / {% %}", "Jinja highlighting"),
        ("jinja chip", "Parse and unknown-var status"),
        ("{{ / {% / {#", "Auto-pair delimiters"),
        ("Ctrl+T / Ctrl+L", "Reveal/complete / accept"),
        ("Tab / Shift+Tab", "Snippet action else list shift"),
        ("<...>", "Complete raw placeholders"),
        ("Prompt Inputs", "Collect raw <...> on submit"),
        ("Ctrl+L in panel", "Keep placeholder literal"),
        ("Ctrl+D in panel", "Delete saved completion entry"),
        ("#name / #!name", "Auto-open xprompt menu"),
        ("@", "Artifact kinds; Ctrl+T files"),
        ("%model: / %auto: / %effort:", "Auto-open directive values"),
        ("%model:@", "Model aliases only"),
        ("%wait: / #fork:", "Complete agents, real @tribes"),
        ("#@ Ctrl+I", "Inline-expand xprompt"),
        ("#@ Ctrl+O", "Edit definition here (target)"),
        ("K", "Preview xprompt/skill/file/word"),
        ("Ctrl+]", "Jump to xprompt/skill/file/repo"),
        ("K / Ctrl+] on glossary term", "Preview / jump to definition"),
        ("K / Ctrl+] on repo name", "Preview repo / open checkout"),
        ("/ / ?", "Search prompt fwd/rev (NORMAL)"),
        ("n / N", "Repeat prompt search fwd/rev"),
        ("* / #", "Search word under cursor"),
        ("g* / g#", "... as substring"),
        ("Enter / Esc", "Confirm / cancel prompt search"),
        ("gf / Ctrl+G f", "Format current prompt"),
        ("gG / Ctrl+G G", "Glossary panel"),
        ("gm / Ctrl+G m", "Memory panel"),
        ("gT / Ctrl+G T", "Snippets panel"),
        ("g=", "Frontmatter panel"),
        ("q/Esc (panel)", "Return to originating pane"),
        ("gj/gk (panel)", "Top / bottom prompt pane"),
        ("Ctrl+S", "Stash pane (panel if empty)"),
        ("gs / Ctrl+G s", "Stash all panes"),
        ("gx / Ctrl+G x / Ctrl+G Ctrl+X", "Open mini-xprompt pane"),
        ("gt / Ctrl+G t", "New/edit snippet pane"),
        ("gX / Ctrl+G X", "Open xprompt/snippet save panel"),
        ("gL / Ctrl+G L", "Save pane as local xprompt"),
        ("gw / Ctrl+G w", "Save to targeted xprompt"),
        ("Ctrl+G p / @", "Stashed prompts panel"),
        ("Enter", "Submit; chooser when needed"),
        ("g<enter>", "Submit current pane only"),
        ("gj / gk", "Focus prompt panes (NORMAL)"),
        ("gJ / gK", "Move prompt pane (NORMAL)"),
        ("g-", "Add prompt pane"),
    ],
)

ADMIN_CENTER_TASKS_SECTION: tuple[str, list[tuple[str, str]]] = (
    "Admin Center Procs",
    [
        ("j / k", "Move through procs"),
        ("a", "Scope: this session / all"),
        ("K", "Kill selected running proc"),
        ("d / D", "Dismiss done / all done"),
        ("e / y", "Edit / copy proc output"),
        ("Enter", "Open the monitor's agent"),
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
        ("H", "CLI history: this / all"),
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


def glossary_panel_section(
    km: KeymapRegistry,
) -> tuple[str, list[tuple[str, str]]]:
    """Build the Glossary panel keybinding section from configured keys."""
    d = key_display_name
    g = km.glossary
    return (
        "Glossary Panel",
        [
            ("gG / Ctrl+G G", "Open from prompt"),
            (f"{d(g.next_term)} / {d(g.prev_term)}", "Move through terms"),
            (f"{d(g.first_term)} / {d(g.last_term)}", "First / last term"),
            (d(g.filter_terms), "Filter terms / aliases"),
            (d(g.toggle_definition_filter), "Match definition bodies"),
            (f"{d(g.next_relation)} / {d(g.prev_relation)}", "Move relation chip"),
            (d(g.follow_relation), "Follow relation"),
            (NUMBERED_LINK_HELP_KEYS, "Follow numbered chip"),
            (d(g.travel_back), "Walk back along trail"),
            (f"{d(g.next_project)} / {d(g.prev_project)}", "Cycle visible project"),
            (d(g.add_term), "Add a term"),
            (d(g.delete_term), "Delete selected term"),
            (d(g.open_source), "Open source in editor"),
            (d(g.copy_definition), "Copy definition"),
            (d(g.help), "Panel-scoped help"),
            ("Esc", "Close and restore prompt"),
        ],
    )


def memory_panel_section(
    km: KeymapRegistry,
) -> tuple[str, list[tuple[str, str]]]:
    """Build the Memory panel keybinding section from configured keys."""
    d = key_display_name
    m = km.memory
    return (
        "Memory Panel",
        [
            ("gm / Ctrl+G m", "Open from prompt"),
            (f"{d(m.next_note)} / {d(m.prev_note)}", "Move through notes"),
            (f"{d(m.first_note)} / {d(m.last_note)}", "First / last note"),
            (d(m.filter_notes), "Filter notes"),
            (d(m.toggle_body_filter), "Match note bodies"),
            (f"{d(m.next_link)} / {d(m.prev_link)}", "Move link chip"),
            (d(m.follow_link), "Follow link"),
            (NUMBERED_LINK_HELP_KEYS, "Follow numbered chip"),
            (d(m.travel_back), "Walk back along trail"),
            (f"{d(m.next_scope)} / {d(m.prev_scope)}", "Cycle visible scope"),
            (d(m.pick_scope), "Pick a scope"),
            (d(m.add_note), "Add a note"),
            (d(m.edit_note), "Edit selected note"),
            (d(m.delete_note), "Delete selected note"),
            (d(m.publish), "Publish unpublished"),
            (d(m.open_source), "Open source in editor"),
            (d(m.copy_body), "Copy note body"),
            (d(m.help), "Panel-scoped help"),
            ("Esc", "Close and restore prompt"),
        ],
    )


def snippets_panel_section(
    km: KeymapRegistry,
) -> tuple[str, list[tuple[str, str]]]:
    """Build the Snippets panel keybinding section from configured keys."""
    d = key_display_name
    s = km.snippets
    return (
        "Snippets Panel",
        [
            ("gT / Ctrl+G T", "Open from prompt"),
            (f"{d(s.next_snippet)} / {d(s.prev_snippet)}", "Move through snippets"),
            (f"{d(s.first_snippet)} / {d(s.last_snippet)}", "First / last snippet"),
            (d(s.filter_snippets), "Filter triggers / sources"),
            (d(s.toggle_body_filter), "Match template bodies"),
            (f"{d(s.next_relation)} / {d(s.prev_relation)}", "Move relation chip"),
            (d(s.follow_relation), "Follow relation"),
            ("1-9", "Follow numbered chip"),
            (d(s.travel_back), "Walk back along trail"),
            (f"{d(s.next_project)} / {d(s.prev_project)}", "Cycle visible project"),
            (d(s.add_snippet), "Add a snippet"),
            (d(s.edit_snippet), "Edit selected snippet"),
            (d(s.delete_snippet), "Delete selected snippet"),
            (d(s.open_source), "Open source in editor"),
            (d(s.copy_template), "Copy raw template"),
            (d(s.help), "Panel-scoped help"),
            ("Esc", "Close and restore prompt"),
        ],
    )


_custom_mode_sections = custom_mode_sections


TAB_DISPLAY_NAMES = {
    "artifacts": "Artifacts",
    "agents": "Agents",
    "axe": "Axe",
}

# Column split indices for each tab (left column gets indices < split, right gets >= split)
COLUMN_SPLITS = {
    "artifacts": 11,  # Balance artifact panes + PR actions against modes/copy help.
    "agents": 3,  # Left: Navigation, Agent Actions, Workflow Folding; Right: rest
    "axe": 3,  # Left: Navigation, BgCmds, Leader Mode; Right: rest
}
