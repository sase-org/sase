"""Tests for the ace TUI keymap registry."""

from dataclasses import fields

from sase.ace.tui.keymaps import (
    AppKeymaps,
    BangModeKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    KeymapRegistry,
    LeaderModeKeymaps,
    ModeKeymaps,
    _BINDING_META,
    build_app_bindings,
    key_display_name,
    load_builtin_app_defaults,
    load_keymap_registry,
)


def _default_app_keymaps(**overrides: str) -> AppKeymaps:
    """Create an AppKeymaps using builtin defaults, with optional overrides."""
    kwargs = load_builtin_app_defaults()
    kwargs.update(overrides)
    return AppKeymaps(**kwargs)


# --- load_keymap_registry ---


def test_empty_config_uses_builtin_defaults() -> None:
    """Empty config uses defaults from default_config.yml."""
    reg = load_keymap_registry({})
    assert reg.app.next_changespec == "j"
    assert reg.app.quit == "q"
    assert reg.app.next_tab == "tab"
    assert isinstance(reg.fold_mode, FoldModeKeymaps)
    assert isinstance(reg.copy_mode, CopyModeKeymaps)
    assert isinstance(reg.leader_mode, LeaderModeKeymaps)
    assert isinstance(reg.bang_mode, BangModeKeymaps)


def test_partial_app_override() -> None:
    """Overriding one app key preserves all other defaults."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_changespec": "f"}}})
    assert reg.app.next_changespec == "f"
    assert reg.app.prev_changespec == "k"  # unchanged
    assert reg.app.quit == "q"  # unchanged


def test_partial_mode_override() -> None:
    """Overriding one mode key preserves other mode defaults."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "keys": {"cycle_commits": "x"},
                    },
                },
            },
        }
    )
    assert reg.fold_mode.keys["cycle_commits"] == "x"
    assert reg.fold_mode.keys["cycle_hooks"] == "h"  # unchanged
    assert reg.fold_mode.prefix == "z"  # unchanged


def test_mode_prefix_override() -> None:
    """Overriding a mode prefix also updates the app action key."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {"prefix": "Z"},
                },
            },
        }
    )
    assert reg.fold_mode.prefix == "Z"
    assert reg.app.start_fold_mode == "Z"  # synced


def test_prefix_sync_mode_wins() -> None:
    """When app action and mode prefix differ, mode prefix wins."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {"start_fold_mode": "F"},
                "modes": {"fold_mode": {"prefix": "Z"}},
            },
        }
    )
    # Mode prefix wins
    assert reg.app.start_fold_mode == "Z"
    assert reg.fold_mode.prefix == "Z"


def test_copy_mode_nested_defaults() -> None:
    """Copy mode preserves nested per-tab key structure."""
    reg = load_keymap_registry({})
    keys = reg.copy_mode.keys
    assert isinstance(keys["changespecs"], dict)
    assert keys["changespecs"]["raw"] == "percent_sign"
    assert keys["changespecs"]["bug"] == "b"
    assert isinstance(keys["agents"], dict)
    assert keys["agents"]["chat"] == "c"
    assert isinstance(keys["axe"], dict)
    assert keys["axe"]["visible"] == "o"


def test_copy_mode_nested_override() -> None:
    """Partial override of nested copy mode keys merges correctly."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "copy_mode": {
                        "keys": {
                            "changespecs": {"bug": "B"},
                        },
                    },
                },
            },
        }
    )
    cs_keys = reg.copy_mode.keys["changespecs"]
    assert isinstance(cs_keys, dict)
    assert cs_keys["bug"] == "B"  # overridden
    assert cs_keys["raw"] == "percent_sign"  # unchanged


def test_unknown_mode_becomes_generic() -> None:
    """User-defined modes produce generic ModeKeymaps instances."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "my_mode": {
                        "prefix": "semicolon",
                        "keys": {
                            "do_thing": {
                                "key": "t",
                                "shell": "echo hi",
                                "description": "Do thing",
                            },
                            "do_other": {
                                "key": "o",
                                "action": "refresh",
                                "description": "Do other",
                            },
                        },
                    },
                },
            },
        }
    )
    m = reg.modes["my_mode"]
    assert isinstance(m, ModeKeymaps)
    assert not isinstance(m, FoldModeKeymaps)
    assert m.prefix == "semicolon"
    assert isinstance(m.keys["do_thing"], dict)
    assert m.keys["do_thing"]["key"] == "t"


