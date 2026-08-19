"""Shared helpers for config schema regression tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jsonschema.exceptions import ValidationError

from sase.config.inventory import load_config_schema


REPO_ROOT = Path(__file__).resolve().parents[1]


def schema() -> dict[str, Any]:
    return load_config_schema()


def format_schema_error(error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"
