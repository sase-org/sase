"""Tests for keymap validation (duplicate keys, invalid keys)."""

import logging

import pytest

from sase.ace.tui.keymaps import (
    canonicalize_key_binding,
    is_valid_key,
    load_keymap_registry,
)


# --- is_valid_key ---


def test_single_char_keys_accepted() -> None:
    """Single alphanumeric characters are valid keys."""
    assert is_valid_key("j")
    assert is_valid_key("Q")
    assert is_valid_key("1")


def test_valid_named_keys_accepted() -> None:
    """Named Textual keys and modifier combos are valid."""
    assert is_valid_key("full_stop")
    assert is_valid_key("ctrl+d")
    assert is_valid_key("ctrl+@")
    assert is_valid_key("ctrl+space")
    assert is_valid_key("ctrl+at")
    assert is_valid_key("ctrl+shift+o")
    assert is_valid_key("escape")
    assert is_valid_key("shift+tab")
    assert is_valid_key("enter")
    assert is_valid_key("f12")


def test_plus_key_spellings_accepted() -> None:
    """The ``+`` launcher key is valid by name, raw glyph, and Unicode name."""
    assert is_valid_key("plus")
    assert is_valid_key("+")
    assert is_valid_key("plus_sign")


def test_plus_aliases_canonicalize_to_plus() -> None:
    """Friendly ``+`` spellings normalize to Textual's ``plus`` key name."""
    assert canonicalize_key_binding("+") == "plus"
    assert canonicalize_key_binding("plus_sign") == "plus"
    assert canonicalize_key_binding("plus") == "plus"


def test_minus_key_spellings_accepted() -> None:
    """The ``-`` panel-fold-sweep key is valid by name and raw glyph."""
    assert is_valid_key("minus")
    assert is_valid_key("-")


def test_minus_alias_canonicalizes_to_minus() -> None:
    """The friendly ``-`` spelling normalizes to Textual's ``minus`` key name."""
    assert canonicalize_key_binding("-") == "minus"
    assert canonicalize_key_binding("minus") == "minus"


def test_compound_key_alternatives_accepted() -> None:
    """Comma-separated Textual binding alternatives are valid."""
    assert is_valid_key("colon,semicolon")
    assert is_valid_key("ctrl+d,shift+tab")


def test_compound_key_with_invalid_alternative_rejected() -> None:
    """Every segment of a compound binding must be a valid key."""
    assert not is_valid_key("colon,not_a_real_key")
    assert not is_valid_key("colon,")
    assert not is_valid_key("colon,colon")
    assert not is_valid_key("ctrl+space,ctrl+@")


def test_ctrl_space_aliases_canonicalize_to_ctrl_at() -> None:
    """Readable Ctrl+Space spellings normalize to Textual's runtime key."""
    assert canonicalize_key_binding("ctrl+space") == "ctrl+@"
    assert canonicalize_key_binding("ctrl+at") == "ctrl+@"
    assert canonicalize_key_binding("colon, ctrl+space") == "colon,ctrl+@"


def test_empty_string_key_invalid() -> None:
    """Empty string is not a valid key and reverts to default."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_patch": ""}}})
    assert reg.app.next_patch == "j"  # default


def test_invalid_key_reverts_to_default() -> None:
    """Nonsense key name reverts to default."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_patch": "not_a_real_key"}}})
    assert reg.app.next_patch == "j"


def test_invalid_key_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Invalid key triggers a log warning."""
    with caplog.at_level(logging.WARNING):
        load_keymap_registry({"keymaps": {"app": {"next_patch": "not_a_real_key"}}})
    assert any("Invalid key" in r.message for r in caplog.records)


# --- Duplicate key detection ---


def test_duplicate_app_keys_reverts_to_default() -> None:
    """Override that conflicts with a default key reverts."""
    # next_patch overridden to "q" clashes with quit's default "q".
    reg = load_keymap_registry({"keymaps": {"app": {"next_patch": "q"}}})
    assert reg.app.next_patch == "j"  # reverted to default
    assert reg.app.quit == "q"  # unchanged


def test_duplicate_app_keys_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    """Duplicate key conflict triggers a log warning."""
    with caplog.at_level(logging.WARNING):
        load_keymap_registry({"keymaps": {"app": {"next_patch": "q"}}})
    assert any("Duplicate key" in r.message for r in caplog.records)


def test_contextual_query_actions_may_share_a_custom_key() -> None:
    """Agents search and non-Agents query editing have disjoint scopes."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "search_forward": "f12",
                    "edit_query": "f12",
                }
            }
        }
    )

    assert reg.app.search_forward == "f12"
    assert reg.app.edit_query == "f12"


