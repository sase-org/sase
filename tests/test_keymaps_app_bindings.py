"""Tests for ace TUI app binding construction."""

from dataclasses import fields

from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.keymaps import AppKeymaps, build_app_bindings
from tests._keymaps_helpers import default_app_keymaps


def test_build_app_bindings_count() -> None:
    """Bindings contain every configurable action plus five fixed tab jumps."""
    bindings = build_app_bindings(default_app_keymaps())
    assert len(bindings) == len(fields(AppKeymaps)) + 5


def test_file_trim_actions_are_not_configurable_bindings() -> None:
    actions = {binding.action for binding in build_app_bindings(default_app_keymaps())}

    assert "reset_file_trim" not in actions
    assert "show_all_file_lines" not in actions


def test_build_app_bindings_priority() -> None:
    """Global tab switching and Bugs link activation take key priority."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["next_tab"].priority is True
    assert by_action["prev_tab"].priority is True
    assert by_action["activate_bug_link"].priority is True
    assert by_action["next_patch"].priority is False
    assert by_action["quit"].priority is False


def test_build_app_bindings_uses_config_keys() -> None:
    """Bindings reflect overridden keys from AppKeymaps."""
    km = default_app_keymaps(next_patch="n", quit="Q")
    bindings = build_app_bindings(km)
    by_action = {b.action: b for b in bindings}
    assert by_action["next_patch"].key == "n"
    assert by_action["quit"].key == "Q"


def test_search_and_contextual_app_query_share_slash() -> None:
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {binding.action: binding for binding in bindings}

    assert by_action["search_forward"].key == "slash"
    assert by_action["edit_query"].key == "slash"
    assert by_action["search_reverse"].key == "ctrl+r"
    assert by_action["show_help"].key == "question_mark"


def test_diff_and_axe_description_toggle_share_d_in_resolution_order() -> None:
    bindings = build_app_bindings(default_app_keymaps())

    assert [binding.action for binding in bindings if binding.key == "d"][:2] == [
        "show_diff",
        "toggle_axe_description",
    ]


def test_build_app_bindings_uses_plus_custom_agent_binding() -> None:
    """The custom-agent launcher builds a ``plus`` binding, not ``at``."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    by_key = {b.key: b.action for b in bindings}

    assert by_action["start_custom_agent"].key == "plus"
    assert by_key.get("plus") == "start_custom_agent"
    assert not any(b.action == "start_custom_agent" and b.key == "at" for b in bindings)


def test_build_app_bindings_binds_at_to_restore_prompt_stash() -> None:
    """Bare ``@`` (Textual ``at``) is the global prompt-stash restore binding."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    by_key = {b.key: b.action for b in bindings}

    assert by_action["restore_prompt_stash"].key == "at"
    assert by_key.get("at") == "restore_prompt_stash"


def test_build_app_bindings_uses_ctrl_space_agent_binding() -> None:
    """Agent home uses Space while repeat-last keeps Ctrl+Space."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    by_key = {b.key: b.action for b in bindings}

    assert by_action["start_agent_home"].key == "space"
    assert by_action["start_agent_from_patch"].key == "ctrl+@"
    assert by_key["space"] == "start_agent_home"
    assert not any(
        b.action == "start_agent_from_patch" and b.key == "space" for b in bindings
    )


def test_default_lowercase_s_bindings_are_tab_scoped_and_ordered() -> None:
    """Default ``s`` is intentionally shared across contextual surfaces."""
    bindings = build_app_bindings(default_app_keymaps())
    assert [b.action for b in bindings if b.key == "s"] == [
        "change_status",
        "stitches_cycle_merges",
        "beads_cycle_status",
        "chats_cycle_provenance",
        "files_cycle_kind",
        "toggle_bug_state",
        "save_marked_agents",
    ]


