"""Regression coverage for the user-facing SASE config schema."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_default_config_matches_public_schema() -> None:
    schema = json.loads((REPO_ROOT / "config/sase.schema.json").read_text())
    default_config = yaml.safe_load(
        (REPO_ROOT / "src/sase/default_config.yml").read_text()
    )

    Draft7Validator.check_schema(schema)
    errors = sorted(
        Draft7Validator(schema).iter_errors(default_config),
        key=lambda error: list(error.absolute_path),
    )

    assert errors == [], "\n".join(_format_schema_error(error) for error in errors)


def _format_schema_error(error: ValidationError) -> str:
    path = ".".join(str(part) for part in error.absolute_path) or "<root>"
    return f"{path}: {error.message}"
