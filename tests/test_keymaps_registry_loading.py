"""Tests for loading ace TUI keymap registries."""

import logging

import pytest

from sase.ace.tui.keymaps import (
    BangModeKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    GateModalKeymaps,
    LeaderModeKeymaps,
    ModeKeymaps,
    StatisticsPaneKeymaps,
    load_keymap_registry,
)


def test_retired_selected_panel_toggle_leader_override_is_filtered() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {"keys": {"toggle_selected_agent_panels": "P"}}
                }
            }
        }
    )

    assert "toggle_selected_agent_panels" not in reg.leader_mode.keys


def test_empty_config_uses_builtin_defaults() -> None:
    """Empty config uses defaults from default_config.yml."""
    reg = load_keymap_registry({})
    assert reg.app.next_changespec == "j"
    assert reg.app.quit == "q"
    assert reg.app.next_tab == "tab"
    assert reg.app.jump_to_entry_fast == "ctrl+o"
    assert reg.app.jump_to_entry_forward == "ctrl+shift+o"
    assert reg.app.next_agent_metadata_section == "ctrl+j"
    assert reg.app.prev_agent_metadata_section == "ctrl+k"
    assert reg.app.search_forward == "slash"
    assert reg.app.edit_query == "slash"
    assert reg.app.search_reverse == "question_mark"
    assert reg.leader_mode.keys["edit_query"] == "slash"
    assert reg.leader_mode.keys["show_help"] == "question_mark"
    assert isinstance(reg.fold_mode, FoldModeKeymaps)
    assert isinstance(reg.copy_mode, CopyModeKeymaps)
    assert isinstance(reg.leader_mode, LeaderModeKeymaps)
    assert isinstance(reg.bang_mode, BangModeKeymaps)
    assert isinstance(reg.statistics, StatisticsPaneKeymaps)
    assert isinstance(reg.gate, GateModalKeymaps)
    assert reg.gate.toggle_option == "space"
    assert reg.gate.submit_branch == "ctrl+s"
    assert reg.statistics.prev_view == "left_square_bracket"
    assert reg.statistics.next_view == "right_square_bracket"
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


def test_app_query_override_is_honored_while_retired_help_is_dropped(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="sase.ace.tui.keymaps.registry"):
        reg = load_keymap_registry(
            {"keymaps": {"app": {"edit_query": "f5", "show_help": "f6"}}}
        )

    assert reg.app.edit_query == "f5"
    assert not hasattr(reg.app, "show_help")
    assert "Ignoring retired app keymap action: edit_query" not in caplog.text
    assert "Ignoring retired app keymap action: show_help" in caplog.text
    assert "Unknown keymap action" not in caplog.text


def test_statistics_pane_keys_can_be_overridden_independently() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "statistics": {
                    "prev_view": "f12",
                    "next_view": "f11",
                    "cycle_range": "f10",
                    "cycle_range_reverse": "f9",
                    "custom_range": "f8",
                    "cycle_group": "f7",
                    "cycle_project_filter": "f6",
                    "cycle_project_filter_reverse": "f1",
                    "focus_xprompt": "home",
                    "clear_xprompt_focus": "end",
                    "scroll_down": "f5",
                    "scroll_up": "f4",
                    "refresh": "f3",
                    "help": "f2",
                }
            }
        }
    )

    assert reg.statistics.prev_view == "f12"
    assert reg.statistics.next_view == "f11"
    assert reg.statistics.cycle_range == "f10"
    assert reg.statistics.cycle_range_reverse == "f9"
    assert reg.statistics.custom_range == "f8"
    assert reg.statistics.cycle_group == "f7"
    assert reg.statistics.cycle_project_filter == "f6"
    assert reg.statistics.cycle_project_filter_reverse == "f1"
    assert reg.statistics.focus_xprompt == "home"
    assert reg.statistics.clear_xprompt_focus == "end"
    assert reg.statistics.scroll_down == "f5"
    assert reg.statistics.scroll_up == "f4"
    assert reg.statistics.refresh == "f3"
    assert reg.statistics.help == "f2"


def test_duplicate_statistics_help_override_reverts_to_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry({"keymaps": {"statistics": {"help": "r"}}})

    assert reg.statistics.help == "question_mark"
    assert "Duplicate statistics key" in caplog.text


