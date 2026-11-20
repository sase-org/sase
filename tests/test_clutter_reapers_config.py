"""Config validation and default/schema coverage for clutter-reaper horizons."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from sase.config import core as config_core


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 86400.0),
        ({"procs": {"log_lock_orphan_horizon_seconds": 60}}, 60.0),
        ({"procs": {"log_lock_orphan_horizon_seconds": 0}}, 0.0),
        ({"procs": {"log_lock_orphan_horizon_seconds": -1}}, 86400.0),
        ({"procs": {"log_lock_orphan_horizon_seconds": "day"}}, 86400.0),
        ({"procs": []}, 86400.0),
    ],
)
def test_proc_log_lock_horizon_validation(
    monkeypatch: Any, config: dict[str, Any], expected: float
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)
    assert config_core.get_proc_log_lock_orphan_horizon_seconds() == expected


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 2000),
        ({"procs": {"log_lock_orphan_max_removals": 5}}, 5),
        ({"procs": {"log_lock_orphan_max_removals": 0}}, 2000),
        ({"procs": {"log_lock_orphan_max_removals": "many"}}, 2000),
    ],
)
def test_proc_log_lock_budget_validation(
    monkeypatch: Any, config: dict[str, Any], expected: int
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)
    assert config_core.get_proc_log_lock_orphan_max_removals() == expected


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 600.0),
        ({"agent_names": {"registry_tmp_horizon_seconds": 60}}, 60.0),
        ({"agent_names": {"registry_tmp_horizon_seconds": -5}}, 600.0),
        ({"agent_names": {"registry_tmp_horizon_seconds": True}}, 600.0),
        ({"agent_names": []}, 600.0),
    ],
)
def test_registry_tmp_horizon_validation(
    monkeypatch: Any, config: dict[str, Any], expected: float
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)
    assert config_core.get_agent_name_registry_tmp_horizon_seconds() == expected


@pytest.mark.parametrize(
    ("config", "expected"),
    [
        ({}, 200),
        ({"agent_names": {"registry_tmp_max_removals": 5}}, 5),
        ({"agent_names": {"registry_tmp_max_removals": 0}}, 200),
    ],
)
def test_registry_tmp_budget_validation(
    monkeypatch: Any, config: dict[str, Any], expected: int
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)
    assert config_core.get_agent_name_registry_tmp_max_removals() == expected


def test_clutter_reaper_config_defaults_and_schema() -> None:
    root = Path(__file__).parents[1]
    defaults = yaml.safe_load(
        (root / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "src/sase/config/sase.schema.json").read_text(encoding="utf-8")
    )

    assert defaults["procs"]["log_lock_orphan_horizon_seconds"] == 86400
    assert defaults["procs"]["log_lock_orphan_max_removals"] == 2000
    procs = schema["properties"]["procs"]["properties"]
    assert procs["log_lock_orphan_horizon_seconds"]["default"] == 86400
    assert procs["log_lock_orphan_horizon_seconds"]["minimum"] == 0
    assert procs["log_lock_orphan_max_removals"]["default"] == 2000

    assert defaults["agent_names"]["registry_tmp_horizon_seconds"] == 600
    assert defaults["agent_names"]["registry_tmp_max_removals"] == 200
    agent_names = schema["properties"]["agent_names"]
    assert agent_names["additionalProperties"] is False
    assert agent_names["properties"]["registry_tmp_horizon_seconds"]["default"] == 600
    assert agent_names["properties"]["registry_tmp_max_removals"]["default"] == 200
