"""Tests for ace TUI app binding construction."""

from dataclasses import fields

from sase.ace.tui.bindings import DEFAULT_BINDINGS
from sase.ace.tui.artifact_tabs import resolve_artifacts_subtabs
from sase.ace.tui.keymaps import AppKeymaps, build_app_bindings
from sase.ace.tui.keymaps.key_validation import is_unbound_key
from tests._keymaps_helpers import default_app_keymaps


def test_build_app_bindings_count() -> None:
    """Bindings contain configurable actions plus runtime artifact jumps."""
    bindings = build_app_bindings(default_app_keymaps())
    artifact_jump_count = sum(
        descriptor.digit_shortcut is not None
        for descriptor in resolve_artifacts_subtabs()
    )
    app_km = default_app_keymaps()
    bound_actions = sum(
        1
        for field in fields(AppKeymaps)
        if not is_unbound_key(getattr(app_km, field.name))
    )
    assert len(bindings) == bound_actions + artifact_jump_count


def test_file_trim_actions_are_not_configurable_bindings() -> None:
    actions = {binding.action for binding in build_app_bindings(default_app_keymaps())}

    assert "reset_file_trim" not in actions
    assert "show_all_file_lines" not in actions


def test_build_app_bindings_priority() -> None:
    """Global tab switching takes key priority."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["next_tab"].priority is True
    assert by_action["prev_tab"].priority is True
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


def test_patch_filters_take_f_and_hook_editing_moves_to_capital_f() -> None:
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {binding.action: binding for binding in bindings}

    assert by_action["patches_filters"].key == "f"
    assert by_action["edit_hooks"].key == "F"


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
    """Default ``s`` is intentionally shared across contextual surfaces.

    sase-m6.9 kept ``s`` = mutate (Patch's ``change_status``, Beads'
    ``beads_cycle_status``, which already mutates) and moved the two pure
    display-facet cycles (``stitches_cycle_merges``, ``files_cycle_kind``)
    off ``s`` onto ``z`` so ``s`` means the same contract verb everywhere
    it fires.
    """
    bindings = build_app_bindings(default_app_keymaps())
    assert [b.action for b in bindings if b.key == "s"] == [
        "change_status",
        "beads_cycle_status",
        "save_marked_agents",
    ]
    assert [b.action for b in bindings if b.key == "z"] == [
        "start_fold_mode",
        "stitches_cycle_merges",
        "beads_snooze",
        "files_cycle_kind",
    ]


def test_capital_x_binds_agent_cleanup_panel() -> None:
    """Capital X is the cleanup entry point and the Patches reverted toggle."""
    bindings = build_app_bindings(default_app_keymaps())
    by_action = {b.action: b for b in bindings}
    assert by_action["open_agent_cleanup_panel"].key == "X"
    assert by_action["patches_toggle_reverted"].key == "X"


def test_full_stop_binds_relation_toggle_and_hide_reverted() -> None:
    bindings = build_app_bindings(default_app_keymaps())
    assert [binding.action for binding in bindings if binding.key == "full_stop"] == [
        "toggle_relation_panel",
        "toggle_hide_reverted",
    ]


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
        "prev_agent_metadata_section",
        "artifacts_unload",
    ]
    assert [b.action for b in bindings if b.key == "ctrl+j"] == [
        "next_agent_metadata_section",
        "artifacts_load_more",
    ]
    assert by_action["next_agent_metadata_section"].key == "ctrl+j"
    assert by_action["artifacts_load_more"].key == "ctrl+j"
    assert by_action["artifacts_unload"].key == "ctrl+k"
    assert fallback_by_action["jump_to_entry_fast"].key == "ctrl+o"
    assert fallback_by_action["jump_to_entry_forward"].key == "ctrl+shift+o"
    assert fallback_by_action["prev_agent_metadata_section"].key == "ctrl+k"
    assert fallback_by_action["artifacts_load_more"].key == "ctrl+j"
    assert fallback_by_action["artifacts_unload"].key == "ctrl+k"


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
    expected_digits = {
        descriptor.digit_shortcut: descriptor.id
        for descriptor in resolve_artifacts_subtabs()
        if descriptor.digit_shortcut is not None
    }

    assert {
        by_action[f"show_artifacts_digit({digit})"].key: subtab
        for digit, subtab in expected_digits.items()
    } == expected_digits
    assert by_action["open_saved_query_picker"].key == "asterisk"
    assert by_action["start_saved_query_mode"].key == "0"
    assert {
        binding.key
        for binding in bindings
        if len(binding.key) == 1 and binding.key.isdigit()
    } == {*expected_digits, "0"}
    assert not any(
        binding.action.startswith("load_saved_query") for binding in bindings
    )


def test_fallback_bindings_match_numbered_artifacts_and_saved_query_picker() -> None:
    """Class-level bindings preserve runtime behavior before registry wiring."""
    by_action = {binding.action: binding for binding in DEFAULT_BINDINGS}

    assert [
        (by_action[f"show_artifacts_digit({digit})"].key, subtab)
        for digit, subtab in (
            ("1", "stitches"),
            ("2", "patches"),
            ("3", "beads"),
            ("4", "files"),
        )
    ] == [
        ("1", "stitches"),
        ("2", "patches"),
        ("3", "beads"),
        ("4", "files"),
    ]
    assert by_action["open_saved_query_picker"].key == "asterisk"
    assert by_action["start_saved_query_mode"].key == "0"
    assert {
        binding.key
        for binding in DEFAULT_BINDINGS
        if len(binding.key) == 1 and binding.key.isdigit()
    } == {"1", "2", "3", "4", "0"}
    assert not any(
        binding.action.startswith("load_saved_query") for binding in DEFAULT_BINDINGS
    )


def test_h_binding_metadata_describes_navigation_and_contextual_collapse() -> None:
    runtime_by_action = {
        binding.action: binding for binding in build_app_bindings(default_app_keymaps())
    }
    fallback_by_action = {binding.action: binding for binding in DEFAULT_BINDINGS}

    lower = "Parent / Collapse or Jump Panel/Fold"
    upper = "Collapse Selected Workflow/Family / Scoped Agent Nodes/Clans/Groups / Hint Panel Fold / Compact Tools / All"
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
