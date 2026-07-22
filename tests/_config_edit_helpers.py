"""Shared fixtures and builders for config edit tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from sase.config.core import ConfigLayer
from sase.config.inventory import build_config_inventory


EDIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "definitions": {
        "repo": {
            "type": "object",
            "required": ["name"],
            "additionalProperties": False,
            "properties": {"name": {"type": "string"}},
        }
    },
    "properties": {
        "timezone": {"type": "string", "default": "America/New_York"},
        "axe": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"max_hook_runners": {"type": "integer", "default": 3}},
        },
        "linked_repos": {
            "type": "array",
            "items": {"$ref": "#/definitions/repo"},
            "default": [],
        },
    },
}


def config_layer(
    name: str,
    *,
    path: str | None = None,
    strategy: str = "concatenate",
    data: dict[str, Any] | None = None,
    exists: bool = True,
) -> ConfigLayer:
    return ConfigLayer(
        name=name,
        path=path,
        exists=exists,
        list_strategy=strategy,
        data=data or {},
    )


def config_inventory(
    layers: list[ConfigLayer], schema: dict[str, Any] | None = None
) -> Any:
    with patch("sase.config.inventory.load_config_layers", return_value=layers):
        return build_config_inventory(schema=schema or EDIT_SCHEMA)


def user_file_inventory(
    tmp_path: Path, user_text: str, default_data: dict[str, Any]
) -> tuple[Any, Path]:
    """Build a [default, user] inventory backed by a real user ``sase.yml``."""
    user_file = tmp_path / "sase.yml"
    user_file.write_text(user_text, encoding="utf-8")
    user_data = yaml.safe_load(user_text) if user_text.strip() else {}
    layers = [
        config_layer("default", data=default_data),
        config_layer(
            "user", path=str(user_file), strategy="replace", data=user_data or {}
        ),
    ]
    return config_inventory(layers), user_file
