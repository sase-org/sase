"""Default config and schema coverage for the notifications.suppress section."""

from __future__ import annotations

import importlib.resources
import json
from pathlib import Path
from typing import Any

import jsonschema
import pytest
import yaml

from sase.config.core import _load_default_config


def _load_schema() -> dict[str, Any]:
    schema_path = Path(__file__).parent.parent / "config" / "sase.schema.json"
    return json.loads(schema_path.read_text())


def _load_default_config_yaml() -> dict[str, Any]:
    ref = importlib.resources.files("sase").joinpath("default_config.yml")
    return yaml.safe_load(ref.read_text(encoding="utf-8"))


# --- default_config.yml shape ---


def test_default_config_has_notifications_suppress_section() -> None:
    cfg = _load_default_config()
    assert "notifications" in cfg
    assert "suppress" in cfg["notifications"]
    assert isinstance(cfg["notifications"]["suppress"], list)


def test_default_config_suppresses_tui_agent_completion() -> None:
    cfg = _load_default_config()
    rules = cfg["notifications"]["suppress"]
    assert rules == [{"client": "tui", "types": ["agent_completion"]}]


def test_default_config_does_not_suppress_agent_failure() -> None:
    """Failed agents must remain visible in the TUI error path."""
    cfg = _load_default_config()
    rules = cfg["notifications"]["suppress"]
    tui_types: list[str] = []
    for rule in rules:
        if str(rule.get("client", "")).casefold() == "tui":
            tui_types.extend(rule.get("types", []))
    assert "agent_failure" not in tui_types


def test_default_config_yaml_file_matches_loader() -> None:
    """`_load_default_config` and a direct YAML read of the file agree."""
    assert _load_default_config_yaml() == _load_default_config()


# --- schema validation ---


def test_schema_accepts_default_notifications_section() -> None:
    """Validate just the notifications subtree against the notifications schema."""
    schema = _load_schema()
    notifications_schema = schema["properties"]["notifications"]
    cfg = _load_default_config()
    jsonschema.validate(instance=cfg["notifications"], schema=notifications_schema)


def test_schema_accepts_empty_suppress_list() -> None:
    schema = _load_schema()
    jsonschema.validate(
        instance={"notifications": {"suppress": []}},
        schema=schema,
    )


def test_schema_accepts_multiple_clients() -> None:
    schema = _load_schema()
    instance = {
        "notifications": {
            "suppress": [
                {"client": "tui", "types": ["agent_completion"]},
                {"client": "telegram", "types": ["sync_result", "axe_error_digest"]},
                {"client": "mobile", "types": ["plan_approval"]},
            ]
        }
    }
    jsonschema.validate(instance=instance, schema=schema)


def test_schema_accepts_unknown_client_names() -> None:
    """Unknown client names must not be rejected by the parser/schema."""
    schema = _load_schema()
    instance = {
        "notifications": {
            "suppress": [{"client": "future_client", "types": ["agent_completion"]}]
        }
    }
    jsonschema.validate(instance=instance, schema=schema)


def test_schema_rejects_empty_types_list() -> None:
    schema = _load_schema()
    instance = {"notifications": {"suppress": [{"client": "tui", "types": []}]}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


def test_schema_rejects_missing_required_fields() -> None:
    schema = _load_schema()
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"notifications": {"suppress": [{"client": "tui"}]}},
            schema=schema,
        )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(
            instance={"notifications": {"suppress": [{"types": ["agent_completion"]}]}},
            schema=schema,
        )


def test_schema_rejects_extra_fields_on_rule() -> None:
    schema = _load_schema()
    instance = {
        "notifications": {
            "suppress": [
                {"client": "tui", "types": ["agent_completion"], "extra": True}
            ]
        }
    }
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)


def test_schema_rejects_extra_top_level_notifications_field() -> None:
    schema = _load_schema()
    instance = {"notifications": {"suppress": [], "bogus": 1}}
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(instance=instance, schema=schema)
