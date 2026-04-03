"""Keymap dataclasses, constants, and key validation for the ace TUI.

Defines the dataclass hierarchy for all configurable keymaps (app-level
bindings and prefix-key modes) along with the constant metadata tables
that describe binding order, display names, and mode associations.
"""

from dataclasses import dataclass, field, fields


# Known Textual named keys (beyond what's in _KEY_DISPLAY).
_NAMED_KEYS: set[str] = {
    "escape",
    "enter",
    "tab",
    "backspace",
    "delete",
    "up",
    "down",
    "left",
    "right",
    "home",
    "end",
    "pageup",
    "pagedown",
    "insert",
    *(f"f{n}" for n in range(1, 25)),
}

# ---------------------------------------------------------------------------
# Binding metadata: (action_name, description, priority)
# Order matches the original hardcoded BINDINGS in app.py.
# ---------------------------------------------------------------------------
_BINDING_META: list[tuple[str, str, bool]] = [
    ("next_changespec", "Next", False),
    ("prev_changespec", "Previous", False),
    ("quit", "Quit", False),
    ("change_status", "Status", False),
    ("run_workflow", "Run", False),
    ("mail", "Mail", False),
    ("show_diff", "Diff", False),
    ("reword", "Reword", False),
    ("add_tag", "Add Tag", False),
    ("view_files", "View", False),
    ("jump_to_entry", "Jump to Entry", False),
    ("hooks_or_collapse", "Hooks / Collapse", False),
    ("hooks_or_collapse_all", "Hooks / Collapse All", False),
    ("start_fold_mode", "Fold", False),
    ("accept_proposal", "Accept", False),
    ("rebase", "Rebase", False),
    ("start_rewind", "Rewind", False),
    ("open_tmux", "Tmux", False),
    ("start_tmux_mode", "Tmux Mode", False),
    ("checkout", "Checkout", False),
    ("start_checkout_mode", "Checkout Mode", False),
    ("refresh", "Refresh", False),
    ("sync", "Sync", False),
    ("edit_query", "Edit Query", False),
    ("edit_spec", "Edit Spec", False),
    ("scroll_detail_down", "Scroll Down", False),
    ("scroll_detail_up", "Scroll Up", False),
    ("scroll_prompt_down", "Scroll Prompt Down", False),
    ("scroll_prompt_up", "Scroll Prompt Up", False),
    ("next_tab", "Next Tab", True),
    ("prev_tab", "Prev Tab", True),
    ("toggle_axe", "Start/Stop Axe", False),
    ("stop_axe_and_quit", "Stop & Quit", False),
    ("start_custom_agent", "Run Agent", False),
    ("start_agent_from_changespec", "Run Agent (CL)", False),
    ("start_bang_mode", "Bang Mode", False),
    ("toggle_mark", "Mark", False),
    ("rename_cl", "Rename", False),
    ("clear_marks", "Unmark All", False),
    ("bulk_change_status", "Bulk Status", False),
    ("show_notifications", "Notifications", False),
    ("pin_agent", "Pin", False),
    ("focus_pinned_panel", "Focus Pinned", False),
    ("kill_agent", "Kill", False),
    ("expand_or_layout", "Expand / Layout", False),
    ("expand_all_folds", "Expand All", False),
    ("toggle_layout", "Layout", False),
    ("toggle_thinking", "Thinking", False),
    ("toggle_thinking_reverse", "Thinking Rev", False),
    ("mark_inactive", "Mark Inactive", False),
    ("mark_inactive_pinned", "Pin Inactive", False),
    ("copy_tab_content", "Copy", False),
    ("scroll_to_top", "Top", False),
    ("scroll_to_bottom", "Bottom", False),
    ("show_help", "Help", False),
    ("browse_xprompts", "XPrompts", False),
    ("prev_query", "Prev Query", False),
    ("next_query", "Next Query", False),
    ("prev_changespec_history", "Prev CL History", False),
    ("next_changespec_history", "Next CL History", False),
    ("start_ancestor_mode", "Ancestor", False),
    ("start_child_mode", "Child", False),
    ("start_sibling_mode", "Sibling", False),
    ("toggle_hide_reverted", "Toggle Reverted", False),
    ("toggle_hide_submitted", "Toggle Submitted", False),
    ("start_leader_mode", "Leader", False),
    ("next_agent_file", "Next File", False),
    ("prev_agent_file", "Prev File", False),
    ("edit_panel", "Edit Panel", False),
    ("reset_file_trim", "Reset Trim", False),
    ("show_all_file_lines", "Show All", False),
    ("jump_to_agent_changespec", "Go to CL", False),
]

