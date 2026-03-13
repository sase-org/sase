"""Keymap registry for the ace TUI.

Defines dataclasses for all configurable keymaps (app-level bindings and
prefix-key modes) and provides a loader that reads from the merged config
system (``default_config.yml`` → plugins → ``sase.yml`` → overlays).
"""

import logging
from dataclasses import dataclass, field, fields

from textual.binding import Binding


log = logging.getLogger(__name__)

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
    ("kill_agent", "Kill", False),
    ("expand_or_layout", "Expand / Layout", False),
    ("expand_all_folds", "Expand All", False),
    ("toggle_layout", "Layout", False),
    ("toggle_thinking", "Thinking", False),
    ("toggle_thinking_reverse", "Thinking Rev", False),
    ("mark_inactive", "Mark Inactive", False),
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
    ("start_leader_mode", "Leader", False),
    ("next_agent_file", "Next File", False),
    ("prev_agent_file", "Prev File", False),
    ("edit_panel", "Edit Panel", False),
    ("reset_file_trim", "Reset Trim", False),
    ("show_all_file_lines", "Show All", False),
    ("jump_to_agent_changespec", "Go to CL", False),
]

# Maps mode name → the app-level action that activates it.
_MODE_PREFIX_ACTIONS: dict[str, str] = {
    "fold_mode": "start_fold_mode",
    "copy_mode": "copy_tab_content",
    "leader_mode": "start_leader_mode",
    "bang_mode": "start_bang_mode",
}

# Textual special key names → display characters.
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


def _is_valid_key(key: str) -> bool:
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
        return _is_valid_key(suffix)
    return False


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class _AppKeymaps:
    """One field per configurable app-level action; defaults match the
    original hardcoded BINDINGS in ``app.py``."""

    # Navigation
    next_changespec: str = "j"
    prev_changespec: str = "k"
    scroll_to_top: str = "g"
    scroll_to_bottom: str = "G"
    scroll_detail_down: str = "ctrl+d"
    scroll_detail_up: str = "ctrl+u"
    scroll_prompt_down: str = "ctrl+f"
    scroll_prompt_up: str = "ctrl+b"
    prev_changespec_history: str = "ctrl+o"
    next_changespec_history: str = "ctrl+k"
    next_agent_file: str = "ctrl+n"
    prev_agent_file: str = "ctrl+p"
    # Tab switching
    next_tab: str = "tab"
    prev_tab: str = "shift+tab"
    # CL actions
    quit: str = "q"
    change_status: str = "s"
    run_workflow: str = "r"
    mail: str = "M"
    show_diff: str = "d"
    reword: str = "w"
    add_tag: str = "W"
    view_files: str = "v"
    edit_spec: str = "e"
    rename_cl: str = "n"
    # Proposals & sync
    accept_proposal: str = "a"
    rebase: str = "b"
    start_rewind: str = "R"
    sync: str = "Y"
    refresh: str = "y"
    # Fold / collapse
    hooks_or_collapse: str = "h"
    hooks_or_collapse_all: str = "H"
    expand_or_layout: str = "l"
    expand_all_folds: str = "L"
    toggle_layout: str = "p"
    # Marking
    toggle_mark: str = "m"
    clear_marks: str = "u"
    bulk_change_status: str = "S"
    mark_inactive: str = "i"
    # Agent / axe
    kill_agent: str = "x"
    toggle_axe: str = "X"
    stop_axe_and_quit: str = "Q"
    start_custom_agent: str = "at"
    start_agent_from_changespec: str = "space"
    jump_to_agent_changespec: str = "enter"
    edit_panel: str = "E"
    # Thinking panel
    toggle_thinking: str = "right_square_bracket"
    toggle_thinking_reverse: str = "left_square_bracket"
    # File trim
    reset_file_trim: str = "minus"
    show_all_file_lines: str = "equals_sign"
    # Queries
    edit_query: str = "slash"
    prev_query: str = "circumflex_accent"
    next_query: str = "underscore"
    # Display / misc
    toggle_hide_reverted: str = "full_stop"
    show_notifications: str = "N"
    show_help: str = "question_mark"
    browse_xprompts: str = "number_sign"
    # Workspace mode prefixes
    checkout: str = "C"
    start_checkout_mode: str = "c"
    open_tmux: str = "T"
    start_tmux_mode: str = "t"
    # Tree navigation prefixes
    start_ancestor_mode: str = "<"
    start_child_mode: str = ">"
    start_sibling_mode: str = "~"
    # Mode activation prefixes
    start_fold_mode: str = "z"
    start_leader_mode: str = "comma"
    start_bang_mode: str = "exclamation_mark"
    copy_tab_content: str = "percent_sign"


