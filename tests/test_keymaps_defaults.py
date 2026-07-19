"""Tests for ace TUI keymap defaults and source-of-truth consistency."""

from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

from sase.ace.tui.keymaps import (
    AppKeymaps,
    GateModalKeymaps,
    KeymapRegistry,
    LeaderModeKeymaps,
    StatisticsPaneKeymaps,
    _BINDING_META,
    load_builtin_app_defaults,
    load_builtin_gate_defaults,
    load_builtin_statistics_defaults,
    load_keymap_registry,
)
from sase.ace.tui.modals.help_modal.bindings import (
    agents_bindings,
    axe_bindings,
    cls_bindings,
)
from tests._keymaps_helpers import default_app_keymaps


def test_registry_default_modes_always_present() -> None:
    """KeymapRegistry always has all four built-in modes."""
    reg = KeymapRegistry(app=default_app_keymaps())
    assert "fold_mode" in reg.modes
    assert "copy_mode" in reg.modes
    assert "leader_mode" in reg.modes
    assert "bang_mode" in reg.modes


def test_zoom_and_agents_fold_defaults_are_in_sync_with_help() -> None:
    reg = load_keymap_registry({})
    agent_fold = reg.fold_mode.keys["agents"]
    assert isinstance(agent_fold, dict)

    assert reg.app.start_fold_mode == "z"
    assert reg.app.zoom_panel == "Z"
    assert agent_fold == {
        "cycle_level": "z",
        "cycle_level_back": "Z",
        "cycle_section": "a",
        "toggle_section": "A",
    }

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert ("Z", "Zoom largest panel popup") in agent_pairs
    assert ("zz", "Cycle panel fold level forward") in agent_pairs
    assert ("zZ", "Cycle panel fold level backward") in agent_pairs
    assert ("za", "Cycle section/member forward") in agent_pairs
    assert ("zA", "Toggle section/member full") in agent_pairs
    assert ("0-9", "Jump to numbered member") in agent_pairs
    assert ("Esc", "Enter selected panel / cancel member jump") in agent_pairs


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


def test_leader_mode_drops_tab_guide_key() -> None:
    """The ``,?`` tab guide leader key was retired into the Help panel."""
    reg = load_keymap_registry({})
    assert "tab_guide" not in LeaderModeKeymaps().keys
    assert "tab_guide" not in reg.leader_mode.keys


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
    """The ``,t`` task queue leader key was retired in the Tasks-tab cutover."""
    reg = load_keymap_registry({})
    assert "task_queue" not in reg.leader_mode.keys
    assert "task_queue" not in LeaderModeKeymaps().keys


def test_leader_mode_includes_agent_panel_grouping_toggle() -> None:
    """LeaderModeKeymaps default includes the ``,g`` panel grouping toggle."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["toggle_agent_panel_grouping"] == "g"


def test_leader_mode_includes_selected_panel_toggle() -> None:
    reg = load_keymap_registry({})

    assert reg.leader_mode.keys["toggle_selected_agent_panels"] == "H"


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
    assert reg.app.toggle_agent_unread == "U"

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert (",u", "Mark all unread done agents read") in agent_pairs
    assert (",U", "Mark all unread done agents read") not in agent_pairs


def test_help_advertises_update_sase_on_all_tabs() -> None:
    """The global ``,U`` update shortcut appears in every help binding list."""
    reg = load_keymap_registry({})
    expected = (",U", "Update sase, core & plugins")
    for bindings in (cls_bindings, agents_bindings, axe_bindings):
        pairs = {
            (key, label) for _section, rows in bindings(reg) for key, label in rows
        }
        assert expected in pairs


def test_leader_mode_includes_prompt_history_edit_first() -> None:
    """LeaderModeKeymaps default includes the ``, Ctrl+G`` history edit."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["prompt_history_edit_first"] == "ctrl+g"


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
    """Leader ``,x`` owns kill-and-edit; the separate ``,X`` key is retired.

    A single ``kill_and_edit`` action bound to ``x`` handles both the focused
    row and the marked set (contextually); ``kill_marked_and_edit`` no longer
    exists as a default leader key.
    """
    reg = load_keymap_registry({})
    assert LeaderModeKeymaps().keys["kill_and_edit"] == "x"
    assert "kill_marked_and_edit" not in LeaderModeKeymaps().keys
    assert reg.leader_mode.keys["kill_and_edit"] == "x"
    assert "kill_marked_and_edit" not in reg.leader_mode.keys


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


def test_open_command_palette_default_binding() -> None:
    """``:`` and ``;`` are bound to open_command_palette by default.

    Phase 1 of the command palette plan: every keymap (including the
    one that opens the palette itself) lives in default_config.yml.
    """
    reg = load_keymap_registry({})
    assert reg.app.open_command_palette == "colon,semicolon"


def test_saved_query_picker_default_binding() -> None:
    """The PR-only saved-query chooser uses Textual's canonical star key."""
    reg = load_keymap_registry({})
    assert reg.app.open_saved_query_picker == "asterisk"


def test_start_last_vcs_xprompt_editor_default_binding() -> None:
    """Ctrl+G opens the last VCS xprompt directly in the editor."""
    reg = load_keymap_registry({})
    assert reg.app.start_last_vcs_xprompt_in_editor == "ctrl+g"


def test_default_config_covers_all_app_keymaps() -> None:
    """default_config.yml must define every AppKeymaps field."""
    defaults = load_builtin_app_defaults()
    field_names = {f.name for f in fields(AppKeymaps)}
    missing = field_names - set(defaults.keys())
    assert not missing, f"default_config.yml missing: {sorted(missing)}"


def test_default_config_covers_all_statistics_keymaps() -> None:
    """The bundled config is the source of truth for Statistics-pane keys."""
    defaults = load_builtin_statistics_defaults()
    field_names = {field.name for field in fields(StatisticsPaneKeymaps)}

    assert defaults == {
        "prev_view": "left_square_bracket",
        "next_view": "right_square_bracket",
        "cycle_range": "t",
        "custom_range": "c",
        "cycle_group": "g",
        "cycle_project_filter": "p",
        "refresh": "r",
    }
    assert field_names == set(defaults)


def test_default_config_covers_all_gate_modal_keymaps() -> None:
    """The bundled config is the source of truth for shared gate controls."""
    defaults = load_builtin_gate_defaults()
    field_names = {field.name for field in fields(GateModalKeymaps)}

    assert defaults == {
        "next_control": "j",
        "previous_control": "k",
        "toggle_option": "space",
        "submit_primary": "enter",
        "submit_branch": "ctrl+s",
    }
    assert field_names == set(defaults)


def test_binding_meta_matches_app_keymaps() -> None:
    """_BINDING_META must cover exactly AppKeymaps fields."""
    meta_actions = {a for a, _, _ in _BINDING_META}
    field_names = {f.name for f in fields(AppKeymaps)}
    assert meta_actions == field_names


def test_pr_facing_binding_meta_uses_pr_labels() -> None:
    """Visible binding names should match the PR terminology used by ACE."""
    meta_labels = {action: label for action, label, _priority in _BINDING_META}

    assert meta_labels["start_agent_from_changespec"] == "Run Agent (PR)"
    assert meta_labels["jump_to_agent_changespec"] == "Go to PR"
