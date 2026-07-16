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
    ("jump_to_entry_fast", "Fast Jump", False),
    ("jump_to_entry_forward", "Forward Jump", False),
    ("jump_to_all_entries", "Jump All", False),
    ("hooks_or_collapse", "Hooks / Collapse", False),
    ("hooks_or_collapse_all", "Collapse Panel / All", False),
    ("edit_hooks", "Edit Hooks", False),
    ("start_fold_mode", "Fold", False),
    ("zoom_panel", "Zoom", False),
    ("plans_approve", "Approve Plan", False),
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
    ("open_saved_query_picker", "Saved Queries", False),
    ("edit_spec", "Edit Spec", False),
    ("scroll_detail_down", "Scroll Down", False),
    ("scroll_detail_up", "Scroll Up", False),
    ("scroll_prompt_down", "Scroll Prompt Down", False),
    ("scroll_prompt_up", "Scroll Prompt Up", False),
    ("next_agent_metadata_section", "Next Metadata Section", False),
    ("prev_agent_metadata_section", "Previous Metadata Section", False),
    ("next_tab", "Next Tab", True),
    ("prev_tab", "Prev Tab", True),
    ("cycle_artifacts_subtab", "Next Artifact", False),
    ("cycle_artifacts_subtab_reverse", "Previous Artifact", False),
    ("pick_artifacts_project", "Project Scope", False),
    ("commits_next", "Next Commit", False),
    ("commits_prev", "Previous Commit", False),
    ("commits_view_selected", "View Commit", False),
    ("commits_copy_sha", "Copy Commit SHA", False),
    ("commits_filters", "Commit Filters", False),
    ("commits_toggle_sdd", "Toggle Commit SDD", False),
    ("commits_toggle_all_projects", "Toggle All Projects", False),
    ("commits_fetch", "Fetch Commits", False),
    ("commits_refresh", "Refresh Commits", False),
    ("plans_next", "Next Plan", False),
    ("plans_prev", "Previous Plan", False),
    ("plans_view_selected", "View Plan", False),
    ("plans_expand", "Expand Epic", False),
    ("plans_collapse", "Collapse Epic", False),
    ("plans_cycle_status", "Bead Status", False),
    ("plans_edit_bead", "Edit Bead", False),
    ("plans_launch_epic", "Launch Epic", False),
    ("plans_reject", "Reject Plan", False),
    ("plans_open_bug", "Open Bug", False),
    ("plans_refresh", "Refresh Plans", False),
    ("next_bug", "Next Bug", False),
    ("prev_bug", "Previous Bug", False),
    ("cycle_bug_filter", "Bug State Filter", False),
    ("create_bug", "Create Bug", False),
    ("edit_bug", "Edit Bug", False),
    ("toggle_bug_state", "Close / Reopen Bug", False),
    ("open_bug", "Open Bug", False),
    ("copy_bug", "Copy Bug", False),
    ("start_agent_from_bug", "Run Agent (Bug)", False),
    ("focus_bug_links", "Bug Links", False),
    ("activate_bug_link", "Open Bug Link", True),
    ("refresh_bugs", "Refresh Bugs", False),
    ("open_agent_cleanup_panel", "Agent Cleanup", False),
    ("stop_axe_and_quit", "Quit / Restart", False),
    ("start_custom_agent", "Run Agent", False),
    ("start_agent_home", "Run Agent (Home)", False),
    ("start_agent_from_changespec", "Run Agent (PR)", False),
    ("start_last_vcs_xprompt_in_editor", "Edit Last VCS XPrompt", False),
    ("restore_prompt_stash", "Restore Prompt Stash", False),
    ("start_bang_mode", "Bang Mode", False),
    ("toggle_mark", "Mark", False),
    ("rename_cl", "Rename", False),
    ("clear_marks", "Unmark All", False),
    ("bulk_change_status", "Bulk Status", False),
    ("save_marked_agents", "Save Marked Agents", False),
    ("show_notifications", "Notifications", False),
    ("kill_agent", "Kill", False),
    ("expand_or_layout", "Expand / Layout", False),
    ("expand_all_folds", "Expand Panel / All", False),
    ("toggle_layout", "Layout", False),
    ("toggle_thinking", "Tools", False),
    ("toggle_thinking_reverse", "Tools Rev", False),
    ("copy_tab_content", "Copy", False),
    ("scroll_to_top", "Top", False),
    ("scroll_to_bottom", "Bottom", False),
    ("show_help", "Help", False),
    ("open_config_center", "SASE Admin Center", False),
    ("prev_query", "Prev Query", False),
    ("next_query", "Next Query", False),
    ("start_ancestor_mode", "Ancestor", False),
    ("start_child_mode", "Child", False),
    ("start_sibling_mode", "Sibling", False),
    ("toggle_hide_reverted", "Toggle Reverted", False),
    ("toggle_hide_submitted", "Toggle Submitted", False),
    ("start_leader_mode", "Leader", False),
    ("next_agent_file", "Next File", False),
    ("prev_agent_file", "Prev File", False),
    ("edit_panel", "Edit Panel", False),
    ("jump_to_agent_changespec", "Go to PR", False),
    ("open_agent_artifacts", "Artifacts", False),
    ("toggle_attempt_view", "Toggle Attempt View", False),
    ("toggle_agent_unread", "Toggle Agent Unread", False),
    ("add_agent_tag", "Add Agent Tag", False),
    ("focus_next_agent_panel", "Next Panel", False),
    ("focus_prev_agent_panel", "Prev Panel", False),
    ("cycle_grouping_mode", "Cycle Grouping", False),
    ("cycle_grouping_mode_reverse", "Cycle Grouping Rev", False),
    ("show_agent_run_log", "Agent Run Log", False),
    ("open_command_palette", "Command Palette", False),
    ("dismiss_toasts", "Dismiss Toasts", False),
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
    "apostrophe": "'",
    "grave_accent": "`",
    "slash": "/",
    "asterisk": "*",
    "at": "@",
    "plus": "+",
    "space": "Space",
    "tab": "Tab",
    "shift+tab": "Shift+Tab",
    "enter": "Enter",
    "tilde": "~",
    "semicolon": ";",
    "colon": ":",
}