def test_gate_modal_keys_can_be_overridden_independently() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "gate": {
                    "next_control": "down",
                    "previous_control": "up",
                    "toggle_option": "t",
                    "submit_primary": "a",
                    "submit_branch": "s",
                }
            }
        }
    )

    assert reg.gate == GateModalKeymaps("down", "up", "t", "a", "s")


def test_retired_activate_control_override_aliases_submit_primary(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry({"keymaps": {"gate": {"activate_control": "f12"}}})

    assert reg.gate.submit_primary == "f12"
    assert "deprecated" in caplog.text


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
    assert reg.app.start_agent_from_changespec == "ctrl+@"


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
    assert reg.app.start_agent_from_changespec == "ctrl+@"
    assert reg.app.start_agent_from_changespec != "space"
    assert reg.app.start_agent_from_changespec != reg.app.start_agent_home
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
                "app": {"start_agent_from_changespec": "ctrl+space"},
                "modes": {"leader_mode": {"keys": {"agent_from_cl": "ctrl+space"}}},
            }
        }
    )

    assert reg.app.start_agent_from_changespec == "ctrl+@"
    assert reg.leader_mode.keys["agent_from_cl"] == "ctrl+@"


def test_edit_hooks_default_binding() -> None:
    """Guard: ``f`` is bound to ``edit_hooks`` (restored after d7b96606)."""
    reg = load_keymap_registry({})
    assert reg.app.edit_hooks == "f"
    assert reg.app.run_workflow == "r"


def test_g_and_o_default_bindings_do_not_collide() -> None:
    """Guard: ``g`` is scroll_to_top everywhere; ``o`` is the grouping cycle.

    Re-introducing the old ``cycle_grouping_mode: g`` binding would steal the
    universal scroll-to-top mnemonic on the Agents tab; see
    sdd/plans/202604/g_keymap_restore.md.
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
    assert reg.fold_mode.keys["cycle_commits"] == "c"


def test_legacy_agents_reverse_cycle_override_migrates_to_toggle_all(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry(
            {
                "keymaps": {
                    "modes": {
                        "fold_mode": {
                            "keys": {
                                "agents": {
                                    "cycle_level_back": "v",
                                    "toggle_all": "Z",
                                }
                            }
                        }
                    }
                }
            }
        )

    agent_keys = reg.fold_mode.keys["agents"]
    assert isinstance(agent_keys, dict)
    assert agent_keys["toggle_all"] == "v"
    assert "cycle_level_back" not in agent_keys
    assert "deprecated" in caplog.text


def test_agents_toggle_all_override_wins_over_legacy_alias() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "keys": {
                            "agents": {
                                "cycle_level_back": "v",
                                "toggle_all": "x",
                            }
                        }
                    }
                }
            }
        }
    )

    agent_keys = reg.fold_mode.keys["agents"]
    assert isinstance(agent_keys, dict)
    assert agent_keys["toggle_all"] == "x"
    assert "cycle_level_back" not in agent_keys


def test_stale_kill_marked_and_edit_override_is_dropped() -> None:
    """A lingering ``kill_marked_and_edit`` override cannot revive the key.

    The action was folded into the contextual ``kill_and_edit`` (``,x``); a
    stale user config entry must be filtered during load so the deep-merge
    does not reintroduce it, while other leader overrides still apply.
    """
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "keys": {
                            "kill_marked_and_edit": "X",
                            "kill_and_edit": "y",
                        },
                    },
                },
            },
        }
    )
    assert "kill_marked_and_edit" not in reg.leader_mode.keys
    assert reg.leader_mode.keys["kill_and_edit"] == "y"  # legit override survives


def test_stale_restore_prompt_stash_override_is_dropped() -> None:
    """A lingering ``restore_prompt_stash`` override cannot revive global ``,P``.

    The global leader restore was retired in favour of ``@`` and the
    prompt-local ``Ctrl+G p`` panel opener; a stale user config entry must be
    filtered during load so the deep-merge does not reintroduce it, while other
    leader overrides still apply.
    """
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "keys": {
                            "restore_prompt_stash": "P",
                            "kill_and_edit": "y",
                        },
                    },
                },
            },
        }
    )
    assert "restore_prompt_stash" not in reg.leader_mode.keys
    assert reg.leader_mode.keys["kill_and_edit"] == "y"  # legit override survives


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