def test_capital_x_binds_agent_cleanup_panel() -> None:
    """Capital X is the single cleanup entry point."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["open_agent_cleanup_panel"].key == "X"


def test_lowercase_a_binds_agent_artifacts_and_capital_a_accepts() -> None:
    """Lowercase ``a`` opens agent artifacts; capital ``A`` accepts/auto-approves.

    Guards the swapped Agents-tab defaults: ``a`` opens artifacts and ``A``
    drives accept_proposal (PR proposal acceptance + Agents-tab auto-approve/HITL).
    """
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["open_artifact_files"].key == "a"
    assert by_action["accept_proposal"].key == "A"
    assert by_action["show_agent_run_log"].key == "V"
    assert by_action["toggle_attempt_view"].key == "D"
    assert by_action["toggle_agent_unread"].key == "U"
    assert [b.action for b in bindings if b.key == "A"] == [
        "plans_approve",
        "accept_proposal",
    ]


def test_default_jump_and_metadata_navigation_keys_are_unique() -> None:
    """Jump-stack navigation is distinct from Agents metadata navigation."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    fallback_by_action = {b.action: b for b in DEFAULT_BINDINGS}

    assert by_action["jump_to_entry_fast"].key == "ctrl+o"
    assert by_action["jump_to_entry_forward"].key == "ctrl+shift+o"
    assert "prev_patch_history" not in by_action
    assert "next_patch_history" not in by_action
    assert [b.action for b in bindings if b.key == "ctrl+o"] == ["jump_to_entry_fast"]
    assert [b.action for b in bindings if b.key == "ctrl+shift+o"] == [
        "jump_to_entry_forward"
    ]
    assert [b.action for b in bindings if b.key == "ctrl+k"] == [
        "prev_agent_metadata_section"
    ]
    assert by_action["next_agent_metadata_section"].key == "ctrl+j"
    assert fallback_by_action["jump_to_entry_fast"].key == "ctrl+o"
    assert fallback_by_action["jump_to_entry_forward"].key == "ctrl+shift+o"
    assert fallback_by_action["prev_agent_metadata_section"].key == "ctrl+k"


def test_build_app_bindings_preserves_compound_key() -> None:
    """Compound Textual binding strings stay on the single configured action."""
    km = default_app_keymaps(open_command_palette="colon,semicolon")
    bindings = build_app_bindings(km)
    by_action = {b.action: b for b in bindings}
    assert by_action["open_command_palette"].key == "colon,semicolon"


def test_build_app_bindings_number_artifacts_and_prefix_saved_queries() -> None:
    """Bare digits jump Artifacts panes; saved query slots live behind 0."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {binding.action: binding for binding in bindings}

    assert {
        by_action[f"show_artifacts_{subtab}"].key: subtab
        for subtab in ("stitches", "beads", "bugs", "prs", "files")
    } == {
        "1": "stitches",
        "2": "beads",
        "3": "bugs",
        "4": "prs",
        "5": "files",
    }
    assert by_action["open_saved_query_picker"].key == "asterisk"
    assert by_action["start_saved_query_mode"].key == "0"
    assert {
        binding.key
        for binding in bindings
        if len(binding.key) == 1 and binding.key.isdigit()
    } == {"1", "2", "3", "4", "5", "0"}
    assert not any(
        binding.action.startswith("load_saved_query") for binding in bindings
    )


def test_fallback_bindings_match_numbered_artifacts_and_saved_query_picker() -> None:
    """Class-level bindings preserve runtime behavior before registry wiring."""
    by_action = {binding.action: binding for binding in DEFAULT_BINDINGS}

    assert [
        (by_action[f"show_artifacts_{subtab}"].key, subtab)
        for subtab in ("stitches", "beads", "bugs", "prs", "files")
    ] == [
        ("1", "stitches"),
        ("2", "beads"),
        ("3", "bugs"),
        ("4", "prs"),
        ("5", "files"),
    ]
    assert by_action["open_saved_query_picker"].key == "asterisk"
    assert by_action["start_saved_query_mode"].key == "0"
    assert {
        binding.key
        for binding in DEFAULT_BINDINGS
        if len(binding.key) == 1 and binding.key.isdigit()
    } == {"1", "2", "3", "4", "5", "0"}
    assert not any(
        binding.action.startswith("load_saved_query") for binding in DEFAULT_BINDINGS
    )


def test_h_binding_metadata_describes_navigation_and_contextual_collapse() -> None:
    runtime_by_action = {
        binding.action: binding for binding in build_app_bindings(default_app_keymaps())
    }
    fallback_by_action = {binding.action: binding for binding in DEFAULT_BINDINGS}

    lower = "Parent / Collapse or Jump Panel/Fold"
    upper = "Collapse Scoped Lanes/Clans/Groups / Hint Panel Fold / Compact Tools / All"
    zoom = "Zoom Detail"
    isolate = "Only/Restore Panels"
    sweep = "Collapse/Restore Panel Folds"
    assert runtime_by_action["hooks_or_collapse"].description == lower
    assert fallback_by_action["hooks_or_collapse"].description == lower
    assert runtime_by_action["hooks_or_collapse_all"].description == upper
    assert fallback_by_action["hooks_or_collapse_all"].description == upper
    assert runtime_by_action["zoom_panel"].description == zoom
    assert fallback_by_action["zoom_panel"].description == zoom
    assert runtime_by_action["isolate_panels"].description == isolate
    assert fallback_by_action["isolate_panels"].description == isolate
    assert runtime_by_action["collapse_panel_folds"].description == sweep
    assert fallback_by_action["collapse_panel_folds"].description == sweep