_CTRL_SPACE_KEY = "ctrl+@"
_KEY_ALIASES: dict[str, str] = {
    "ctrl+space": _CTRL_SPACE_KEY,
    "ctrl+at": _CTRL_SPACE_KEY,
    # Textual normalizes the printable ``+`` key to the name ``plus``; accept
    # the raw glyph and the Unicode name as friendly config spellings for it.
    "+": "plus",
    "plus_sign": "plus",
}


def split_key_alternatives(key: str) -> tuple[str, ...]:
    """Split a Textual binding string into its comma-separated alternatives."""
    return tuple(part.strip() for part in key.split(","))


def canonicalize_single_key(key: str) -> str:
    """Return the internal Textual key spelling for one configured key."""
    key = key.strip()
    return _KEY_ALIASES.get(key.lower(), key)


def canonicalize_key_binding(key: str) -> str:
    """Canonicalize every alternative in a Textual key binding string."""
    return ",".join(
        canonicalize_single_key(alternative)
        for alternative in split_key_alternatives(key)
    )


def normalize_key_binding(key: str) -> str:
    """Normalize whitespace and aliases around comma-separated key alternatives."""
    return canonicalize_key_binding(key)


def _canonical_key_alternatives(key: str) -> tuple[str, ...]:
    """Split and canonicalize a Textual binding string."""
    return tuple(canonicalize_single_key(part) for part in split_key_alternatives(key))


def _is_valid_single_key(key: str) -> bool:
    """Check whether *key* is a recognised single Textual key name."""
    if not key:
        return False
    if key == _CTRL_SPACE_KEY:
        return True
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
        return _is_valid_single_key(suffix)
    return False