# Maps mode name -> the app-level action that activates it.
_MODE_PREFIX_ACTIONS: dict[str, str] = {
    "fold_mode": "start_fold_mode",
    "copy_mode": "copy_tab_content",
    "leader_mode": "start_leader_mode",
    "bang_mode": "start_bang_mode",
}

# Textual special key names -> display characters.
_KEY_DISPLAY: dict[str, str] = {
    "full_stop": ".",
    "exclamation_mark": "!",
    "percent_sign": "%",
    "comma": ",",
    "less_than_sign": "<",
    "greater_than_sign": ">",
    "circumflex_accent": "^",
    "underscore": "_",
    "number_sign": "#",
    "right_square_bracket": "]",
    "left_square_bracket": "[",
    "equals_sign": "=",
    "minus": "-",
    "question_mark": "?",
    "slash": "/",
    "at": "@",
    "space": "Space",
    "tab": "Tab",
    "shift+tab": "Shift+Tab",
    "enter": "Enter",
    "tilde": "~",
    "semicolon": ";",
}


def is_valid_key(key: str) -> bool:
    """Check whether *key* is a recognised Textual key name."""
    if not key:
        return False
    # Single alphanumeric character.
    if len(key) == 1 and key.isalnum():
        return True
    # Entry in _KEY_DISPLAY (known Textual special names).
    if key in _KEY_DISPLAY:
        return True
    # Known named keys.
    if key in _NAMED_KEYS:
        return True
    # ctrl+ or shift+ prefix with a valid suffix.
    if key.startswith(("ctrl+", "shift+")):
        suffix = key.split("+", 1)[1]
        return is_valid_key(suffix)
    return False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AppKeymaps:
    """One field per configurable app-level action.

    No defaults -- all values must come from configuration files
    (``default_config.yml`` or user/plugin overrides).  This ensures
    ``default_config.yml`` is the single source of truth for default
    keybindings and that adding a new field without a config entry is
    caught immediately at startup.
    """

    # Navigation
    next_changespec: str
    prev_changespec: str
    scroll_to_top: str
    scroll_to_bottom: str
    scroll_detail_down: str
    scroll_detail_up: str
    scroll_prompt_down: str
    scroll_prompt_up: str
    prev_changespec_history: str
    next_changespec_history: str
    next_agent_file: str
    prev_agent_file: str
    # Tab switching
    next_tab: str
    prev_tab: str
    # CL actions
    quit: str
    change_status: str
    run_workflow: str
    mail: str
    show_diff: str
    reword: str
    add_tag: str
    view_files: str
    jump_to_entry: str
    edit_spec: str
    rename_cl: str
    # Proposals & sync
    accept_proposal: str
    rebase: str
    start_rewind: str
    sync: str
    refresh: str
    # Fold / collapse
    hooks_or_collapse: str
    hooks_or_collapse_all: str
    expand_or_layout: str
    expand_all_folds: str
    toggle_layout: str
    # Marking
    toggle_mark: str
    clear_marks: str
    bulk_change_status: str
    mark_inactive: str
    mark_inactive_pinned: str
    # Agent / axe
    pin_agent: str
    focus_pinned_panel: str
    kill_agent: str
    toggle_axe: str
    stop_axe_and_quit: str
    start_custom_agent: str
    start_agent_from_changespec: str
    jump_to_agent_changespec: str
    edit_panel: str
    # Thinking panel
    toggle_thinking: str
    toggle_thinking_reverse: str
    # File trim
    reset_file_trim: str
    show_all_file_lines: str
    # Queries
    edit_query: str
    prev_query: str
    next_query: str
    # Display / misc
    toggle_hide_reverted: str
    toggle_hide_submitted: str
    show_notifications: str
    show_help: str
    browse_xprompts: str
    # Workspace mode prefixes
    checkout: str
    start_checkout_mode: str
    open_tmux: str
    start_tmux_mode: str
    # Tree navigation prefixes
    start_ancestor_mode: str
    start_child_mode: str
    start_sibling_mode: str
    # Mode activation prefixes
    start_fold_mode: str
    start_leader_mode: str
    start_bang_mode: str
    copy_tab_content: str


@dataclass
class ModeKeymaps:
    """Generic container for a prefix-key mode."""

    prefix: str = ""
    keys: dict[str, str | dict[str, str]] = field(default_factory=dict)


