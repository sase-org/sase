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


def test_config_schema_accepts_scoped_statistics_keymaps() -> None:
    Draft7Validator(schema()).validate(
        {
            "ace": {
                "keymaps": {
                    "statistics": {
                        "prev_view": "f12",
                        "next_view": "f11",
                        "cycle_range": "f10",
                        "custom_range": "f9",
                        "cycle_group": "f8",
                        "cycle_project_filter": "f7",
                        "refresh": "f6",
                        "help": "f5",
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


def test_get_max_running_agents_reads_merged_config(monkeypatch) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"max_running_agents": 7},
    )

    assert config_core.get_max_running_agents() == 7


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
