"""Core regression coverage for the user-facing SASE config schema."""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from sase.config.inventory import config_schema_path
from tests._config_schema_helpers import format_schema_error, schema


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_config_schema_resolves_inside_sase_package() -> None:
    schema_path = config_schema_path().resolve()
    package_root = Path(str(importlib.resources.files("sase"))).resolve()

    assert schema_path.is_file()
    assert schema_path.is_relative_to(package_root)
    json.loads(schema_path.read_text(encoding="utf-8"))


def test_default_config_matches_public_schema() -> None:
    public_schema = schema()
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text()
    )

    Draft7Validator.check_schema(public_schema)
    errors = sorted(
        Draft7Validator(public_schema).iter_errors(default_config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(format_schema_error(error) for error in errors)


def test_prompt_completion_history_word_count_default_contract() -> None:
    public_schema = schema()
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    prompt_completion_schema = public_schema["properties"]["ace"]["properties"][
        "prompt_completion"
    ]

    assert default_config["ace"]["prompt_completion"]["history_word_count"] == 10000
    assert (
        prompt_completion_schema["properties"]["history_word_count"]["default"] == 10000
    )


def test_prompt_completion_artifact_menu_default_contract() -> None:
    public_schema = schema()
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    prompt_completion_schema = public_schema["properties"]["ace"]["properties"][
        "prompt_completion"
    ]

    assert default_config["ace"]["prompt_completion"]["auto_artifact_menu"] is True
    assert (
        prompt_completion_schema["properties"]["auto_artifact_menu"]["default"] is True
    )


def test_config_schema_validates_ace_agents_sync_settings() -> None:
    validator = Draft7Validator(schema())
    validator.validate(
        {
            "ace": {
                "agents_sync": {
                    "check_interval_minutes": 5,
                    "recompute_interval_minutes": 30,
                    "indicator": False,
                }
            }
        }
    )
    for invalid in (
        {"check_interval_minutes": 0},
        {"recompute_interval_minutes": -1},
        {"indicator": "yes"},
        {"unknown": True},
    ):
        with pytest.raises(ValidationError):
            validator.validate({"ace": {"agents_sync": invalid}})


def test_prompt_completion_word_min_length_schema_contract() -> None:
    public_schema = schema()
    prompt_completion = public_schema["properties"]["ace"]["properties"][
        "prompt_completion"
    ]
    word_min_length = prompt_completion["properties"]["word_min_length"]

    assert word_min_length["minimum"] == 1
    assert word_min_length["default"] == 5
    Draft7Validator(public_schema).validate(
        {"ace": {"prompt_completion": {"word_min_length": 3}}}
    )
    with pytest.raises(ValidationError):
        Draft7Validator(public_schema).validate(
            {"ace": {"prompt_completion": {"history_word_min_length": 3}}}
        )


def test_config_schema_allows_base_config_without_identity() -> None:
    validator = Draft7Validator(schema())

    validator.validate({})
    validator.validate(
        {
            "use_chezmoi": True,
            "max_running_agents": 10,
        }
    )


def test_config_schema_validates_nested_owner_and_legacy_machine_name() -> None:
    validator = Draft7Validator(schema())

    validator.validate({"id": {"username": "alice-2", "machine_name": "athena"}})
    validator.validate({"machine_name": "athena"})
    validator.validate({"machine_name": "build_host"})
    for invalid in ("Athena", "host-1", "host1", ""):
        with pytest.raises(ValidationError):
            validator.validate({"id": {"username": "alice", "machine_name": invalid}})
    for invalid in ("Alice", "alice.", "a--b", "agents", "sase"):
        with pytest.raises(ValidationError):
            validator.validate({"id": {"username": invalid, "machine_name": "athena"}})

    assert schema()["properties"]["machine_name"]["deprecated"] is True


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


def test_config_schema_accepts_max_running_agents() -> None:
    Draft7Validator(schema()).validate({"max_running_agents": 1})
    Draft7Validator(schema()).validate({"max_running_agents": 25})


def test_config_schema_rejects_max_running_agents_below_minimum() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"max_running_agents": 0})


