"""Tests for ace TUI keymap defaults and source-of-truth consistency."""

from dataclasses import fields
from pathlib import Path
from unittest.mock import patch

import yaml

from sase.ace.tui.keymaps import (
    AppKeymaps,
    BangModeKeymaps,
    BeadIssueModeKeymaps,
    ConfigHubKeymaps,
    CopyModeKeymaps,
    FoldModeKeymaps,
    GateModalKeymaps,
    GlossaryPanelKeymaps,
    KeymapRegistry,
    LeaderModeKeymaps,
    MemoryPanelKeymaps,
    ProjectsPaneKeymaps,
    SnippetPanelKeymaps,
    StatisticsPaneKeymaps,
    _BINDING_META,
    load_builtin_app_defaults,
    load_builtin_config_defaults,
    load_builtin_gate_defaults,
    load_builtin_glossary_defaults,
    load_builtin_memory_defaults,
    load_builtin_projects_defaults,
    load_builtin_snippets_defaults,
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
    """KeymapRegistry always has all built-in modes."""
    reg = KeymapRegistry(app=default_app_keymaps())
    assert "fold_mode" in reg.modes
    assert "copy_mode" in reg.modes
    assert "leader_mode" in reg.modes
    assert "bang_mode" in reg.modes
    assert "bead_issue_mode" in reg.modes


def test_fold_mode_dataclass_defaults_match_default_config() -> None:
    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["fold_mode"]
    defaults = FoldModeKeymaps()

    assert configured == {"prefix": defaults.prefix, "keys": defaults.keys}


def test_copy_mode_dataclass_defaults_match_default_config() -> None:
    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["copy_mode"]
    defaults = CopyModeKeymaps()

    assert configured == {"prefix": defaults.prefix, "keys": defaults.keys}


def test_bang_mode_dataclass_defaults_match_default_config() -> None:
    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["bang_mode"]
    defaults = BangModeKeymaps()

    assert configured == {"prefix": defaults.prefix, "keys": defaults.keys}


def test_bead_issue_mode_dataclass_defaults_match_default_config() -> None:
    config = yaml.safe_load(
        Path("src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    configured = config["ace"]["keymaps"]["modes"]["bead_issue_mode"]
    defaults = BeadIssueModeKeymaps()

    assert configured == {"prefix": defaults.prefix, "keys": defaults.keys}


def test_zoom_and_agents_fold_defaults_are_in_sync_with_help() -> None:
    reg = load_keymap_registry({})
    agent_fold = reg.fold_mode.keys["agents"]
    assert isinstance(agent_fold, dict)

    assert reg.app.start_fold_mode == "z"
    assert reg.app.zoom_panel == "Z"
    assert reg.app.isolate_panels == "="
    assert reg.app.collapse_panel_folds == "minus"
    assert agent_fold == {
        "cycle_level": "z",
        "toggle_all": "Z",
        "cycle_section": "a",
        "toggle_section": "A",
        "set_level_1": "1",
        "set_level_2": "2",
        "set_level_3": "3",
        "set_level_4": "4",
    }

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    assert ("Z", "Zoom agent/tribe detail") in agent_pairs
    assert ("=", "Only panel ⇄ restore panels") in agent_pairs
    assert ("zz", "Cycle panel fold level forward") in agent_pairs
    assert ("zZ", "Toggle all metadata folds") in agent_pairs
    assert ("za", "Cycle foldable section/member") in agent_pairs
    assert ("zA", "Toggle foldable section/member") in agent_pairs
    assert ("z1 / z2", "Set family level 1-2") in agent_pairs
    assert ("z1 / z2 / z3", "Set clan/sase agent level 1-3") in agent_pairs
    assert (
        "z1 / z2 / z3 / z4",
        "Set selected tribe level 1-4",
    ) in agent_pairs
    assert ("0-9", "Jump numbered member/neighbor") in agent_pairs
    assert ("Esc", "Enter selected panel / cancel member jump") in agent_pairs


def test_fold_mode_direct_level_overrides_and_prefix_reach_help() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "modes": {
                    "fold_mode": {
                        "prefix": "f",
                        "keys": {
                            "set_level_2": "w",
                            "agents": {"set_level_4": "x", "toggle_all": "v"},
                        },
                    }
                }
            }
        }
    )

    agent_keys = reg.fold_mode.keys["agents"]
    assert isinstance(agent_keys, dict)
    assert reg.app.start_fold_mode == "f"
    assert reg.fold_mode.keys["set_level_1"] == "1"
    assert reg.fold_mode.keys["set_level_2"] == "w"
    assert agent_keys["set_level_1"] == "1"
    assert agent_keys["set_level_4"] == "x"
    assert agent_keys["toggle_all"] == "v"

    agent_pairs = {
        (key, label)
        for _section, bindings in agents_bindings(reg)
        for key, label in bindings
    }
    patch_pairs = {
        (key, label)
        for _section, bindings in cls_bindings(reg)
        for key, label in bindings
    }
    assert ("f1 / f2 / f3 / fx", "Set selected tribe level 1-4") in agent_pairs
    assert ("fv", "Toggle all metadata folds") in agent_pairs
    assert ("f1 / fw / f3", "Set all folds to level 1-3") in patch_pairs


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
    assert reg.leader_mode.keys["edit_query"] == "slash"
    assert "show_help" not in LeaderModeKeymaps().keys
    assert "show_help" not in reg.leader_mode.keys
    assert reg.app.search_forward == "slash"
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


