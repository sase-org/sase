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
    footer_key_display,
    key_display_name,
    load_builtin_app_defaults,
    load_keymap_registry,
)
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
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


def test_edit_hooks_default_binding() -> None:
    """Guard: ``f`` is bound to ``edit_hooks`` (restored after d7b96606)."""
    reg = load_keymap_registry({})
    assert reg.app.edit_hooks == "f"


def test_help_modal_labels_capital_a_as_agent_run_log() -> None:
    """Guard the restored ``A`` Agent Run Log binding."""
    reg = load_keymap_registry({})
    cls_sections = cls_bindings(reg)
    agents_sections = agents_bindings(reg)
    axe_sections = axe_bindings(reg)

    cls_pairs = {
        (key, label) for _section, bindings in cls_sections for key, label in bindings
    }
    assert (",A", "Agent run log") in cls_pairs

    for sections in (cls_sections, agents_sections, axe_sections):
        action_labels = {
            label
            for _section, bindings in sections
            for key, label in bindings
            if key == "A"
        }
        assert "Agent run log" in action_labels


def test_g_and_o_default_bindings_do_not_collide() -> None:
    """Guard: ``g`` is scroll_to_top everywhere; ``o`` is the grouping cycle.

    Re-introducing the old ``cycle_grouping_mode: g`` binding would steal the
    universal scroll-to-top mnemonic on the Agents tab — see
    sdd/tales/202604/g_keymap_restore.md.
    """
    reg = load_keymap_registry({})
    assert reg.app.scroll_to_top == "g"
    assert reg.app.cycle_grouping_mode == "o"
    assert reg.app.cycle_grouping_mode_reverse == "O"


def test_partial_app_override() -> None:
    """Overriding one app key preserves all other defaults."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_changespec": "B"}}})
    assert reg.app.next_changespec == "B"
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
    assert keys["agents"]["name"] == "n"
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
    """build_app_bindings produces 79 configurable + 10 digit = 89 bindings."""
    bindings = build_app_bindings(_default_app_keymaps())
    assert len(bindings) == 89


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


def test_capital_x_binds_agent_cleanup_panel() -> None:
    """Capital X is the single cleanup entry point."""
    bindings = build_app_bindings(_default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["open_agent_cleanup_panel"].key == "X"


def test_build_app_bindings_preserves_compound_key() -> None:
    """Compound Textual binding strings stay on the single configured action."""
    km = _default_app_keymaps(open_command_palette="colon,semicolon")
    bindings = build_app_bindings(km)
    by_action = {b.action: b for b in bindings}
    assert by_action["open_command_palette"].key == "colon,semicolon"


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


def test_key_display_compound_alternatives() -> None:
    """Compound app bindings render as alternatives, not a key sequence."""
    assert key_display_name("colon,semicolon") == ": / ;"


def test_footer_key_display_compound_alternatives() -> None:
    """Compound app bindings keep footer formatting per alternative."""
    assert footer_key_display("colon,space") == ": / <space>"


def test_help_modal_displays_command_palette_alternatives() -> None:
    """The help modal uses the same readable display for compound app bindings."""
    reg = load_keymap_registry({})
    entries = [
        entry
        for _section_name, section_entries in cls_bindings(reg)
        for entry in section_entries
    ]
    assert (": / ;", "Open command palette") in entries


# --- KeymapRegistry defaults ---


def test_registry_default_modes_always_present() -> None:
    """KeymapRegistry always has all four built-in modes."""
    reg = KeymapRegistry(app=_default_app_keymaps())
    assert "fold_mode" in reg.modes
    assert "copy_mode" in reg.modes
    assert "leader_mode" in reg.modes
    assert "bang_mode" in reg.modes


def test_leader_mode_includes_mark_inactive() -> None:
    """LeaderModeKeymaps default includes mark_inactive bound to ``I``."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["mark_inactive"] == "I"


def test_leader_mode_includes_agent_run_log() -> None:
    """LeaderModeKeymaps default includes the ``,A`` run-log fallback."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["agent_run_log"] == "A"


def test_leader_mode_omits_legacy_kill_all() -> None:
    """The Agents cleanup panel replaces the old leader kill-all command."""
    reg = load_keymap_registry({})
    assert "kill_all" not in reg.leader_mode.keys


# --- Source-of-truth consistency ---


def test_open_command_palette_default_binding() -> None:
    """``:`` and ``;`` are bound to open_command_palette by default.

    Phase 1 of the command palette plan: every keymap (including the
    one that opens the palette itself) lives in default_config.yml.
    """
    reg = load_keymap_registry({})
    assert reg.app.open_command_palette == "colon,semicolon"


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