@dataclass
class _ModeKeymaps:
    """Generic container for a prefix-key mode."""

    prefix: str = ""
    keys: dict[str, str | dict[str, str]] = field(default_factory=dict)


@dataclass
class _FoldModeKeymaps(_ModeKeymaps):
    """Typed fields for the built-in fold mode."""

    prefix: str = "z"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "cycle_commits": "c",
            "cycle_hooks": "h",
            "cycle_mentors": "m",
            "cycle_all": "z",
        }
    )


@dataclass
class _CopyModeKeymaps(_ModeKeymaps):
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
class _LeaderModeKeymaps(_ModeKeymaps):
    """Typed fields for the built-in leader mode."""

    prefix: str = "comma"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "run_cmd": "exclamation_mark",
            "runners": "r",
            "kill_mentors": "m",
            "agent_home": "h",
            "agent_from_cl": "space",
        }
    )


@dataclass
class _BangModeKeymaps(_ModeKeymaps):
    """Typed fields for the built-in bang mode."""

    prefix: str = "exclamation_mark"
    keys: dict[str, str | dict[str, str]] = field(
        default_factory=lambda: {
            "run_cmd": "exclamation_mark",
            "toggle_axe": "x",
        }
    )


# Map of built-in mode names to their typed dataclass constructors.
_BUILTIN_MODE_CLASSES: dict[str, type[_ModeKeymaps]] = {
    "fold_mode": _FoldModeKeymaps,
    "copy_mode": _CopyModeKeymaps,
    "leader_mode": _LeaderModeKeymaps,
    "bang_mode": _BangModeKeymaps,
}

BUILTIN_MODE_NAMES: frozenset[str] = frozenset(_BUILTIN_MODE_CLASSES)


@dataclass
class KeymapRegistry:
    """Top-level container for all keymap configuration."""

    app: _AppKeymaps = field(default_factory=_AppKeymaps)
    modes: dict[str, _ModeKeymaps] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Ensure built-in modes exist with defaults if not provided.
        for name, cls in _BUILTIN_MODE_CLASSES.items():
            if name not in self.modes:
                self.modes[name] = cls()

    @property
    def fold_mode(self) -> _FoldModeKeymaps:
        m = self.modes["fold_mode"]
        assert isinstance(m, _FoldModeKeymaps)
        return m

    @property
    def copy_mode(self) -> _CopyModeKeymaps:
        m = self.modes["copy_mode"]
        assert isinstance(m, _CopyModeKeymaps)
        return m

    @property
    def leader_mode(self) -> _LeaderModeKeymaps:
        m = self.modes["leader_mode"]
        assert isinstance(m, _LeaderModeKeymaps)
        return m

    @property
    def bang_mode(self) -> _BangModeKeymaps:
        m = self.modes["bang_mode"]
        assert isinstance(m, _BangModeKeymaps)
        return m


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _deep_merge_keys(
    defaults: dict[str, str | dict[str, str]],
    overrides: dict[str, str | dict[str, str]],
) -> dict[str, str | dict[str, str]]:
    """Merge mode key overrides into defaults, handling nested dicts."""
    result = dict(defaults)
    for k, v in overrides.items():
        if isinstance(v, dict) and isinstance(result.get(k), dict):
            existing = result[k]
            assert isinstance(existing, dict)  # guarded above
            result[k] = {**existing, **v}
        else:
            result[k] = v
    return result


