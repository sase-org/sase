"""Tests for leader-mode keymap defaults and help advertisement."""

from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.keymaps import (
    LeaderModeKeymaps,
    load_keymap_registry,
)
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
)


def test_idle_keymap_defaults_are_removed() -> None:
    """Removed idle actions do not appear in app or leader defaults."""
    reg = load_keymap_registry({})
    assert not hasattr(reg.app, "mark_inactive")
    assert "mark_inactive" not in reg.leader_mode.keys
    assert "mark_inactive_pinned" not in reg.leader_mode.keys
    assert "activity_info" not in reg.leader_mode.keys


def test_leader_mode_includes_agent_run_log() -> None:
    """LeaderModeKeymaps default includes the ``,A`` run-log fallback."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["agent_run_log"] == "A"


def test_contextual_query_and_help_defaults_are_split_by_scope() -> None:
    """Query editing is contextual while help is a global app binding."""
    reg = load_keymap_registry({})
    assert "tab_guide" not in LeaderModeKeymaps().keys
    assert "tab_guide" not in reg.leader_mode.keys
    assert reg.leader_mode.keys["search_forward"] == "slash"
    assert "edit_query" not in LeaderModeKeymaps().keys
    assert "edit_query" not in reg.leader_mode.keys
    assert "show_help" not in LeaderModeKeymaps().keys
    assert "show_help" not in reg.leader_mode.keys
    assert not hasattr(reg.app, "search_forward")
    assert reg.app.edit_query == "slash"
    assert reg.app.search_reverse == "ctrl+r"
    assert reg.app.show_help == "question_mark"


def test_leader_mode_drops_project_management_key() -> None:
    """The ``,p`` project panel leader key was retired in the Projects-tab cutover."""
    reg = load_keymap_registry({})
    assert "projects" not in reg.leader_mode.keys
    assert reg.leader_mode.keys["models_panel"] == "m"


def test_leader_mode_drops_log_panel_key() -> None:
    """The ``,L`` log panel leader key was retired in the Logs-tab cutover."""
    reg = load_keymap_registry({})
    assert "log_panel" not in reg.leader_mode.keys
    assert "log_panel" not in LeaderModeKeymaps().keys


def test_leader_mode_drops_task_queue_key() -> None:
    """The ``,t`` task queue leader key was retired in the Procs-tab cutover."""
    reg = load_keymap_registry({})
    assert "task_queue" not in reg.leader_mode.keys
    assert "task_queue" not in LeaderModeKeymaps().keys


def test_leader_mode_drops_agent_panel_grouping_toggle() -> None:
    """The old ``,g`` panel grouping leader key is retired."""
    reg = load_keymap_registry({})
    assert "toggle_agent_panel_grouping" not in reg.leader_mode.keys
    assert "toggle_agent_panel_grouping" not in LeaderModeKeymaps().keys


def test_leader_mode_includes_collapse_fold_by_hint() -> None:
    """LeaderModeKeymaps default includes the ``,H`` collapse-by-hint chord."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["collapse_fold_by_hint"] == "H"
    assert LeaderModeKeymaps().keys["collapse_fold_by_hint"] == "H"


def test_visible_fold_selector_defaults_to_direct_l_only() -> None:
    reg = load_keymap_registry({})

    assert reg.app.expand_all_folds == "L"
    assert "toggle_selected_agent_panels" not in LeaderModeKeymaps().keys
    assert "toggle_selected_agent_panels" not in reg.leader_mode.keys


def test_leader_mode_includes_jump_to_next_unread_done_agent() -> None:
    """LeaderModeKeymaps default includes the ``,j`` unread done jump."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["jump_to_next_unread_done_agent"] == "j"


def test_leader_mode_includes_jump_to_next_stopped_agent() -> None:
    """LeaderModeKeymaps default includes the ``,J`` stopped-agent jump."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["jump_to_next_stopped_agent"] == "J"


