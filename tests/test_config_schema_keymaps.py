"""Schema coverage for scoped ACE keymap overrides."""

from __future__ import annotations

from typing import Any

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import schema


pytestmark = pytest.mark.contract


def test_config_schema_accepts_scoped_statistics_keymaps() -> None:
    Draft7Validator(schema()).validate(
        {
            "ace": {
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
        }
    )


@pytest.mark.parametrize(
    "statistics",
    [
        {"next_view": 12},
        {"unknown_action": "x"},
    ],
)
def test_config_schema_rejects_invalid_scoped_statistics_keymaps(
    statistics: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"ace": {"keymaps": {"statistics": statistics}}}
        )


def test_config_schema_accepts_scoped_gate_keymaps() -> None:
    Draft7Validator(schema()).validate(
        {
            "ace": {
                "keymaps": {
                    "gate": {
                        "next_control": "down",
                        "previous_control": "up",
                        "toggle_option": "space",
                        "submit_primary": "enter",
                        "submit_branch": "ctrl+enter",
                        "open_inputs": "o",
                        "next_input": "ctrl+n",
                        "previous_input": "ctrl+p",
                    }
                }
            }
        }
    )


def test_config_schema_accepts_deprecated_activate_control_alias() -> None:
    Draft7Validator(schema()).validate(
        {"ace": {"keymaps": {"gate": {"activate_control": "f12"}}}}
    )


@pytest.mark.parametrize(
    "gate",
    [
        {"next_control": 12},
        {"unknown_action": "x"},
    ],
)
def test_config_schema_rejects_invalid_scoped_gate_keymaps(
    gate: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"ace": {"keymaps": {"gate": gate}}})


def test_config_schema_accepts_scoped_memory_keymaps() -> None:
    Draft7Validator(schema()).validate(
        {
            "ace": {
                "keymaps": {
                    "memory": {
                        "next_note": "down",
                        "prev_note": "up",
                        "filter_notes": "f12",
                        "next_scope": "f11",
                        "prev_scope": "f10",
                        "pick_scope": "f8",
                        "toggle_web": "space",
                        "next_strand": "f5",
                        "prev_strand": "f4",
                        "edit_note": "f7",
                        "publish": "f6",
                        "help": "f9",
                    }
                }
            }
        }
    )


@pytest.mark.parametrize(
    "memory",
    [
        {"next_note": 12},
        {"unknown_action": "x"},
    ],
)
def test_config_schema_rejects_invalid_scoped_memory_keymaps(
    memory: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"ace": {"keymaps": {"memory": memory}}})


def test_config_schema_accepts_scoped_snippets_keymaps() -> None:
    Draft7Validator(schema()).validate(
        {
            "ace": {
                "keymaps": {
                    "snippets": {
                        "next_snippet": "down",
                        "prev_snippet": "up",
                        "filter_snippets": "f12",
                        "next_project": "f11",
                        "prev_project": "f10",
                        "edit_snippet": "f7",
                        "help": "f9",
                    }
                }
            }
        }
    )


@pytest.mark.parametrize(
    "snippets",
    [
        {"next_snippet": 12},
        {"unknown_action": "x"},
    ],
)
def test_config_schema_rejects_invalid_scoped_snippets_keymaps(
    snippets: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"ace": {"keymaps": {"snippets": snippets}}})