def test_non_dict_keymaps_config() -> None:
    """Non-dict keymaps config falls back to builtin defaults."""
    reg = load_keymap_registry({"keymaps": "invalid"})
    assert reg.app.next_changespec == "j"
    assert isinstance(reg.fold_mode, FoldModeKeymaps)


# --- build_app_bindings ---


def test_build_app_bindings_count() -> None:
    """build_app_bindings produces 71 configurable + 10 digit = 81 bindings."""
    bindings = build_app_bindings(_default_app_keymaps())
    assert len(bindings) == 81


def test_build_app_bindings_priority() -> None:
    """next_tab and prev_tab have priority=True, others don't."""
    bindings = build_app_bindings(_default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["next_tab"].priority is True
    assert by_action["prev_tab"].priority is True
    assert by_action["next_changespec"].priority is False
    assert by_action["quit"].priority is False


def test_build_app_bindings_uses_config_keys() -> None:
    """Bindings reflect overridden keys from AppKeymaps."""
    km = _default_app_keymaps(next_changespec="n", quit="Q")
    bindings = build_app_bindings(km)
    by_action = {b.action: b for b in bindings}
    assert by_action["next_changespec"].key == "n"
    assert by_action["quit"].key == "Q"


def test_build_app_bindings_digit_keys() -> None:
    """Digit bindings 0-9 are always appended."""
    bindings = build_app_bindings(_default_app_keymaps())
    digit_actions = [b for b in bindings if b.action.startswith("load_saved_query")]
    assert len(digit_actions) == 10
    digit_keys = {b.key for b in digit_actions}
    assert digit_keys == {str(d) for d in range(10)}


# --- key_display_name ---


def test_key_display_special_keys() -> None:
    """Special Textual key names are mapped to display characters."""
    assert key_display_name("full_stop") == "."
    assert key_display_name("exclamation_mark") == "!"
    assert key_display_name("percent_sign") == "%"
    assert key_display_name("comma") == ","
    assert key_display_name("right_square_bracket") == "]"
    assert key_display_name("left_square_bracket") == "["
    assert key_display_name("question_mark") == "?"
    assert key_display_name("slash") == "/"
    assert key_display_name("minus") == "-"
    assert key_display_name("equals_sign") == "="


def test_key_display_ctrl_keys() -> None:
    """Ctrl key combos are formatted as Ctrl+X."""
    assert key_display_name("ctrl+d") == "Ctrl+D"
    assert key_display_name("ctrl+u") == "Ctrl+U"
    assert key_display_name("ctrl+f") == "Ctrl+F"


def test_key_display_passthrough() -> None:
    """Single character keys pass through unchanged."""
    assert key_display_name("j") == "j"
    assert key_display_name("k") == "k"
    assert key_display_name("q") == "q"
    assert key_display_name("G") == "G"


# --- KeymapRegistry defaults ---


def test_registry_default_modes_always_present() -> None:
    """KeymapRegistry always has all four built-in modes."""
    reg = KeymapRegistry(app=_default_app_keymaps())
    assert "fold_mode" in reg.modes
    assert "copy_mode" in reg.modes
    assert "leader_mode" in reg.modes
    assert "bang_mode" in reg.modes


# --- Source-of-truth consistency ---


def test_default_config_covers_all_app_keymaps() -> None:
    """default_config.yml must define every AppKeymaps field."""
    defaults = load_builtin_app_defaults()
    field_names = {f.name for f in fields(AppKeymaps)}
    missing = field_names - set(defaults.keys())
    assert not missing, f"default_config.yml missing: {sorted(missing)}"


def test_binding_meta_matches_app_keymaps() -> None:
    """_BINDING_META must cover exactly AppKeymaps fields."""
    meta_actions = {a for a, _, _ in _BINDING_META}
    field_names = {f.name for f in fields(AppKeymaps)}
    assert meta_actions == field_names