def test_leader_mode_includes_full_history_refresh() -> None:
    """LeaderModeKeymaps default includes the explicit ``,y`` full refresh."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["full_history_refresh"] == "y"


def test_leader_mode_marks_all_unread_done_agents_read_with_u() -> None:
    """LeaderModeKeymaps default binds mark-all-read to ``,u``."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["mark_all_unread_done_agents_read"] == "u"


def test_leader_mode_updates_sase_with_uppercase_u() -> None:
    """LeaderModeKeymaps default binds the comprehensive update to ``,U``."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["update_sase"] == "U"
    assert LeaderModeKeymaps().keys["update_sase"] == "U"


def test_leader_mode_updates_everything_with_uppercase_e() -> None:
    """LeaderModeKeymaps default binds direct Everything update to ``,E``."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["update_everything"] == "E"
    assert LeaderModeKeymaps().keys["update_everything"] == "E"


def test_merged_default_config_marks_all_unread_done_agents_read_with_u(
    tmp_path: Path,
) -> None:
    """Production-style merged defaults also bind mark-all-read to ``,u``."""
    from sase.config.core import load_merged_config

    with (
        patch("sase.config.core.CONFIG_DIR", tmp_path / "empty_config"),
        patch("sase.config.core.Path.cwd", return_value=tmp_path / "no_local_config"),
        patch("sase.config.core._load_plugin_configs", return_value=[]),
    ):
        merged = load_merged_config()

    ace_cfg = merged["ace"]
    assert isinstance(ace_cfg, dict)
    reg = load_keymap_registry(ace_cfg)
    assert reg.leader_mode.keys["mark_all_unread_done_agents_read"] == "u"
    assert reg.leader_mode.keys["update_everything"] == "E"
    assert reg.app.toggle_agent_unread == "U"

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert (",u", "Mark all unread done agents read / undo") in agent_pairs
    assert (",U", "Mark all unread done agents read / undo") not in agent_pairs


def test_help_advertises_update_sase_on_all_tabs() -> None:
    """The global ``,U`` update shortcut appears in every help binding list."""
    reg = load_keymap_registry({})
    expected = (",U", "Update panel (SASE, providers)")
    for bindings in (cls_bindings, agents_bindings, axe_bindings):
        pairs = {
            (key, label) for _section, rows in bindings(reg) for key, label in rows
        }
        assert expected in pairs


def test_help_advertises_update_everything_on_all_tabs() -> None:
    """The global ``,E`` direct Everything shortcut appears in all Help lists."""
    reg = load_keymap_registry({})
    expected = (",E", "Update Everything (no confirmation)")
    for bindings in (cls_bindings, agents_bindings, axe_bindings):
        pairs = {
            (key, label) for _section, rows in bindings(reg) for key, label in rows
        }
        assert expected in pairs


def test_help_uses_configured_update_everything_leader_key() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "leader_mode": {
                        "prefix": "semicolon",
                        "keys": {"update_everything": "Q"},
                    }
                }
            }
        }
    )
    expected = (";Q", "Update Everything (no confirmation)")
    for bindings in (cls_bindings, agents_bindings, axe_bindings):
        pairs = {
            (key, label) for _section, rows in bindings(reg) for key, label in rows
        }
        assert expected in pairs


def test_leader_mode_includes_prompt_history_edit_first() -> None:
    """LeaderModeKeymaps default includes the ``, Ctrl+G`` history edit."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["prompt_history_edit_first"] == "ctrl+g"


def test_leader_mode_includes_jump_to_last_error() -> None:
    """LeaderModeKeymaps default binds the last-error jump to ``,L``."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["jump_to_last_error"] == "L"
    assert LeaderModeKeymaps().keys["jump_to_last_error"] == "L"


def test_leader_mode_omits_legacy_kill_all() -> None:
    """The Agents cleanup panel replaces the old leader kill-all command."""
    reg = load_keymap_registry({})
    assert "kill_all" not in reg.leader_mode.keys


