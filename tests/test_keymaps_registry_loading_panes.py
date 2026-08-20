"""Tests for pane and modal keymap overrides during registry loading."""

import logging

import pytest

from sase.ace.tui.keymaps import GateModalKeymaps, load_keymap_registry


def test_statistics_pane_keys_can_be_overridden_independently() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "statistics": {
                    "prev_view": "f12",
                    "next_view": "f11",
                    "select_view": "f13",
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
    assert reg.statistics.select_view == "f13"
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

    assert reg.gate == GateModalKeymaps(
        next_control="down",
        previous_control="up",
        toggle_option="t",
        submit_primary="a",
        submit_branch="s",
    )


def test_glossary_panel_keys_can_be_overridden_independently() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "glossary": {
                    "next_term": "down",
                    "prev_term": "up",
                    "filter_terms": "f12",
                    "next_project": "f11",
                    "prev_project": "f10",
                    "help": "f9",
                }
            }
        }
    )

    assert reg.glossary.next_term == "down"
    assert reg.glossary.prev_term == "up"
    assert reg.glossary.filter_terms == "f12"
    assert reg.glossary.next_project == "f11"
    assert reg.glossary.prev_project == "f10"
    assert reg.glossary.help == "f9"
    # Unoverridden fields keep their bundled defaults.
    assert reg.glossary.add_term == "a"
    assert reg.glossary.delete_term == "d"


def test_memory_panel_keys_can_be_overridden_independently() -> None:
    reg = load_keymap_registry(
        {
            "keymaps": {
                "memory": {
                    "next_note": "down",
                    "prev_note": "up",
                    "filter_notes": "f12",
                    "next_scope": "f11",
                    "prev_scope": "f10",
                    "pick_scope": "f8",
                    "help": "f9",
                }
            }
        }
    )

    assert reg.memory.next_note == "down"
    assert reg.memory.prev_note == "up"
    assert reg.memory.filter_notes == "f12"
    assert reg.memory.next_scope == "f11"
    assert reg.memory.prev_scope == "f10"
    assert reg.memory.pick_scope == "f8"
    assert reg.memory.help == "f9"
    # Unoverridden fields keep their bundled defaults.
    assert reg.memory.add_note == "a"
    assert reg.memory.edit_note == "e"
    assert reg.memory.delete_note == "d"
    assert reg.memory.publish == "I"


def test_duplicate_glossary_help_override_reverts_to_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry({"keymaps": {"glossary": {"help": "r"}}})

    assert reg.glossary.help == "question_mark"
    assert "Duplicate glossary key" in caplog.text


def test_duplicate_memory_help_override_reverts_to_default(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry({"keymaps": {"memory": {"help": "r"}}})

    assert reg.memory.help == "question_mark"
    assert "Duplicate memory key" in caplog.text


def test_unknown_memory_action_is_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING):
        reg = load_keymap_registry({"keymaps": {"memory": {"not_a_real_action": "x"}}})

    assert reg.memory.next_note == "j"
    assert "Unknown memory keymap action" in caplog.text