def load_keymap_registry(ace_cfg: dict) -> KeymapRegistry:
    """Build a ``KeymapRegistry`` from the ``ace`` config section.

    Args:
        ace_cfg: The ``ace`` dict from the merged config (may be empty).

    Returns:
        Fully populated registry with defaults for any missing keys.
    """
    keymaps_cfg = ace_cfg.get("keymaps", {})
    if not isinstance(keymaps_cfg, dict):
        return KeymapRegistry()

    # --- App keymaps ---
    app_overrides = keymaps_cfg.get("app", {})
    if not isinstance(app_overrides, dict):
        app_overrides = {}

    app_defaults = _AppKeymaps()
    app_field_names = {f.name for f in fields(_AppKeymaps)}
    app_kwargs: dict[str, str] = {}
    for fname in app_field_names:
        if fname in app_overrides and isinstance(app_overrides[fname], str):
            app_kwargs[fname] = app_overrides[fname]
        else:
            app_kwargs[fname] = getattr(app_defaults, fname)

    # --- Validate user-overridden keys ---
    user_overridden = {
        fname
        for fname in app_field_names
        if fname in app_overrides
        and isinstance(app_overrides[fname], str)
        and app_overrides[fname] != getattr(app_defaults, fname)
    }

    # Invalid key validation: revert unrecognised keys to defaults.
    for fname in sorted(user_overridden):
        if not _is_valid_key(app_kwargs[fname]):
            log.warning(
                "Invalid key %r for action %r; reverting to default %r",
                app_kwargs[fname],
                fname,
                getattr(app_defaults, fname),
            )
            app_kwargs[fname] = getattr(app_defaults, fname)
            user_overridden.discard(fname)

    # Duplicate key detection: revert user overrides that conflict.
    key_to_actions: dict[str, list[str]] = {}
    for fname, key_val in app_kwargs.items():
        key_to_actions.setdefault(key_val, []).append(fname)

    for key_val, actions in key_to_actions.items():
        if len(actions) <= 1:
            continue
        overridden = [a for a in actions if a in user_overridden]
        if not overridden:
            continue
        for fname in overridden:
            default_val = getattr(app_defaults, fname)
            log.warning(
                "Duplicate key %r: action %r conflicts with %s; "
                "reverting to default %r",
                key_val,
                fname,
                [a for a in actions if a != fname],
                default_val,
            )
            app_kwargs[fname] = default_val

    app_km = _AppKeymaps(**app_kwargs)

    # --- Mode keymaps ---
    modes_cfg = keymaps_cfg.get("modes", {})
    if not isinstance(modes_cfg, dict):
        modes_cfg = {}

    modes: dict[str, _ModeKeymaps] = {}
    # Process built-in modes first (ensure they always exist).
    for mode_name, cls in _BUILTIN_MODE_CLASSES.items():
        mode_defaults = cls()
        mode_overrides = modes_cfg.get(mode_name, {})
        if not isinstance(mode_overrides, dict):
            modes[mode_name] = mode_defaults
            continue

        prefix = mode_overrides.get("prefix", mode_defaults.prefix)
        if not isinstance(prefix, str):
            prefix = mode_defaults.prefix

        keys_overrides = mode_overrides.get("keys", {})
        if not isinstance(keys_overrides, dict):
            keys_overrides = {}

        merged_keys = _deep_merge_keys(mode_defaults.keys, keys_overrides)
        modes[mode_name] = cls(prefix=prefix, keys=merged_keys)

    # Process any additional (user-defined) modes.
    for mode_name, mode_data in modes_cfg.items():
        if mode_name in _BUILTIN_MODE_CLASSES:
            continue  # Already handled above.
        if not isinstance(mode_data, dict):
            continue
        prefix = mode_data.get("prefix", "")
        if not isinstance(prefix, str):
            continue
        raw_keys = mode_data.get("keys", {})
        keys: dict[str, str | dict[str, str]] = {}
        if isinstance(raw_keys, dict):
            for k, v in raw_keys.items():
                if not isinstance(v, dict):
                    # Custom mode sub-keys must be dicts with key/shell/action.
                    log.warning(
                        "Custom mode %r sub-key %r: expected dict, got %s; skipping",
                        mode_name,
                        k,
                        type(v).__name__,
                    )
                    continue
                if "key" not in v:
                    log.warning(
                        "Custom mode %r sub-key %r: missing 'key' field; skipping",
                        mode_name,
                        k,
                    )
                    continue
                if "shell" not in v and "action" not in v:
                    log.warning(
                        "Custom mode %r sub-key %r: missing 'shell' or 'action'; "
                        "skipping",
                        mode_name,
                        k,
                    )
                    continue
                keys[k] = {sk: sv for sk, sv in v.items() if isinstance(sv, str)}
        modes[mode_name] = _ModeKeymaps(prefix=prefix, keys=keys)

    registry = KeymapRegistry(app=app_km, modes=modes)

    # --- Prefix sync: mode prefix wins over app action ---
    for mode_name, action_name in _MODE_PREFIX_ACTIONS.items():
        mode = registry.modes.get(mode_name)
        if mode is None:
            continue
        app_key = getattr(registry.app, action_name, None)
        if app_key != mode.prefix:
            log.warning(
                "Mode %s prefix %r differs from app.%s %r; using mode prefix",
                mode_name,
                mode.prefix,
                action_name,
                app_key,
            )
            setattr(registry.app, action_name, mode.prefix)

    # --- Prefix conflict detection for custom modes ---
    # Warn if a custom mode's prefix collides with an app binding.
    app_keys: set[str] = {getattr(registry.app, f.name) for f in fields(_AppKeymaps)}
    for mode_name, mode in registry.modes.items():
        if mode_name in _BUILTIN_MODE_CLASSES:
            continue
        if mode.prefix and mode.prefix in app_keys:
            log.warning(
                "Custom mode %r prefix %r conflicts with an existing app binding; "
                "the prefix key will activate the custom mode instead",
                mode_name,
                mode.prefix,
            )

    return registry


