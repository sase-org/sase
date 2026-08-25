"""Tests for loading ace TUI keymap registries."""

from sase.ace.tui.keymaps import (
    BangModeKeymaps,
    BeadIssueModeKeymaps,
    ConfigHubKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    GateModalKeymaps,
    LeaderModeKeymaps,
    MemoryPanelKeymaps,
    ModeKeymaps,
    SnippetPanelKeymaps,
    StatisticsPaneKeymaps,
    load_keymap_registry,
)


def test_empty_config_uses_builtin_defaults() -> None:
    """Empty config uses defaults from default_config.yml."""
    reg = load_keymap_registry({})
    assert reg.app.next_patch == "j"
    assert reg.app.quit == "q"
    assert reg.app.next_tab == "tab"
    assert reg.app.jump_to_entry_fast == "ctrl+o"
    assert reg.app.jump_to_entry_forward == "ctrl+shift+o"
    assert reg.app.next_agent_metadata_section == "ctrl+j"
    assert reg.app.prev_agent_metadata_section == "ctrl+k"
    assert reg.app.artifacts_load_more == "ctrl+j"
    assert reg.app.artifacts_unload == "ctrl+k"
    assert reg.app.search_forward == "slash"
    assert reg.app.edit_query == "slash"
    assert reg.app.search_reverse == "ctrl+r"
    assert reg.app.show_help == "question_mark"
    assert reg.leader_mode.keys["edit_query"] == "slash"
    assert "show_help" not in reg.leader_mode.keys
    assert isinstance(reg.fold_mode, FoldModeKeymaps)
    assert isinstance(reg.copy_mode, CopyModeKeymaps)
    assert isinstance(reg.leader_mode, LeaderModeKeymaps)
    assert isinstance(reg.bang_mode, BangModeKeymaps)
    assert isinstance(reg.bead_issue_mode, BeadIssueModeKeymaps)
    assert isinstance(reg.config, ConfigHubKeymaps)
    assert reg.config.select_subtab == "0"
    assert isinstance(reg.statistics, StatisticsPaneKeymaps)
    assert isinstance(reg.gate, GateModalKeymaps)
    assert isinstance(reg.memory, MemoryPanelKeymaps)
    assert isinstance(reg.snippets, SnippetPanelKeymaps)
    assert reg.snippets.next_snippet == "j"
    assert reg.snippets.filter_snippets == "slash"
    assert reg.snippets.next_project == "p"
    assert reg.snippets.copy_template == "y"
    assert reg.snippets.help == "question_mark"
    assert reg.gate.toggle_option == "space"
    assert reg.gate.submit_branch == "ctrl+s"
    assert reg.gate.open_inputs == "i"
    assert reg.gate.next_input == "tab"
    assert reg.gate.previous_input == "shift+tab"
    assert reg.statistics.prev_view == "left_square_bracket"
    assert reg.statistics.next_view == "right_square_bracket"
    assert reg.statistics.select_view == "0"
    assert reg.statistics.cycle_range == "t"
    assert reg.statistics.cycle_range_reverse == "T"
    assert reg.statistics.custom_range == "c"
    assert reg.statistics.cycle_group == "g"
    assert reg.statistics.cycle_project_filter == "p"
    assert reg.statistics.cycle_project_filter_reverse == "P"
    assert reg.statistics.scroll_down == "ctrl+d"
    assert reg.statistics.scroll_up == "ctrl+u"
    assert reg.statistics.refresh == "r"
    assert reg.statistics.help == "question_mark"
    assert reg.memory.next_note == "j"
    assert reg.memory.prev_note == "k"
    assert reg.memory.filter_notes == "slash"
    assert reg.memory.toggle_body_filter == "greater_than_sign"
    assert reg.memory.next_scope == "p"
    assert reg.memory.prev_scope == "P"
    assert reg.memory.pick_scope == "ctrl+p"
    assert reg.memory.edit_note == "e"
    assert reg.memory.publish == "I"
    assert reg.memory.help == "question_mark"


def test_config_hub_keymap_scope_loads_custom_prefix() -> None:
    reg = load_keymap_registry({"keymaps": {"config": {"select_subtab": "f4"}}})

    assert reg.config.select_subtab == "f4"


def test_config_hub_keymap_scope_rejects_invalid_prefix() -> None:
    reg = load_keymap_registry({"keymaps": {"config": {"select_subtab": "not a key"}}})

    assert reg.config.select_subtab == "0"


def test_config_hub_keymap_scope_ignores_unknown_actions() -> None:
    reg = load_keymap_registry(
        {"keymaps": {"config": {"select_subtab": "f5", "missing": "f6"}}}
    )

    assert reg.config.select_subtab == "f5"


def test_leader_repeat_last_default_binding() -> None:
    """Typed defaults and YAML defaults both bind leader repeat to comma."""
    reg = load_keymap_registry({})
    assert LeaderModeKeymaps().keys["repeat_last"] == "comma"
    assert reg.leader_mode.keys["repeat_last"] == "comma"


def test_leader_prompt_stash_panel_defaults_to_at() -> None:
    """Typed and loaded leader defaults bind the stash panel to ``@``."""
    reg = load_keymap_registry({})
    assert LeaderModeKeymaps().keys["open_prompt_stash"] == "at"
    assert reg.leader_mode.keys["open_prompt_stash"] == "at"


def test_custom_agent_launcher_defaults_to_plus() -> None:
    """The app-level custom-agent launcher defaults to ``plus`` (``+``)."""
    reg = load_keymap_registry({})

    assert reg.app.start_custom_agent == "plus"
    assert reg.app.start_agent_home == "space"
    assert reg.app.start_agent_from_patch == "ctrl+@"