def test_leader_mode_omits_retry_edit() -> None:
    """Direct ``r`` handles Agents-tab retry-edit; leader ``,r`` reverts."""
    reg = load_keymap_registry({})
    assert "retry_edit" not in LeaderModeKeymaps().keys
    assert "retry_edit" not in reg.leader_mode.keys


def test_leader_mode_reserves_r_for_revert_and_moves_runners_to_uppercase_r() -> None:
    """Leader ``,r`` reverts the selected agent; runners moves to ``,R``.

    Repro capture lives on ``,B`` (for "bundle") so it no longer collides
    with the runners panel.
    """
    reg = load_keymap_registry({})
    assert LeaderModeKeymaps().keys["revert_agent"] == "r"
    assert LeaderModeKeymaps().keys["runners"] == "R"
    assert LeaderModeKeymaps().keys["capture_agents_repro"] == "B"
    assert reg.leader_mode.keys["revert_agent"] == "r"
    assert reg.leader_mode.keys["runners"] == "R"
    assert reg.leader_mode.keys["capture_agents_repro"] == "B"


def test_leader_mode_kill_and_edit_is_contextual_x_only() -> None:
    """Leader ``,x`` owns kill-and-edit; the retired ``kill_marked_and_edit`` id is gone.

    A single ``kill_and_edit`` action bound to ``x`` handles both the focused
    row and the marked set (contextually); ``kill_marked_and_edit`` no longer
    exists as a default leader key. ``,X`` is a distinct, unrelated action
    (``kill_and_edit_last``, see the next test) that reuses the freed key.
    """
    reg = load_keymap_registry({})
    assert LeaderModeKeymaps().keys["kill_and_edit"] == "x"
    assert "kill_marked_and_edit" not in LeaderModeKeymaps().keys
    assert reg.leader_mode.keys["kill_and_edit"] == "x"
    assert "kill_marked_and_edit" not in reg.leader_mode.keys


def test_leader_mode_kill_and_edit_last_registered_on_shift_x() -> None:
    """``,X`` is the distinct ``kill_and_edit_last`` action, not a mark-scoped ``,x``."""
    reg = load_keymap_registry({})
    assert LeaderModeKeymaps().keys["kill_and_edit_last"] == "X"
    assert reg.leader_mode.keys["kill_and_edit_last"] == "X"


def test_leader_mode_opens_prompt_stash_without_reviving_restore_action() -> None:
    """Leader ``,@`` gets a panel action without reviving global ``,P``.

    The old ``restore_prompt_stash`` leader id remains absent so stale ``,P``
    overrides cannot blur the distinction between restore and panel-only flows.
    """
    reg = load_keymap_registry({})
    assert LeaderModeKeymaps().keys["open_prompt_stash"] == "at"
    assert reg.leader_mode.keys["open_prompt_stash"] == "at"
    assert "restore_prompt_stash" not in LeaderModeKeymaps().keys
    assert "restore_prompt_stash" not in reg.leader_mode.keys


def test_leader_mode_default_subkeys_are_unique() -> None:
    """No two default leader-mode actions share the same subkey.

    A collision would shadow whichever action the dispatcher checks later,
    making it unreachable by keypress and ambiguous via command dispatch.
    """
    subkeys = [
        value for value in LeaderModeKeymaps().keys.values() if isinstance(value, str)
    ]
    duplicates = sorted({key for key in subkeys if subkeys.count(key) > 1})
    assert not duplicates, f"duplicate leader-mode subkeys: {duplicates}"


def test_agents_help_advertises_runners_and_capture_on_new_keys() -> None:
    """Agents help shows ``,R`` for runners and ``,B`` for repro capture.

    Neither ``,R`` nor ``,C`` may advertise the repro-capture action now
    that it has moved to ``,B``.
    """
    reg = load_keymap_registry({})
    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert (",R", "Show runners info") in agent_pairs
    assert (",B", "Capture repro bundle") in agent_pairs
    assert (",R", "Capture repro bundle") not in agent_pairs
    assert (",C", "Capture repro bundle") not in agent_pairs
