"""Schema and accessor coverage for agent-concurrency and runner-slot limits."""

from __future__ import annotations

import pytest
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError

from tests._config_schema_helpers import schema


pytestmark = pytest.mark.contract


def test_config_schema_accepts_max_running_agents() -> None:
    Draft7Validator(schema()).validate({"max_running_agents": 1})
    Draft7Validator(schema()).validate({"max_running_agents": 25})


def test_config_schema_rejects_max_running_agents_below_minimum() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"max_running_agents": 0})


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


def test_config_schema_accepts_max_agent_pipe_chain() -> None:
    Draft7Validator(schema()).validate({"max_agent_pipe_chain": 1})
    Draft7Validator(schema()).validate({"max_agent_pipe_chain": 8})


def test_config_schema_rejects_max_agent_pipe_chain_below_minimum() -> None:
    with pytest.raises(ValidationError):
        Draft7Validator(schema()).validate({"max_agent_pipe_chain": 0})


def test_max_agent_pipe_chain_reads_merged_config(monkeypatch) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"max_agent_pipe_chain": 3},
    )

    assert config_core.get_max_agent_pipe_chain() == 3


@pytest.mark.parametrize("value", [None, 0, -1, True, "8"])
def test_max_agent_pipe_chain_falls_back_to_package_default(
    monkeypatch, value: object
) -> None:
    from sase.config import core as config_core

    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"max_agent_pipe_chain": value},
    )

    assert config_core.get_max_agent_pipe_chain() == 8


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