def test_leader_mode_includes_agent_panel_grouping_toggle() -> None:
    """LeaderModeKeymaps default includes the ``,g`` panel grouping toggle."""
    reg = load_keymap_registry({})
    assert reg.leader_mode.keys["toggle_agent_panel_grouping"] == "g"


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
    assert (",u", "Mark all unread done agents read / undo") in agent_pairs
    assert (",U", "Mark all unread done agents read / undo") not in agent_pairs


def test_help_advertises_update_sase_on_all_tabs() -> None:
    """The global ``,U`` update shortcut appears in every help binding list."""
    reg = load_keymap_registry({})
    expected = (",U", "Update panel (SASE, providers, agents)")
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


def test_saved_query_slot_mode_default_binding() -> None:
    """The direct saved-query slot prefix defaults to 0 and doesn't disturb *."""
    reg = load_keymap_registry({})
    assert reg.app.start_saved_query_mode == "0"
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
        "select_view": "0",
        "jump_to_entry": "apostrophe",
        "cycle_range": "t",
        "cycle_range_reverse": "T",
        "custom_range": "c",
        "cycle_group": "g",
        "cycle_project_filter": "p",
        "cycle_project_filter_reverse": "P",
        "focus_xprompt": "x",
        "clear_xprompt_focus": "X",
        "scroll_down": "ctrl+d",
        "scroll_up": "ctrl+u",
        "refresh": "r",
        "help": "question_mark",
    }
    assert field_names == set(defaults)


def test_default_config_covers_all_config_hub_keymaps() -> None:
    """The bundled config is the source of truth for Config-hub keys."""
    defaults = load_builtin_config_defaults()
    field_names = {field.name for field in fields(ConfigHubKeymaps)}

    assert defaults == {"select_subtab": "0"}
    assert field_names == set(defaults)


def test_default_config_covers_all_glossary_keymaps() -> None:
    """The bundled config is the source of truth for Glossary-panel keys."""
    defaults = load_builtin_glossary_defaults()
    field_names = {field.name for field in fields(GlossaryPanelKeymaps)}

    assert defaults == {
        "next_term": "j",
        "prev_term": "k",
        "first_term": "g",
        "last_term": "G",
        "scroll_definition_down": "ctrl+d",
        "scroll_definition_up": "ctrl+u",
        "filter_terms": "slash",
        "toggle_definition_filter": "full_stop",
        "next_relation": "tab",
        "prev_relation": "shift+tab",
        "follow_relation": "enter,l",
        "travel_back": "backspace,h",
        "next_project": "p",
        "prev_project": "P",
        "add_term": "a",
        "delete_term": "d",
        "open_source": "o",
        "open_viewer": "Z",
        "copy_definition": "y",
        "copy_source_path": "Y",
        "refresh": "r",
        "help": "question_mark",
    }
    assert field_names == set(defaults)