def is_valid_key(key: str) -> bool:
    """Check whether *key* is a recognised Textual key binding.

    Textual ``Binding`` accepts comma-separated alternatives such as
    ``"colon,semicolon"``. Treat those as a single configurable binding
    whose individual alternatives must each be valid Textual keys.
    """
    alternatives = _canonical_key_alternatives(key)
    return (
        bool(alternatives)
        and len(set(alternatives)) == len(alternatives)
        and all(_is_valid_single_key(alternative) for alternative in alternatives)
    )


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
    next_agent_metadata_section: str
    prev_agent_metadata_section: str
    next_agent_file: str
    prev_agent_file: str
    # Tab switching
    next_tab: str
    prev_tab: str
    cycle_artifacts_subtab: str
    cycle_artifacts_subtab_reverse: str
    pick_artifacts_project: str
    # Commits sub-tab
    commits_next: str
    commits_prev: str
    commits_view_selected: str
    commits_copy_sha: str
    commits_filters: str
    commits_toggle_sdd: str
    commits_toggle_all_projects: str
    commits_fetch: str
    commits_refresh: str
    # Plans sub-tab
    plans_next: str
    plans_prev: str
    plans_view_selected: str
    plans_expand: str
    plans_collapse: str
    plans_cycle_status: str
    plans_edit_bead: str
    plans_launch_epic: str
    plans_approve: str
    plans_reject: str
    plans_open_bug: str
    plans_refresh: str
    # Bugs sub-tab
    next_bug: str
    prev_bug: str
    cycle_bug_filter: str
    create_bug: str
    edit_bug: str
    toggle_bug_state: str
    open_bug: str
    copy_bug: str
    start_agent_from_bug: str
    focus_bug_links: str
    activate_bug_link: str
    refresh_bugs: str
    # ChangeSpec actions
    quit: str
    change_status: str
    run_workflow: str
    mail: str
    show_diff: str
    reword: str
    add_tag: str
    view_files: str
    jump_to_entry: str
    jump_to_entry_fast: str
    jump_to_entry_forward: str
    jump_to_all_entries: str
    edit_spec: str
    rename_cl: str
    # ChangeSpec edits
    edit_hooks: str
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
    save_marked_agents: str
    # Agent / axe
    kill_agent: str
    open_agent_cleanup_panel: str
    stop_axe_and_quit: str
    start_custom_agent: str
    start_agent_home: str
    start_agent_from_changespec: str
    start_last_vcs_xprompt_in_editor: str
    restore_prompt_stash: str
    jump_to_agent_changespec: str
    edit_panel: str
    show_agent_run_log: str
    open_agent_artifacts: str
    toggle_attempt_view: str
    toggle_agent_unread: str
    add_agent_tag: str
    focus_next_agent_panel: str
    focus_prev_agent_panel: str
    # Grouping mode cycle (agents tab)
    cycle_grouping_mode: str
    cycle_grouping_mode_reverse: str
    # Tools panel
    toggle_thinking: str
    toggle_thinking_reverse: str
    # Queries
    edit_query: str
    open_saved_query_picker: str
    prev_query: str
    next_query: str
    # Display / misc
    toggle_hide_reverted: str
    toggle_hide_submitted: str
    show_notifications: str
    show_help: str
    open_config_center: str
    open_command_palette: str
    dismiss_toasts: str
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
    zoom_panel: str
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
            "cycle_deltas": "d",
            "toggle_commits": "C",
            "toggle_hooks": "H",
            "toggle_mentors": "M",
            "toggle_timestamps": "T",
            "toggle_deltas": "D",
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
                "pr_number": "c",
                "name": "n",
                "spec": "p",
                "snapshot": "s",
            },
            "agents": {
                "chat": "c",
                "file_path": "E",
                "name": "n",
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
            "repeat_last": "comma",
            "run_cmd": "exclamation_mark",
            "runners": "R",
            "revert_agent": "r",
            "kill_mentors": "M",
            "review_mentors": "C",
            "agent_home": "h",
            "agent_from_cl": "space",
            "toggle_agent_panel_grouping": "g",
            "toggle_selected_agent_panels": "H",
            "jump_to_next_unread_done_agent": "j",
            "jump_to_next_stopped_agent": "J",
            "full_history_refresh": "y",
            "mark_all_unread_done_agents_read": "u",
            "kill_and_edit": "x",
            "clear_comments": "c",
            "open_prompt_stash": "at",
            "prompt_history": "full_stop",
            "prompt_history_edit_first": "ctrl+g",
            "prompt_history_cancelled": "greater_than_sign",
            "agent_run_log": "A",
            "models_panel": "m",
            "update_sase": "U",
            "capture_agents_repro": "B",
            "toggle_agents_repro_checks": "T",
            "jump_to_notification": "n",
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
