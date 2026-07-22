"""Shared helpers for config schema regression tests."""

from __future__ import annotations

from typing import Any

from jsonschema.exceptions import ValidationError

from sase.config.inventory import load_config_schema


def schema() -> dict[str, Any]:
    return load_config_schema()


def with_machine_name(config: dict[str, Any]) -> dict[str, Any]:
    """Add the explicit test identity required by the public config schema."""
    return {"machine_name": "test_machine", **config}


def format_schema_error(error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"
