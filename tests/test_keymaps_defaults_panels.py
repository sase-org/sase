"""Tests for app/panel keymap defaults and binding-metadata consistency."""

from dataclasses import fields

from sase.ace.tui.keymaps import (
    AppKeymaps,
    CommandLineKeymaps,
    ConfigHubKeymaps,
    GateModalKeymaps,
    MemoryPanelKeymaps,
    ProjectsPaneKeymaps,
    SnippetPanelKeymaps,
    StatisticsPaneKeymaps,
    _BINDING_META,
    load_builtin_app_defaults,
    load_builtin_command_line_defaults,
    load_builtin_config_defaults,
    load_builtin_gate_defaults,
    load_builtin_memory_defaults,
    load_builtin_projects_defaults,
    load_builtin_snippets_defaults,
    load_builtin_statistics_defaults,
    load_keymap_registry,
)


def test_open_command_palette_default_binding() -> None:
    """``;`` is bound to open_command_palette by default.

    Phase 1 of the command palette plan: every keymap (including the
    one that opens the palette itself) lives in default_config.yml.
    """
    reg = load_keymap_registry({})
    assert reg.app.open_command_palette == "semicolon"


def test_open_command_line_default_binding() -> None:
    """``:`` is bound to open_command_line by default after the flip."""
    reg = load_keymap_registry({})
    assert reg.app.open_command_line == "colon"


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


def test_agent_header_toggle_default_binding() -> None:
    """The header toggle ships on lowercase ``d``, tab-disjoint from its owners."""
    reg = load_keymap_registry({})
    assert reg.app.toggle_agent_header == "d"


def test_agent_jump_panel_and_non_run_toggle_default_bindings() -> None:
    """The jump panel ships on ``.`` and the non-run toggle moved to ``I``."""
    reg = load_keymap_registry({})
    assert reg.app.toggle_agent_jump_panel == "full_stop"
    assert reg.app.toggle_hide_non_run_agents == "I"
    assert reg.app.toggle_hide_reverted == "full_stop"
    assert reg.app.toggle_relation_panel == "full_stop"


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


def test_default_config_covers_all_memory_keymaps() -> None:
    """The bundled config is the source of truth for Memory-panel keys."""
    defaults = load_builtin_memory_defaults()
    field_names = {field.name for field in fields(MemoryPanelKeymaps)}

    assert defaults == {
        "next_note": "j",
        "prev_note": "k",
        "first_note": "g",
        "last_note": "G",
        "toggle_web": "space",
        "next_strand": "s",
        "prev_strand": "S",
        "scroll_body_down": "ctrl+d",
        "scroll_body_up": "ctrl+u",
        "filter_notes": "slash",
        "toggle_body_filter": "greater_than_sign",
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
        "initialize_project": "i",
        "initialize_all_projects": "I",
    }
    assert field_names == set(defaults)


def test_default_config_covers_all_command_line_keymaps() -> None:
    """The bundled config is the source of truth for Command Line panel keys."""
    defaults = load_builtin_command_line_defaults()
    field_names = {field.name for field in fields(CommandLineKeymaps)}

    assert defaults == {
        "toggle_full_height": "ctrl+t",
        "clear_transcript": "ctrl+l",
        "hide_panel": "escape",
        "hop_to_palette": "semicolon",
        "history_prev": "up",
        "history_next": "down",
        "history_search": "ctrl+r",
        "block_next": "j,down",
        "block_prev": "k,up",
        "block_first": "g",
        "block_last": "G,shift+g",
        "block_toggle_expand": "o,enter",
        "block_pager": "v",
        "block_kill": "K,shift+k",
        "block_rerun": "r",
        "block_rerun_confirm": "R,shift+r",
        "block_edit": "e",
        "block_copy_output": "y",
        "block_copy_command": "Y,shift+y",
        "block_procs": "p",
        "block_remove": "x",
        "block_focus_input": "i,a,colon",
    }
    assert field_names == set(defaults)


def test_command_line_binding_meta_lists_screen_bound_actions() -> None:
    """Every screen-bound Command Line action resolves to a configured key."""
    from sase.ace.tui.keymaps.metadata import _COMMAND_LINE_BINDING_META

    field_names = {field.name for field in fields(CommandLineKeymaps)}
    meta_actions = {action for action, _description in _COMMAND_LINE_BINDING_META}

    assert meta_actions <= field_names
    assert {
        "hop_to_palette",
        "history_prev",
        "history_next",
        "history_search",
    }.isdisjoint(meta_actions)


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