def test_config_schema_validates_runner_slot_deference() -> None:
    Draft7Validator(schema()).validate(
        {
            "runner_slots": {
                "deference_seconds_per_step": 0,
                "deference_max_seconds": 120,
            }
        }
    )
    for invalid in (
        {"deference_seconds_per_step": -1},
        {"deference_seconds_per_step": True},
        {"deference_max_seconds": -1},
        {"deference_max_seconds": "60"},
        {"unknown": 1},
    ):
        with pytest.raises(ValidationError):
            Draft7Validator(schema()).validate({"runner_slots": invalid})


def test_config_schema_accepts_file_hooks() -> None:
    Draft7Validator(schema()).validate(
        {
            "file_hooks": [
                {
                    "name": "research-highlights",
                    "description": "Render new research reports.",
                    "command": "bob highlights create",
                    "projects": ["sase"],
                    "sidecars": ["research"],
                    "globs": ["20*/*/*.md", "!20*/*/*__*.md"],
                    "ops": ["ADD"],
                    "timeout": "120s",
                },
                {
                    "name": "quick_check",
                    "command": "check-file",
                    "timeout": "250ms",
                },
            ]
        }
    )


@pytest.mark.parametrize(
    "hook",
    [
        {},
        {"name": "valid"},
        {"command": "run"},
        {"name": "Not A Slug", "command": "run"},
        {"name": "valid", "command": ""},
        {"name": "valid", "command": "run", "ops": ["CREATE"]},
        {"name": "valid", "command": "run", "timeout": "2 days"},
        {"name": "valid", "command": "run", "unknown": True},
    ],
)
def test_config_schema_rejects_invalid_file_hooks(hook: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"file_hooks": [hook]})


def test_configured_max_running_agents_reads_merged_config(monkeypatch) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"max_running_agents": 7},
    )

    assert config_core.get_configured_max_running_agents() == 7
    assert config_core.get_max_running_agents() == 7


@pytest.mark.parametrize("value", [None, 0, -1, True, "7"])
def test_configured_max_running_agents_falls_back_to_package_default(
    monkeypatch, value: object
) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"max_running_agents": value},
    )

    assert config_core.get_configured_max_running_agents() == 10


def test_runner_slot_deference_accessors_read_merged_config(monkeypatch) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {
            "runner_slots": {
                "deference_seconds_per_step": 5,
                "deference_max_seconds": 90,
            }
        },
    )

    assert config_core.get_runner_slot_deference_seconds_per_step() == 5
    assert config_core.get_runner_slot_deference_max_seconds() == 90


@pytest.mark.parametrize(
    ("config", "expected_step", "expected_max"),
    [
        ({}, 3, 60),
        ({"runner_slots": None}, 3, 60),
        ({"runner_slots": {"deference_seconds_per_step": True}}, 3, 60),
        ({"runner_slots": {"deference_seconds_per_step": -1}}, 3, 60),
        ({"runner_slots": {"deference_max_seconds": "60"}}, 3, 60),
        ({"runner_slots": {"deference_max_seconds": -1}}, 3, 60),
    ],
)
def test_runner_slot_deference_accessors_fall_back_for_invalid_values(
    monkeypatch,
    config: dict[str, object],
    expected_step: int,
    expected_max: int,
) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)

    assert config_core.get_runner_slot_deference_seconds_per_step() == expected_step
    assert config_core.get_runner_slot_deference_max_seconds() == expected_max


def test_runner_slot_deference_accessors_do_not_propagate_config_errors(
    monkeypatch,
) -> None:
    from sase.config import core as config_core

    def unavailable() -> dict[str, object]:
        raise OSError("config unavailable")

    monkeypatch.setattr(config_core, "load_merged_config", unavailable)

    assert config_core.get_runner_slot_deference_seconds_per_step() == 3
    assert config_core.get_runner_slot_deference_max_seconds() == 60


def test_config_schema_accepts_positive_big_epic_phase_threshold() -> None:
    Draft7Validator(schema()).validate({"bead": {"big_epic_phase_threshold": 1}})
    Draft7Validator(schema()).validate({"bead": {"big_epic_phase_threshold": 8}})


@pytest.mark.parametrize("value", [0, -1, True, "5"])
def test_config_schema_rejects_invalid_big_epic_phase_threshold(
    value: object,
) -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"bead": {"big_epic_phase_threshold": value}}
        )
