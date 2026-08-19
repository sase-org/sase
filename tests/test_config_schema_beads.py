"""Schema coverage for bead epic-phase and task-triage settings."""

from __future__ import annotations

import pytest
import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import REPO_ROOT, schema


pytestmark = pytest.mark.contract


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


@pytest.mark.parametrize(
    "field, floor",
    [
        ("min_plus_ones", 0),
        ("stale_after_days", 1),
        ("stale_cleanup_min_beads", 1),
    ],
)
def test_config_schema_accepts_task_triage_field_at_its_floor_and_above(
    field: str, floor: int
) -> None:
    Draft7Validator(schema()).validate({"bead": {"task_triage": {field: floor}}})
    Draft7Validator(schema()).validate({"bead": {"task_triage": {field: floor + 10}}})


@pytest.mark.parametrize(
    "field, floor",
    [
        ("min_plus_ones", 0),
        ("stale_after_days", 1),
        ("stale_cleanup_min_beads", 1),
    ],
)
@pytest.mark.parametrize("bad_value_offset", ["below_floor", "bool", "string"])
def test_config_schema_rejects_invalid_task_triage_field(
    field: str, floor: int, bad_value_offset: str
) -> None:
    value: object
    if bad_value_offset == "below_floor":
        value = floor - 1
    elif bad_value_offset == "bool":
        value = True
    else:
        value = "5"

    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"bead": {"task_triage": {field: value}}})


def test_config_schema_rejects_unknown_task_triage_key() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate(
            {"bead": {"task_triage": {"unknown_field": 1}}}
        )


def test_task_triage_schema_defaults_match_default_config_and_constants() -> None:
    from sase.bead import config as bead_config

    public_schema = schema()
    task_triage_schema = public_schema["properties"]["bead"]["properties"][
        "task_triage"
    ]["properties"]
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text()
    )
    default_task_triage = default_config["bead"]["task_triage"]

    assert (
        task_triage_schema["min_plus_ones"]["default"]
        == default_task_triage["min_plus_ones"]
        == bead_config.DEFAULT_TASK_TRIAGE_MIN_PLUS_ONES
    )
    assert (
        task_triage_schema["stale_after_days"]["default"]
        == default_task_triage["stale_after_days"]
        == bead_config.DEFAULT_TASK_TRIAGE_STALE_AFTER_DAYS
    )
    assert (
        task_triage_schema["stale_cleanup_min_beads"]["default"]
        == default_task_triage["stale_cleanup_min_beads"]
        == bead_config.DEFAULT_TASK_TRIAGE_STALE_CLEANUP_MIN_BEADS
    )