# ---------------------------------------------------------------------------
# Binding builder
# ---------------------------------------------------------------------------

# Non-configurable digit bindings for saved queries.
_DIGIT_BINDINGS: list[Binding] = [
    Binding(str(d), f"load_saved_query_{d}", f"Load Q{d}", show=False)
    for d in [1, 2, 3, 4, 5, 6, 7, 8, 9, 0]
]


def build_app_bindings(app_km: _AppKeymaps) -> list[Binding]:
    """Generate the Textual ``Binding`` list from an ``AppKeymaps`` instance.

    Preserves the original binding order, descriptions, and priority flags.
    Appends the 10 non-configurable digit bindings for saved queries.

    Returns:
        List of ``Binding`` objects suitable for ``App.BINDINGS``.
    """
    bindings: list[Binding] = []
    for action, desc, priority in _BINDING_META:
        key = getattr(app_km, action)
        bindings.append(Binding(key, action, desc, show=False, priority=priority))
    bindings.extend(_DIGIT_BINDINGS)
    return bindings


# ---------------------------------------------------------------------------
# Display helper
# ---------------------------------------------------------------------------


def key_display_name(textual_key: str) -> str:
    """Convert a Textual key name to a human-readable display string.

    Examples:
        ``"full_stop"`` → ``"."``
        ``"ctrl+d"`` → ``"Ctrl+D"``
        ``"j"`` → ``"j"``
    """
    if textual_key in _KEY_DISPLAY:
        return _KEY_DISPLAY[textual_key]
    if textual_key.startswith("ctrl+"):
        return f"Ctrl+{textual_key[5:].upper()}"
    return textual_key


def footer_key_display(textual_key: str) -> str:
    """Convert a Textual key name for footer display.

    Wraps ``key_display_name`` and applies the footer's angle-bracket
    convention for multi-char named keys (``"Space"`` → ``"<space>"``,
    ``"Enter"`` → ``"<enter>"``).  Single chars and ``Ctrl+X`` /
    ``Shift+X`` pass through unchanged.
    """
    name = key_display_name(textual_key)
    if len(name) == 1 or name.startswith(("Ctrl+", "Shift+")):
        return name
    return f"<{name.lower()}>"