@dataclass
class FoldModeKeymaps(ModeKeymaps):
    """Typed fields for the built-in fold mode."""

    prefix: str = "z"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "cycle_commits": "c",
            "cycle_hooks": "h",
            "cycle_mentors": "m",
            "cycle_timestamps": "t",
            "toggle_commits": "C",
            "toggle_hooks": "H",
            "toggle_mentors": "M",
            "toggle_timestamps": "T",
            "cycle_all": "z",
            "toggle_all": "Z",
        }
    )


@dataclass
class CopyModeKeymaps(ModeKeymaps):
    """Typed fields for the built-in copy mode (nested per-tab keys)."""

    prefix: str = "percent_sign"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "changespecs": {
                "raw": "percent_sign",
                "with_snapshot": "exclamation_mark",
                "bug": "b",
                "cl_number": "c",
                "name": "n",
                "spec": "p",
                "snapshot": "s",
            },
            "agents": {
                "chat": "c",
                "file_path": "E",
                "prompt": "p",
                "snapshot": "s",
            },
            "axe": {
                "visible": "o",
                "full": "O",
                "snapshot": "s",
            },
        }
    )


@dataclass
class LeaderModeKeymaps(ModeKeymaps):
    """Typed fields for the built-in leader mode."""

    prefix: str = "comma"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "run_cmd": "exclamation_mark",
            "runners": "r",
            "kill_mentors": "M",
            "review_mentors": "m",
            "agent_home": "h",
            "agent_from_cl": "space",
            "kill_and_edit": "x",
            "retry_edit": "r",
            "activity_info": "i",
            "clear_comments": "c",
            "task_queue": "t",
            "prompt_history": "full_stop",
            "prompt_history_cancelled": "greater_than_sign",
        }
    )


@dataclass
class BangModeKeymaps(ModeKeymaps):
    """Typed fields for the built-in bang mode."""

    prefix: str = "exclamation_mark"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "run_cmd": "exclamation_mark",
            "toggle_axe": "x",
        }
    )


# Map of built-in mode names to their typed dataclass constructors.
_BUILTIN_MODE_CLASSES: dict[str, type[ModeKeymaps]] = {
    "fold_mode": FoldModeKeymaps,
    "copy_mode": CopyModeKeymaps,
    "leader_mode": LeaderModeKeymaps,
    "bang_mode": BangModeKeymaps,
}

BUILTIN_MODE_NAMES: frozenset[str] = frozenset(_BUILTIN_MODE_CLASSES)


# ---------------------------------------------------------------------------
# Module-level consistency check
# ---------------------------------------------------------------------------

# Every AppKeymaps field must have a _BINDING_META entry and vice versa.
_BINDING_META_ACTIONS: frozenset[str] = frozenset(a for a, _, _ in _BINDING_META)
_APP_KEYMAP_FIELDS: frozenset[str] = frozenset(f.name for f in fields(AppKeymaps))

if _BINDING_META_ACTIONS != _APP_KEYMAP_FIELDS:
    _only_in_meta = sorted(_BINDING_META_ACTIONS - _APP_KEYMAP_FIELDS)
    _only_in_keymaps = sorted(_APP_KEYMAP_FIELDS - _BINDING_META_ACTIONS)
    _parts: list[str] = []
    if _only_in_meta:
        _parts.append(f"in _BINDING_META but not AppKeymaps: {_only_in_meta}")
    if _only_in_keymaps:
        _parts.append(f"in AppKeymaps but not _BINDING_META: {_only_in_keymaps}")
    raise RuntimeError(f"_BINDING_META / AppKeymaps mismatch — {'; '.join(_parts)}")


@dataclass
class KeymapRegistry:
    """Top-level container for all keymap configuration."""

    app: AppKeymaps
    modes: dict[str, ModeKeymaps] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Ensure built-in modes exist with defaults if not provided.
        for name, cls in _BUILTIN_MODE_CLASSES.items():
            if name not in self.modes:
                self.modes[name] = cls()

    @property
    def fold_mode(self) -> FoldModeKeymaps:
        m = self.modes["fold_mode"]
        assert isinstance(m, FoldModeKeymaps)
        return m

    @property
    def copy_mode(self) -> CopyModeKeymaps:
        m = self.modes["copy_mode"]
        assert isinstance(m, CopyModeKeymaps)
        return m

    @property
    def leader_mode(self) -> LeaderModeKeymaps:
        m = self.modes["leader_mode"]
        assert isinstance(m, LeaderModeKeymaps)
        return m

    @property
    def bang_mode(self) -> BangModeKeymaps:
        m = self.modes["bang_mode"]
        assert isinstance(m, BangModeKeymaps)
        return m
