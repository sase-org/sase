"""Proc history-limit config validation and default/schema coverage."""

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
        ({}, 100),
        ({"procs": {"history_limit": 7}}, 7),
        ({"procs": {"history_limit": 0}}, 100),
        ({"procs": {"history_limit": True}}, 100),
        ({"procs": {"history_limit": "7"}}, 100),
        ({"procs": []}, 100),
        ({"tasks": {"history_limit": 7}}, 7),
        ({"tasks": {"history_limit": 0}}, 100),
    ],
)
def test_proc_history_limit_validation(
    monkeypatch: Any, config: dict[str, Any], expected: int
) -> None:
    monkeypatch.setattr(config_core, "load_merged_config", lambda: config)
    assert config_core.get_proc_history_limit() == expected


def test_proc_history_limit_prefers_canonical_key_over_legacy(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {
            "procs": {"history_limit": 3},
            "tasks": {"history_limit": 9},
        },
    )

    assert config_core.get_proc_history_limit() == 3


def test_proc_history_limit_legacy_key_alone_still_works(monkeypatch: Any) -> None:
    monkeypatch.setattr(
        config_core,
        "load_merged_config",
        lambda: {"tasks": {"history_limit": 9}},
    )

    assert config_core.get_proc_history_limit() == 9
    # The legacy accessor alias keeps working for callers not yet migrated.
    assert config_core.get_task_history_limit() == 9


def test_proc_history_config_default_and_schema() -> None:
    root = Path(__file__).parents[1]
    defaults = yaml.safe_load(
        (root / "src/sase/default_config.yml").read_text(encoding="utf-8")
    )
    schema = json.loads(
        (root / "src/sase/config/sase.schema.json").read_text(encoding="utf-8")
    )

    assert defaults["procs"]["history_limit"] == 100
    history = schema["properties"]["procs"]["properties"]["history_limit"]
    assert history["type"] == "integer"
    assert history["minimum"] == 1
    assert history["default"] == 100
    assert schema["properties"]["procs"]["additionalProperties"] is False
    assert schema["properties"]["tasks"]["deprecated"] is True