def test_default_config_covers_all_memory_keymaps() -> None:
    """The bundled config is the source of truth for Memory-panel keys."""
    defaults = load_builtin_memory_defaults()
    field_names = {field.name for field in fields(MemoryPanelKeymaps)}

    assert defaults == {
        "next_note": "j",
        "prev_note": "k",
        "first_note": "g",
        "last_note": "G",
        "scroll_body_down": "ctrl+d",
        "scroll_body_up": "ctrl+u",
        "filter_notes": "slash",
        "toggle_body_filter": "full_stop",
        "next_link": "tab",
        "prev_link": "shift+tab",
        "follow_link": "enter,l",
        "travel_back": "backspace,h",
        "next_scope": "p",
        "prev_scope": "P",
        "pick_scope": "ctrl+p",
        "add_note": "a",
        "edit_note": "e",
        "delete_note": "d",
        "publish": "I",
        "open_source": "o",
        "open_viewer": "Z",
        "copy_body": "y",
        "copy_source_path": "Y",
        "refresh": "r",
        "help": "question_mark",
    }
    assert field_names == set(defaults)


def test_default_config_covers_all_snippets_keymaps() -> None:
    """The bundled config is the source of truth for Snippets-panel keys."""
    defaults = load_builtin_snippets_defaults()
    field_names = {field.name for field in fields(SnippetPanelKeymaps)}

    assert defaults == {
        "next_snippet": "j",
        "prev_snippet": "k",
        "first_snippet": "g",
        "last_snippet": "G",
        "scroll_template_down": "ctrl+d",
        "scroll_template_up": "ctrl+u",
        "filter_snippets": "slash",
        "toggle_body_filter": "full_stop",
        "next_relation": "tab",
        "prev_relation": "shift+tab",
        "follow_relation": "enter,l",
        "travel_back": "backspace,h",
        "next_project": "p",
        "prev_project": "P",
        "add_snippet": "a",
        "edit_snippet": "e",
        "delete_snippet": "d",
        "open_source": "o",
        "open_viewer": "Z",
        "copy_template": "y",
        "copy_source_path": "Y",
        "refresh": "r",
        "help": "question_mark",
    }
    assert field_names == set(defaults)


def test_default_config_covers_all_projects_keymaps() -> None:
    """The bundled config is the source of truth for Projects-pane keys."""
    defaults = load_builtin_projects_defaults()
    field_names = {field.name for field in fields(ProjectsPaneKeymaps)}

    assert defaults == {
        "next_option": "j,down,ctrl+n",
        "prev_option": "k,up,ctrl+p",
        "focus_filter": "slash",
        "cycle_subtab": "right_square_bracket",
        "cycle_subtab_reverse": "left_square_bracket",
        "toggle_project_mark": "m",
        "clear_project_marks": "u",
        "edit_project_spec": "e",
        "edit_project_aliases": "A",
        "enable_project": "a",
        "disable_project": "d",
        "delete_project": "ctrl+d",
        "force_current_state_change": "F",
        "default_project_action": "enter",
        "reload": "R",
        "show_project_repos": "r",
        "show_project_workspaces": "w",
        "jump_to_entry": "apostrophe",
        "pick_project": "p",
        "clear_project_filter": "escape",
        "set_current_project": "c",
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
        "open_inputs": "i",
        "next_input": "tab",
        "previous_input": "shift+tab",
    }
    assert field_names == set(defaults)


def test_gate_panel_keys_are_not_bound_on_the_gate_modal() -> None:
    from sase.ace.tui.keymaps.metadata import (
        _GATE_BINDING_META,
        _GATE_INPUT_PANEL_BINDING_META,
    )

    modal_actions = {action for action, _description in _GATE_BINDING_META}
    panel_actions = {action for action, _description in _GATE_INPUT_PANEL_BINDING_META}

    assert "open_inputs" in modal_actions
    assert panel_actions == {"next_input", "previous_input"}
    assert modal_actions.isdisjoint(panel_actions)


def test_binding_meta_matches_app_keymaps() -> None:
    """_BINDING_META must cover exactly AppKeymaps fields."""
    meta_actions = {a for a, _, _ in _BINDING_META}
    field_names = {f.name for f in fields(AppKeymaps)}
    assert meta_actions == field_names


def test_patch_facing_binding_meta_uses_patch_labels() -> None:
    """Visible binding names should match Patch terminology."""
    meta_labels = {action: label for action, label, _priority in _BINDING_META}

    assert meta_labels["start_agent_from_patch"] == "Run Agent (Last VCS XPrompt)"
    assert meta_labels["jump_to_agent_patch"] == "Go to Patch"