def test_restore_prompt_stash_defaults_to_at() -> None:
    """The global prompt-stash restore keymap defaults to ``at`` (``@``)."""
    reg = load_keymap_registry({})

    assert reg.app.restore_prompt_stash == "at"


def test_custom_agent_launcher_at_override_reverts_to_plus() -> None:
    """``at`` now belongs to restore-stash, so a launcher ``at`` override reverts.

    Existing configs that bound the launcher to ``at`` now collide with the new
    default ``restore_prompt_stash`` binding. The duplicate-key guard reverts the
    user-overridden launcher to its ``plus`` default and leaves ``@`` reserved
    for restore.
    """
    reg = load_keymap_registry({"keymaps": {"app": {"start_custom_agent": "at"}}})

    assert reg.app.start_custom_agent == "plus"
    assert reg.app.restore_prompt_stash == "at"


def test_agent_launch_defaults_use_distinct_space_keys() -> None:
    """Agent launch defaults keep bare Space and Ctrl+Space distinct."""
    reg = load_keymap_registry({})

    assert reg.app.start_agent_home == "space"
    assert reg.app.start_agent_from_patch == "ctrl+@"
    assert reg.app.start_agent_from_patch != "space"
    assert reg.app.start_agent_from_patch != reg.app.start_agent_home
    assert LeaderModeKeymaps().keys["agent_home"] == "h"
    assert reg.leader_mode.keys["agent_home"] == "h"
    assert reg.leader_mode.keys["agent_home"] != "space"
    assert LeaderModeKeymaps().keys["agent_from_cl"] == "space"
    assert reg.leader_mode.keys["agent_from_cl"] == "space"
    assert reg.leader_mode.keys["agent_from_cl"] != "ctrl+@"


def test_ctrl_space_user_config_canonicalizes_to_ctrl_at() -> None:
    """User-facing Ctrl+Space spelling canonicalizes for Textual dispatch."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {"start_agent_from_patch": "ctrl+space"},
                "modes": {"leader_mode": {"keys": {"agent_from_cl": "ctrl+space"}}},
            }
        }
    )

    assert reg.app.start_agent_from_patch == "ctrl+@"
    assert reg.leader_mode.keys["agent_from_cl"] == "ctrl+@"


def test_edit_hooks_default_binding() -> None:
    """Guard: Patch filters own ``f`` and hook editing lives on ``F``."""
    reg = load_keymap_registry({})
    assert reg.app.patches_filters == "f"
    assert reg.app.edit_hooks == "F"
    assert reg.app.run_workflow == "r"


def test_g_and_o_default_bindings_do_not_collide() -> None:
    """Guard: ``g`` is scroll_to_top everywhere; grouping-cycle lives on ``o``/``O``.

    Re-introducing the old ``cycle_grouping_mode: g`` binding would steal the
    universal scroll-to-top mnemonic on the Agents tab; see
    sdd/plans/202604/g_keymap_restore.md. Grouping-cycle is ``o`` / ``O``, which
    does not collide with ``g``.
    """
    reg = load_keymap_registry({})
    assert reg.app.scroll_to_top == "g"
    assert reg.app.cycle_grouping_mode == "o"
    assert reg.app.cycle_grouping_mode_reverse == "O"


def test_partial_app_override() -> None:
    """Overriding one app key preserves all other defaults."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_patch": "P"}}})
    assert reg.app.next_patch == "P"
    assert reg.app.prev_patch == "k"  # unchanged
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
    assert reg.fold_mode.keys["cycle_stitches"] == "x"
    assert reg.fold_mode.keys["cycle_hooks"] == "h"  # unchanged
    assert reg.fold_mode.prefix == "z"  # unchanged


def test_fold_mode_agent_defaults_and_nested_override() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "keys": {"agents": {"cycle_section": "s"}},
                    },
                },
            },
        }
    )

    agent_keys = reg.fold_mode.keys["agents"]
    assert isinstance(agent_keys, dict)
    assert agent_keys == {
        "cycle_level": "z",
        "toggle_all": "Z",
        "cycle_section": "s",
        "toggle_section": "A",
        "set_level_1": "1",
        "set_level_2": "2",
        "set_level_3": "3",
        "set_level_4": "4",
    }
    assert reg.fold_mode.keys["cycle_stitches"] == "c"


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
    assert isinstance(keys["patches"], dict)
    assert keys["patches"]["raw"] == "percent_sign"
    assert keys["patches"]["bug"] == "b"
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
                            "changespecs": {"bug": "B"},  # legacy wire key
                        },
                    },
                },
            },
        }
    )
    cs_keys = reg.copy_mode.keys["patches"]
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
    assert reg.app.next_patch == "j"
    assert isinstance(reg.fold_mode, FoldModeKeymaps)


def test_legacy_glossary_keymap_scope_is_ignored_without_error() -> None:
    """A retired ``ace.keymaps.glossary`` user override loads without error.

    The Glossary panel keymap scope is retired: ``KeymapRegistry`` no longer
    has a ``.glossary`` field, and no bindings are built from it. The config
    schema still accepts the key for one release, so the loader must ignore
    it silently rather than raising.
    """
    reg = load_keymap_registry(
        {"keymaps": {"glossary": {"next_term": "down", "help": "f9"}}}
    )
    assert not hasattr(reg, "glossary")
    assert reg.app.next_patch == "j"  # unaffected