def test_contextual_open_external_actions_may_share_a_custom_key() -> None:
    """Beads and Files open-externally actions are pane-disjoint."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "beads_open_bug": "f11",
                    "files_open_external": "f11",
                }
            }
        }
    )

    assert reg.app.beads_open_bug == "f11"
    assert reg.app.files_open_external == "f11"


def test_both_overrides_duplicate_revert_both() -> None:
    """Two user overrides mapping to the same key both revert."""
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "next_patch": "Z",
                    "prev_patch": "Z",
                },
            },
        }
    )
    assert reg.app.next_patch == "j"  # default
    assert reg.app.prev_patch == "k"  # default


def test_jump_forward_and_metadata_section_remain_independently_configurable() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "app": {
                    "prev_agent_metadata_section": "ctrl+x",
                    "jump_to_entry_forward": "ctrl+y",
                }
            }
        }
    )

    assert reg.app.prev_agent_metadata_section == "ctrl+x"
    assert reg.app.jump_to_entry_forward == "ctrl+y"


def test_compound_key_conflict_reverts_override() -> None:
    """A key inside a compound binding conflicts like a normal app key."""
    reg = load_keymap_registry({"keymaps": {"app": {"next_patch": "semicolon"}}})
    assert reg.app.open_command_palette == "colon,semicolon"
    assert reg.app.next_patch == "j"


def test_compound_key_conflict_logs_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Compound-key duplicate conflicts emit the existing duplicate warning."""
    with caplog.at_level(logging.WARNING):
        load_keymap_registry({"keymaps": {"app": {"next_patch": "semicolon"}}})
    assert any("Duplicate key" in r.message for r in caplog.records)


def test_statistics_key_can_overlap_global_app_key() -> None:
    """Scoped Statistics keys do not participate in global app conflicts."""
    reg = load_keymap_registry({"keymaps": {"statistics": {"cycle_group": "q"}}})

    assert reg.statistics.cycle_group == "q"
    assert reg.app.quit == "q"


def test_duplicate_statistics_keys_revert_overrides() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "statistics": {
                    "prev_view": "f12",
                    "next_view": "f12",
                }
            }
        }
    )

    assert reg.statistics.prev_view == "left_square_bracket"
    assert reg.statistics.next_view == "right_square_bracket"


def test_reverse_statistics_range_key_collision_reverts_override() -> None:
    reg = load_keymap_registry(
        {"keymaps": {"statistics": {"cycle_range_reverse": "t"}}}
    )

    assert reg.statistics.cycle_range == "t"
    assert reg.statistics.cycle_range_reverse == "T"


def test_reverse_statistics_project_key_collision_reverts_override() -> None:
    reg = load_keymap_registry(
        {"keymaps": {"statistics": {"cycle_project_filter_reverse": "p"}}}
    )

    assert reg.statistics.cycle_project_filter == "p"
    assert reg.statistics.cycle_project_filter_reverse == "P"


def test_clear_xprompt_focus_key_collision_reverts_override() -> None:
    reg = load_keymap_registry(
        {"keymaps": {"statistics": {"clear_xprompt_focus": "x"}}}
    )

    assert reg.statistics.focus_xprompt == "x"
    assert reg.statistics.clear_xprompt_focus == "X"


def test_invalid_statistics_key_reverts_to_default() -> None:
    reg = load_keymap_registry(
        {"keymaps": {"statistics": {"refresh": "not_a_real_key"}}}
    )

    assert reg.statistics.refresh == "r"


def test_duplicate_gate_keys_revert_overrides() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "gate": {
                    "next_control": "f12",
                    "previous_control": "f12",
                }
            }
        }
    )

    assert reg.gate.next_control == "j"
    assert reg.gate.previous_control == "k"


def test_glossary_key_can_overlap_global_app_key() -> None:
    """Scoped Glossary panel keys do not participate in global app conflicts."""
    reg = load_keymap_registry({"keymaps": {"glossary": {"refresh": "q"}}})

    assert reg.glossary.refresh == "q"
    assert reg.app.quit == "q"


def test_duplicate_glossary_keys_revert_overrides() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "glossary": {
                    "next_term": "f12",
                    "prev_term": "f12",
                }
            }
        }
    )

    assert reg.glossary.next_term == "j"
    assert reg.glossary.prev_term == "k"


def test_invalid_glossary_key_reverts_to_default() -> None:
    reg = load_keymap_registry({"keymaps": {"glossary": {"refresh": "not_a_real_key"}}})

    assert reg.glossary.refresh == "r"


def test_projects_key_can_overlap_global_app_key() -> None:
    """Scoped Projects pane keys do not participate in global app conflicts."""
    reg = load_keymap_registry({"keymaps": {"projects": {"toggle_project_mark": "q"}}})

    assert reg.projects.toggle_project_mark == "q"
    assert reg.app.quit == "q"


def test_duplicate_projects_keys_revert_overrides() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "projects": {
                    "toggle_project_mark": "f12",
                    "clear_project_marks": "f12",
                }
            }
        }
    )

    assert reg.projects.toggle_project_mark == "m"
    assert reg.projects.clear_project_marks == "u"


def test_invalid_projects_key_reverts_to_default() -> None:
    reg = load_keymap_registry(
        {"keymaps": {"projects": {"set_current_project": "not_a_real_key"}}}
    )

    assert reg.projects.set_current_project == "c"


def test_custom_mode_prefix_conflicts_with_compound_app_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Custom mode prefixes compare against each key in a compound app binding."""
    with caplog.at_level(logging.WARNING):
        load_keymap_registry(
            {
                "keymaps": {
                    "modes": {
                        "my_mode": {
                            "prefix": "semicolon",
                            "keys": {
                                "do_thing": {
                                    "key": "t",
                                    "shell": "echo hi",
                                },
                            },
                        },
                    },
                }
            }
        )
    assert any("prefix 'semicolon' conflicts" in r.message for r in caplog.records)
